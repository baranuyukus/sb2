import os
import platform
from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from runtime_env import resource_path


@dataclass
class BrowserBundle:
    chrome_binary: str
    driver_binary: str


def _mac_candidates(vendor_root):
    candidates = []
    machine = platform.machine().lower()

    preferred_arches = ["arm64", "x64"] if "arm" in machine or "aarch" in machine else ["x64", "arm64"]

    for arch in preferred_arches:
        chrome_binary = os.path.join(
            vendor_root,
            "chrome",
            f"chrome-mac-{arch}",
            "Google Chrome for Testing.app",
            "Contents",
            "MacOS",
            "Google Chrome for Testing",
        )
        driver_binary = os.path.join(
            vendor_root,
            "chromedriver",
            f"chromedriver-mac-{arch}",
            "chromedriver",
        )
        candidates.append(BrowserBundle(chrome_binary=chrome_binary, driver_binary=driver_binary))

    return candidates


def _windows_candidates(vendor_root):
    return [
        BrowserBundle(
            chrome_binary=os.path.join(vendor_root, "chrome", "chrome-win64", "chrome.exe"),
            driver_binary=os.path.join(vendor_root, "chromedriver", "chromedriver-win64", "chromedriver.exe"),
        )
    ]


def _linux_candidates(vendor_root):
    machine = platform.machine().lower()
    preferred_arches = ["linux64"]
    if "arm" in machine or "aarch" in machine:
        preferred_arches = ["linux-arm64", "linux64"]

    candidates = []
    for arch in preferred_arches:
        chrome_binary = os.path.join(vendor_root, "chrome", f"chrome-{arch}", "chrome")
        driver_binary = os.path.join(vendor_root, "chromedriver", f"chromedriver-{arch}", "chromedriver")
        candidates.append(BrowserBundle(chrome_binary=chrome_binary, driver_binary=driver_binary))
    return candidates


def resolve_browser_bundle():
    chrome_env = os.environ.get("SB_CHROME_BINARY")
    driver_env = os.environ.get("SB_CHROMEDRIVER")
    if chrome_env and driver_env and os.path.exists(chrome_env) and os.path.exists(driver_env):
        return BrowserBundle(chrome_binary=chrome_env, driver_binary=driver_env)

    vendor_root = resource_path("vendor")
    if not os.path.isdir(vendor_root):
        return None

    system = platform.system().lower()
    if "darwin" in system:
        candidates = _mac_candidates(vendor_root)
    elif "windows" in system:
        candidates = _windows_candidates(vendor_root)
    else:
        candidates = _linux_candidates(vendor_root)

    for candidate in candidates:
        if os.path.exists(candidate.chrome_binary) and os.path.exists(candidate.driver_binary):
            if not system.startswith("windows"):
                os.chmod(candidate.chrome_binary, 0o755)
                os.chmod(candidate.driver_binary, 0o755)
            return candidate

    return None


def create_webdriver(chrome_options):
    bundle = resolve_browser_bundle()
    if bundle:
        chrome_options.binary_location = bundle.chrome_binary
        service = Service(executable_path=bundle.driver_binary)
        return webdriver.Chrome(service=service, options=chrome_options)
    return webdriver.Chrome(options=chrome_options)
