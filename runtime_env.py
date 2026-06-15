import os
import sys


APP_NAME = "SneakerBaker"
DEFAULT_PROFILE_ID = "default"
CURRENT_PROFILE_ID = os.environ.get("SB_PROFILE_ID", DEFAULT_PROFILE_ID)


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def bundle_root():
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    return os.path.join(bundle_root(), *parts)


def app_data_dir():
    if sys.platform.startswith("win"):
        base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    elif sys.platform == "darwin":
        base_dir = os.path.expanduser("~/Library/Application Support")
    else:
        base_dir = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    path = os.path.join(base_dir, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def profiles_root():
    path = os.path.join(app_data_dir(), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def normalize_profile_id(profile_id=None):
    profile = (profile_id or CURRENT_PROFILE_ID or DEFAULT_PROFILE_ID).strip()
    return profile or DEFAULT_PROFILE_ID


def initialize_profile_runtime(profile_id=None):
    global CURRENT_PROFILE_ID
    CURRENT_PROFILE_ID = normalize_profile_id(profile_id)
    os.environ["SB_PROFILE_ID"] = CURRENT_PROFILE_ID
    profile_dir(CURRENT_PROFILE_ID)
    return CURRENT_PROFILE_ID


def current_profile_id():
    return normalize_profile_id(CURRENT_PROFILE_ID)


def profile_dir(profile_id=None):
    path = os.path.join(profiles_root(), normalize_profile_id(profile_id))
    os.makedirs(path, exist_ok=True)
    return path


def profile_path(*parts, profile_id=None):
    path = os.path.join(profile_dir(profile_id), *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def ensure_profile_subdir(*parts, profile_id=None):
    path = os.path.join(profile_dir(profile_id), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def app_data_path(*parts):
    path = os.path.join(app_data_dir(), *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def ensure_app_subdir(*parts):
    path = os.path.join(app_data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path
