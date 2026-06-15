import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime

from port_utils import DEFAULT_PORT_BASE, next_preferred_port

from runtime_env import (
    app_data_dir,
    app_data_path,
    ensure_profile_subdir,
    profile_dir,
    profile_path,
    resource_path,
)


REGISTRY_PATH = app_data_path("profiles.json")
RUNTIME_FILENAME = "runtime.json"
SEED_PROFILE_NAMES = ["Profil 1", "Profil 2", "Profil 3"]


def _now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="sb-profile-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _safe_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "profile"


def _load_registry():
    if not os.path.exists(REGISTRY_PATH):
        return {"version": 1, "profiles": []}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload.setdefault("version", 1)
    payload.setdefault("profiles", [])
    return payload


def _save_registry(registry):
    _atomic_write_json(REGISTRY_PATH, registry)


def _profile_runtime_path(profile_id):
    return profile_path(RUNTIME_FILENAME, profile_id=profile_id)


def _profile_sort_key(profile):
    return (profile.get("created_at", ""), profile.get("name", ""))


def _is_process_alive(pid):
    if not pid:
        return False

    try:
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=creationflags,
            )
            return str(pid) in result.stdout

        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _url_alive(local_url, expected_profile=None):
    if not local_url:
        return False

    status_url = local_url.rstrip("/") + "/api/status"
    try:
        with urllib.request.urlopen(status_url, timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.load(response)
            if expected_profile and payload.get("profile") != expected_profile:
                return False
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, ValueError):
        return False


def _copy_if_missing(source, destination):
    if not os.path.exists(source) or os.path.exists(destination):
        return False

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _copytree_if_missing(source, destination):
    if not os.path.isdir(source) or os.path.exists(destination):
        return False

    shutil.copytree(source, destination)
    return True


def _ensure_profile_layout(profile_id):
    ensure_profile_subdir("chrome-profile", profile_id=profile_id)
    ensure_profile_subdir("cloudflared-home", profile_id=profile_id)
    ensure_profile_subdir("img_cache", profile_id=profile_id)
    ensure_profile_subdir("debug", profile_id=profile_id)


def _legacy_migration_candidates():
    return {
        "state": [
            app_data_path("state_default.json"),
            resource_path("state_default.json"),
        ],
        "img_cache": [
            os.path.join(app_data_dir(), "img_cache"),
        ],
        "debug": [
            os.path.join(app_data_dir(), "debug"),
        ],
        "chrome_profile": [
            os.path.join(app_data_dir(), "chrome-profile", "default"),
        ],
    }


def _migrate_legacy_default_profile(profile_id):
    _ensure_profile_layout(profile_id)
    candidates = _legacy_migration_candidates()

    for state_path in candidates["state"]:
        if _copy_if_missing(state_path, profile_path("state.json", profile_id=profile_id)):
            break

    for source in candidates["img_cache"]:
        if _copytree_if_missing(source, profile_path("img_cache", profile_id=profile_id)):
            break

    for source in candidates["debug"]:
        if _copytree_if_missing(source, profile_path("debug", profile_id=profile_id)):
            break

    for source in candidates["chrome_profile"]:
        if _copytree_if_missing(source, profile_path("chrome-profile", "legacy-default", profile_id=profile_id)):
            break


def ensure_seed_profiles():
    registry = _load_registry()
    changed = False

    if not registry["profiles"]:
        assigned_ports = []
        for index, name in enumerate(SEED_PROFILE_NAMES, start=1):
            profile_id = f"profile-{index}"
            preferred_port = next_preferred_port(assigned_ports)
            assigned_ports.append(preferred_port)
            registry["profiles"].append(
                {
                    "id": profile_id,
                    "name": name,
                    "created_at": _now_iso(),
                    "last_used_at": None,
                    "preferred_port": preferred_port,
                    "is_seeded": True,
                }
            )
        changed = True

    assigned_ports = set()
    for profile in registry["profiles"]:
        if "created_at" not in profile:
            profile["created_at"] = _now_iso()
            changed = True
        if "last_used_at" not in profile:
            profile["last_used_at"] = None
            changed = True
        preferred_port = profile.get("preferred_port")
        if not isinstance(preferred_port, int):
            try:
                preferred_port = int(preferred_port)
            except (TypeError, ValueError):
                preferred_port = None

        if preferred_port is None or preferred_port <= 0 or preferred_port in assigned_ports:
            profile["preferred_port"] = next_preferred_port(assigned_ports)
            changed = True
        else:
            safe_port = next_preferred_port(assigned_ports, start=preferred_port, step=1)
            if safe_port != preferred_port:
                profile["preferred_port"] = safe_port
                changed = True
        if "is_seeded" not in profile:
            profile["is_seeded"] = False
            changed = True
        assigned_ports.add(profile["preferred_port"])
        _ensure_profile_layout(profile["id"])

    registry["profiles"].sort(key=_profile_sort_key)

    if registry["profiles"]:
        _migrate_legacy_default_profile(registry["profiles"][0]["id"])

    if changed:
        _save_registry(registry)

    return registry["profiles"]


def list_profiles():
    ensure_seed_profiles()
    return sorted(_load_registry()["profiles"], key=_profile_sort_key)


def get_profile(profile_id):
    for profile in list_profiles():
        if profile["id"] == profile_id:
            return profile
    return None


def resolve_profile_name(profile_id):
    profile = get_profile(profile_id)
    return profile["name"] if profile else profile_id


def ensure_profile(profile_id, name=None):
    profiles = list_profiles()
    for profile in profiles:
        if profile["id"] == profile_id:
            return profile

    registry = _load_registry()
    profile = {
        "id": profile_id,
        "name": name or profile_id,
        "created_at": _now_iso(),
        "last_used_at": None,
        "preferred_port": next_preferred_port([item.get("preferred_port") for item in registry["profiles"]]),
        "is_seeded": False,
    }
    registry["profiles"].append(profile)
    _save_registry(registry)
    _ensure_profile_layout(profile_id)
    return profile


def create_profile(name):
    ensure_seed_profiles()
    registry = _load_registry()
    existing_ids = {profile["id"] for profile in registry["profiles"]}

    base_id = _safe_slug(name)
    profile_id = base_id
    counter = 2
    while profile_id in existing_ids:
        profile_id = f"{base_id}-{counter}"
        counter += 1

    used_ports = [profile.get("preferred_port", DEFAULT_PORT_BASE) for profile in registry["profiles"]]
    preferred_port = next_preferred_port(used_ports)

    profile = {
        "id": profile_id,
        "name": name,
        "created_at": _now_iso(),
        "last_used_at": None,
        "preferred_port": preferred_port,
        "is_seeded": False,
    }
    registry["profiles"].append(profile)
    _save_registry(registry)
    _ensure_profile_layout(profile_id)
    return profile


def rename_profile(profile_id, name):
    registry = _load_registry()
    for profile in registry["profiles"]:
        if profile["id"] == profile_id:
            profile["name"] = name
            _save_registry(registry)
            return profile
    raise KeyError(profile_id)


def delete_profile(profile_id):
    registry = _load_registry()
    profile = get_profile(profile_id)
    if not profile:
        return False
    if is_profile_running(profile_id):
        raise RuntimeError("Profil halen çalışıyor")

    registry["profiles"] = [item for item in registry["profiles"] if item["id"] != profile_id]
    _save_registry(registry)
    shutil.rmtree(profile_dir(profile_id), ignore_errors=True)
    return True


def record_profile_launch(profile_id, port):
    registry = _load_registry()
    for profile in registry["profiles"]:
        if profile["id"] == profile_id:
            profile["preferred_port"] = int(port)
            profile["last_used_at"] = _now_iso()
            _save_registry(registry)
            return profile
    return ensure_profile(profile_id)


def mark_profile_running(profile_id, port, pid, local_url):
    payload = {
        "profile_id": profile_id,
        "pid": pid,
        "port": port,
        "local_url": local_url,
        "started_at": _now_iso(),
    }
    _atomic_write_json(_profile_runtime_path(profile_id), payload)
    record_profile_launch(profile_id, port)
    return payload


def clear_profile_runtime(profile_id, pid=None):
    runtime_path = _profile_runtime_path(profile_id)
    if not os.path.exists(runtime_path):
        return

    if pid is not None:
        try:
            with open(runtime_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("pid") != pid:
                return
        except Exception:
            pass

    try:
        os.remove(runtime_path)
    except FileNotFoundError:
        pass


def get_profile_runtime(profile_id):
    runtime_path = _profile_runtime_path(profile_id)
    if not os.path.exists(runtime_path):
        return None
    try:
        with open(runtime_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def cleanup_stale_runtime(profile_id):
    runtime = get_profile_runtime(profile_id)
    if not runtime:
        return None

    if _is_process_alive(runtime.get("pid")):
        if _url_alive(runtime.get("local_url"), expected_profile=profile_id):
            return runtime
        started_at = runtime.get("started_at", "")
        if started_at:
            try:
                started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                if (datetime.now(started_dt.tzinfo) - started_dt).total_seconds() < 30:
                    return runtime
            except ValueError:
                return runtime

    clear_profile_runtime(profile_id, pid=runtime.get("pid"))
    return None


def is_profile_running(profile_id):
    return cleanup_stale_runtime(profile_id) is not None
