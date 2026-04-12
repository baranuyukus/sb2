import os
import sys


APP_NAME = "SneakerBaker"


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
