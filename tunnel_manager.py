import atexit
import os
import platform
import re
import subprocess
import tarfile
import threading
import urllib.request

from runtime_env import app_data_path, ensure_app_subdir, resource_path


CLOUDFLARE_URL = None
TUNNEL_PROCESS = None
TUNNEL_LOCK = threading.Lock()


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

    print(f"[*] Cloudflared indiriliyor: {url}")
    if url.endswith(".tgz"):
        tgz_path = app_data_path("bin", f"{bin_name}.tgz")
        urllib.request.urlretrieve(url, tgz_path)
        with tarfile.open(tgz_path, "r:gz") as archive:
            archive.extractall(bin_dir)
        os.remove(tgz_path)
    else:
        urllib.request.urlretrieve(url, bin_path)

    if not bin_name.endswith(".exe"):
        os.chmod(bin_path, 0o755)
    print(f"[+] Cloudflared hazır: {bin_path}")
    return bin_path


def ensure_cloudflared_binary():
    bin_name, url = _platform_download()
    bundled = _bundled_binary_path(bin_name)
    if bundled:
        return bundled
    try:
        return _download_to_app_data(bin_name, url)
    except Exception as exc:
        print(f"[-] Cloudflared hazırlanamadı: {exc}")
        return None


def _stream_output(stream, url_regex):
    global CLOUDFLARE_URL
    for line in iter(stream.readline, ""):
        if not line:
            break
        print(line.rstrip())
        match = url_regex.search(line)
        if match and CLOUDFLARE_URL != match.group(0):
            CLOUDFLARE_URL = match.group(0)
            print("\n────────────────────────────────────────────────────────")
            print(" 🌐 GLOBAL ERİŞİM LİNKİ:")
            print(f" ⭐ {CLOUDFLARE_URL}")
            print("────────────────────────────────────────────────────────\n")


def start_tunnel(port):
    global CLOUDFLARE_URL, TUNNEL_PROCESS

    if os.environ.get("SB_DISABLE_TUNNEL") == "1":
        print("[i] SB_DISABLE_TUNNEL=1 olduğu için tunnel başlatılmadı.")
        return

    with TUNNEL_LOCK:
        if TUNNEL_PROCESS and TUNNEL_PROCESS.poll() is None:
            return

        CLOUDFLARE_URL = None
        bin_path = ensure_cloudflared_binary()
        if not bin_path:
            return

        cmd = [bin_path, "tunnel", "--url", f"http://127.0.0.1:{port}"]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        TUNNEL_PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )

    url_regex = re.compile(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com")
    threading.Thread(target=_stream_output, args=(TUNNEL_PROCESS.stdout, url_regex), daemon=True).start()
    threading.Thread(target=_stream_output, args=(TUNNEL_PROCESS.stderr, url_regex), daemon=True).start()


def stop_tunnel():
    global TUNNEL_PROCESS
    with TUNNEL_LOCK:
        if not TUNNEL_PROCESS or TUNNEL_PROCESS.poll() is not None:
            return
        try:
            TUNNEL_PROCESS.terminate()
            TUNNEL_PROCESS.wait(timeout=5)
        except Exception:
            try:
                TUNNEL_PROCESS.kill()
            except Exception:
                pass
        finally:
            TUNNEL_PROCESS = None


def get_tunnel_url():
    return CLOUDFLARE_URL


atexit.register(stop_tunnel)
