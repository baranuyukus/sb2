import atexit
import os
import platform
import re
import subprocess
import tarfile
import threading
import urllib.request
from datetime import datetime

from runtime_env import app_data_dir, app_data_path, ensure_app_subdir, resource_path


_UNSET = object()
CLOUDFLARE_URL = None
TUNNEL_PROCESS = None
TUNNEL_PORT = None
TUNNEL_STATUS = "idle"
TUNNEL_ERROR = None
TUNNEL_LOGS = []
MAX_TUNNEL_LOGS = 200
TUNNEL_LOCK = threading.Lock()


def _append_log(message, level="info"):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level,
    }
    with TUNNEL_LOCK:
        TUNNEL_LOGS.append(entry)
        if len(TUNNEL_LOGS) > MAX_TUNNEL_LOGS:
            del TUNNEL_LOGS[:-MAX_TUNNEL_LOGS]
    print(f"[TUNNEL {entry['time']}] [{level.upper()}] {message}")


def _set_state(status=None, error=None, url=_UNSET, port=None):
    global TUNNEL_STATUS, TUNNEL_ERROR, CLOUDFLARE_URL, TUNNEL_PORT
    with TUNNEL_LOCK:
        if status is not None:
            TUNNEL_STATUS = status
        if error is not None:
            TUNNEL_ERROR = error
        if url is not _UNSET:
            CLOUDFLARE_URL = url
        if port is not None:
            TUNNEL_PORT = port


def _platform_download():
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch" in machine

    if "windows" in os_name:
        return (
            "cloudflared.exe",
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        )

    if "darwin" in os_name:
        if is_arm:
            return (
                "cloudflared",
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
            )
        return (
            "cloudflared",
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        )

    if is_arm:
        return (
            "cloudflared",
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
        )
    return (
        "cloudflared",
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    )


def _bundled_binary_path(bin_name):
    candidates = [
        resource_path("vendor", "cloudflared", bin_name),
        resource_path(bin_name),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            if not bin_name.endswith(".exe"):
                os.chmod(candidate, 0o755)
            return candidate
    return None


def _download_to_app_data(bin_name, url):
    bin_dir = ensure_app_subdir("bin")
    bin_path = os.path.join(bin_dir, bin_name)

    if os.path.exists(bin_path):
        if not bin_name.endswith(".exe"):
            os.chmod(bin_path, 0o755)
        return bin_path

    _append_log(f"Cloudflared indiriliyor: {url}")
    if url.endswith(".tgz"):
        tgz_path = app_data_path("bin", f"{bin_name}.tgz")
        urllib.request.urlretrieve(url, tgz_path)
        with tarfile.open(tgz_path, "r:gz") as archive:
            archive.extractall(bin_dir, filter="data")
        os.remove(tgz_path)
    else:
        urllib.request.urlretrieve(url, bin_path)

    if not bin_name.endswith(".exe"):
        os.chmod(bin_path, 0o755)
    _append_log(f"Cloudflared hazır: {bin_path}", "success")
    return bin_path


def ensure_cloudflared_binary():
    bin_name, url = _platform_download()
    bundled = _bundled_binary_path(bin_name)
    if bundled:
        return bundled
    try:
        return _download_to_app_data(bin_name, url)
    except Exception as exc:
        _append_log(f"Cloudflared hazırlanamadı: {exc}", "error")
        _set_state(status="error", error=str(exc), url=None)
        return None


def _cloudflared_env():
    home_dir = ensure_app_subdir("cloudflared-home")
    cloudflared_config_dir = os.path.join(home_dir, ".cloudflared")
    os.makedirs(cloudflared_config_dir, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = home_dir
    env["XDG_CONFIG_HOME"] = home_dir
    env["CLOUDFLARED_HOME"] = cloudflared_config_dir

    if os.name == "nt":
        env["USERPROFILE"] = home_dir

    return env


def _stream_output(stream, url_regex):
    global CLOUDFLARE_URL

    for line in iter(stream.readline, ""):
        if not line:
            break

        clean = line.strip()
        if not clean:
            continue

        level = "error" if " ERR " in f" {clean} " or clean.startswith("ERR") else "info"
        _append_log(clean, level=level)

        match = url_regex.search(clean)
        if match:
            tunnel_url = match.group(0)
            _set_state(status="running", error=None, url=tunnel_url)
            _append_log(f"Global erisim linki hazir: {tunnel_url}", "success")

        lowered = clean.lower()
        if "failed" in lowered or "unable to" in lowered or "error" in lowered:
            if "cannot determine default configuration path" not in lowered:
                with TUNNEL_LOCK:
                    should_mark_error = TUNNEL_STATUS not in {"running", "stopped"}
                if should_mark_error:
                    _set_state(status="error", error=clean)

    try:
        stream.close()
    except Exception:
        pass


def _watch_process(process):
    global TUNNEL_PROCESS

    exit_code = process.wait()
    with TUNNEL_LOCK:
        still_current = TUNNEL_PROCESS is process
        current_status = TUNNEL_STATUS
        current_error = TUNNEL_ERROR

    if not still_current:
        return

    if current_status == "stopped":
        _append_log("Tunnel durduruldu.", "info")
    elif exit_code == 0:
        _set_state(status="stopped", error=None, url=None)
        _append_log("Tunnel temiz sekilde kapandi.", "info")
    else:
        error_message = current_error or f"Tunnel kapandi. Cikis kodu: {exit_code}"
        _set_state(status="error", error=error_message, url=None)
        _append_log(error_message, "error")

    with TUNNEL_LOCK:
        if TUNNEL_PROCESS is process:
            TUNNEL_PROCESS = None


def start_tunnel(port, force=False):
    global TUNNEL_PROCESS

    if os.environ.get("SB_DISABLE_TUNNEL") == "1":
        _append_log("SB_DISABLE_TUNNEL=1 oldugu icin tunnel baslatilmadi.", "warning")
        _set_state(status="stopped", error="Tunnel devre disi", url=None, port=port)
        return False

    with TUNNEL_LOCK:
        if TUNNEL_PROCESS and TUNNEL_PROCESS.poll() is None:
            if not force:
                return True

    if force:
        stop_tunnel()

    bin_path = ensure_cloudflared_binary()
    if not bin_path:
        return False

    _set_state(status="starting", error=None, url=None, port=port)
    _append_log(f"Tunnel baslatiliyor: http://127.0.0.1:{port}", "info")

    cmd = [
        bin_path,
        "--no-autoupdate",
        "tunnel",
        "--url",
        f"http://127.0.0.1:{port}",
    ]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
            cwd=app_data_dir(),
            env=_cloudflared_env(),
        )
    except Exception as exc:
        _set_state(status="error", error=str(exc), url=None, port=port)
        _append_log(f"Tunnel baslatilamadi: {exc}", "error")
        return False

    with TUNNEL_LOCK:
        TUNNEL_PROCESS = process

    url_regex = re.compile(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com")
    threading.Thread(target=_stream_output, args=(process.stdout, url_regex), daemon=True).start()
    threading.Thread(target=_stream_output, args=(process.stderr, url_regex), daemon=True).start()
    threading.Thread(target=_watch_process, args=(process,), daemon=True).start()
    return True


def stop_tunnel():
    global TUNNEL_PROCESS
    try:
        with TUNNEL_LOCK:
            process = TUNNEL_PROCESS
            if not process or process.poll() is not None:
                TUNNEL_PROCESS = None
                process = None
            else:
                TUNNEL_PROCESS = None

        _set_state(status="stopped", error=None, url=None)

        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        return True
    except KeyboardInterrupt:
        return False


def get_tunnel_url():
    with TUNNEL_LOCK:
        return CLOUDFLARE_URL


def get_tunnel_status():
    with TUNNEL_LOCK:
        return {
            "status": TUNNEL_STATUS,
            "url": CLOUDFLARE_URL,
            "error": TUNNEL_ERROR,
            "port": TUNNEL_PORT,
            "logs": TUNNEL_LOGS[-12:],
            "running": bool(TUNNEL_PROCESS and TUNNEL_PROCESS.poll() is None),
        }


atexit.register(stop_tunnel)
