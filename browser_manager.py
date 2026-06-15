import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as SeleniumChromeOptions
import undetected_chromedriver as uc

from runtime_env import resource_path


@dataclass
class BrowserTarget:
    browser_binary: str
    source: str
    label: str
    driver_binary: str | None = None


MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}

MACOS_XATTRS = ("com.apple.quarantine", "com.apple.provenance")


def _mac_bundle_path(app_name):
    return os.path.join("/Applications", f"{app_name}.app", "Contents", "MacOS", app_name)


def _system_browser_candidates():
    system = platform.system().lower()

    if "darwin" in system:
        return [
            BrowserTarget(_mac_bundle_path("Google Chrome"), "system", "Sistem Chrome"),
            BrowserTarget(_mac_bundle_path("Microsoft Edge"), "system", "Sistem Edge"),
        ]

    if "windows" in system:
        local_app = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        return [
            BrowserTarget(os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"), "system", "Sistem Chrome"),
            BrowserTarget(os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"), "system", "Sistem Chrome"),
            BrowserTarget(os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"), "system", "Sistem Chrome"),
            BrowserTarget(os.path.join(local_app, "Microsoft", "Edge", "Application", "msedge.exe"), "system", "Sistem Edge"),
            BrowserTarget(os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"), "system", "Sistem Edge"),
            BrowserTarget(os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"), "system", "Sistem Edge"),
        ]

    linux_names = [
        ("google-chrome", "Sistem Chrome"),
        ("google-chrome-stable", "Sistem Chrome"),
        ("microsoft-edge", "Sistem Edge"),
        ("microsoft-edge-stable", "Sistem Edge"),
        ("chromium", "Sistem Chromium"),
        ("chromium-browser", "Sistem Chromium"),
    ]
    candidates = []
    for command, label in linux_names:
        path = shutil.which(command)
        if path:
            candidates.append(BrowserTarget(path, "system", label))
    return candidates


def _mac_bundled_targets(vendor_root):
    machine = platform.machine().lower()
    preferred_arches = ["arm64", "x64"] if "arm" in machine or "aarch" in machine else ["x64", "arm64"]
    targets = []
    for arch in preferred_arches:
        targets.append(
            BrowserTarget(
                browser_binary=os.path.join(
                    vendor_root,
                    "chrome",
                    f"chrome-mac-{arch}",
                    "Google Chrome for Testing.app",
                    "Contents",
                    "MacOS",
                    "Google Chrome for Testing",
                ),
                driver_binary=os.path.join(vendor_root, "chromedriver", f"chromedriver-mac-{arch}", "chromedriver"),
                source="bundled",
                label=f"Bundled Chrome ({arch})",
            )
        )
    return targets


def _windows_bundled_targets(vendor_root):
    return [
        BrowserTarget(
            browser_binary=os.path.join(vendor_root, "chrome", "chrome-win64", "chrome.exe"),
            driver_binary=os.path.join(vendor_root, "chromedriver", "chromedriver-win64", "chromedriver.exe"),
            source="bundled",
            label="Bundled Chrome",
        )
    ]


def _linux_bundled_targets(vendor_root):
    return [
        BrowserTarget(
            browser_binary=os.path.join(vendor_root, "chrome", "chrome-linux64", "chrome"),
            driver_binary=os.path.join(vendor_root, "chromedriver", "chromedriver-linux64", "chromedriver"),
            source="bundled",
            label="Bundled Chrome",
        )
    ]


def _is_macho_binary(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def _make_executable(path):
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        os.chmod(path, mode | 0o111)
    except OSError:
        pass


def _remove_macos_xattrs(path):
    if not hasattr(os, "removexattr"):
        return
    for attribute in MACOS_XATTRS:
        try:
            os.removexattr(path, attribute)
        except OSError:
            pass


def _find_app_bundle_root(binary_path):
    path = Path(binary_path).resolve()
    for candidate in [path] + list(path.parents):
        if candidate.suffix == ".app":
            return str(candidate)
    return None


def _repair_macos_target(target):
    app_root = _find_app_bundle_root(target.browser_binary)
    if app_root and os.path.isdir(app_root):
        for root, dirs, files in os.walk(app_root):
            _remove_macos_xattrs(root)
            for directory in dirs:
                _remove_macos_xattrs(os.path.join(root, directory))
            for filename in files:
                candidate = os.path.join(root, filename)
                _remove_macos_xattrs(candidate)
                if _is_macho_binary(candidate):
                    _make_executable(candidate)

    for path in filter(None, (target.browser_binary, target.driver_binary)):
        _remove_macos_xattrs(path)
        if _is_macho_binary(path):
            _make_executable(path)


def _repair_target_permissions(target):
    system = platform.system().lower()
    if "darwin" in system:
        _repair_macos_target(target)
        return
    if system.startswith("windows"):
        return
    for path in filter(None, (target.browser_binary, target.driver_binary)):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def resolve_bundled_target():
    vendor_root = resource_path("vendor")
    if not os.path.isdir(vendor_root):
        return None

    system = platform.system().lower()
    if "darwin" in system:
        candidates = _mac_bundled_targets(vendor_root)
    elif "windows" in system:
        candidates = _windows_bundled_targets(vendor_root)
    else:
        candidates = _linux_bundled_targets(vendor_root)

    for candidate in candidates:
        if os.path.exists(candidate.browser_binary) and candidate.driver_binary and os.path.exists(candidate.driver_binary):
            _repair_target_permissions(candidate)
            return candidate
    return None


def resolve_browser_target():
    chrome_env = os.environ.get("SB_CHROME_BINARY")
    driver_env = os.environ.get("SB_CHROMEDRIVER")
    if chrome_env and os.path.exists(chrome_env):
        target = BrowserTarget(
            browser_binary=chrome_env,
            driver_binary=driver_env if driver_env and os.path.exists(driver_env) else None,
            source="env",
            label="Özel Browser",
        )
        _repair_target_permissions(target)
        return target

    for candidate in _system_browser_candidates():
        if os.path.exists(candidate.browser_binary):
            _repair_target_permissions(candidate)
            return candidate

    return resolve_bundled_target()


def resolved_browser_label():
    target = resolve_browser_target()
    return target.label if target else "Browser bulunamadı"


def _clone_chrome_arguments(chrome_options, fallback_options):
    for arg in getattr(chrome_options, "arguments", []):
        fallback_options.add_argument(arg)
    if getattr(chrome_options, "binary_location", None):
        fallback_options.binary_location = chrome_options.binary_location
    fallback_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    fallback_options.add_experimental_option("useAutomationExtension", False)
    return fallback_options


def _apply_stealth_patches(driver):
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['tr-TR', 'tr', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4]});
                    window.chrome = window.chrome || { runtime: {} };
                """
            },
        )
    except Exception:
        pass


def _launch_with_selenium_manager(chrome_options, target):
    options = _clone_chrome_arguments(chrome_options, SeleniumChromeOptions())
    options.binary_location = target.browser_binary
    driver = webdriver.Chrome(options=options)
    driver.sb_browser_source = target.source
    driver.sb_browser_label = target.label
    _apply_stealth_patches(driver)
    return driver


def _launch_with_uc(chrome_options, target, user_data_dir=None):
    kwargs = {
        "options": chrome_options,
        "use_subprocess": True,
        "user_multi_procs": True,
    }
    if user_data_dir:
        kwargs["user_data_dir"] = user_data_dir
    chrome_options.binary_location = target.browser_binary
    kwargs["browser_executable_path"] = target.browser_binary
    if target.driver_binary:
        kwargs["driver_executable_path"] = target.driver_binary
    driver = uc.Chrome(**kwargs)
    driver.sb_browser_source = target.source
    driver.sb_browser_label = target.label
    return driver


def create_webdriver(chrome_options, user_data_dir=None):
    target = resolve_browser_target()
    if not target:
        raise FileNotFoundError("Başlatılacak Chrome/Edge tarayıcısı bulunamadı")

    if target.source in {"system", "env"}:
        try:
            return _launch_with_selenium_manager(chrome_options, target)
        except Exception as system_exc:
            bundled_target = resolve_bundled_target()
            if bundled_target and bundled_target.browser_binary != target.browser_binary:
                try:
                    return _launch_with_uc(chrome_options, bundled_target, user_data_dir=user_data_dir)
                except Exception as bundled_exc:
                    raise RuntimeError(
                        f"sistem browser açılamadı: {system_exc}; bundled fallback açılamadı: {bundled_exc}"
                    ) from bundled_exc
            raise RuntimeError(f"sistem browser açılamadı: {system_exc}") from system_exc

    try:
        return _launch_with_uc(chrome_options, target, user_data_dir=user_data_dir)
    except Exception as primary_exc:
        try:
            return _launch_with_selenium_manager(chrome_options, target)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"bundled browser açılamadı: {primary_exc}; selenium fallback açılamadı: {fallback_exc}"
            ) from fallback_exc
