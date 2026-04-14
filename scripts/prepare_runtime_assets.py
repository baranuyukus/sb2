#!/usr/bin/env python3

import argparse
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile


CHROME_JSON_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"


def download_file(url, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    print(f"[*] Downloading {url}")
    urllib.request.urlretrieve(url, destination)
    return destination


def extract_zip(zip_path, output_dir):
    with zipfile.ZipFile(zip_path) as archive:
        for entry in archive.infolist():
            archive.extract(entry, output_dir)
            extracted_path = os.path.join(output_dir, entry.filename)
            mode = entry.external_attr >> 16
            if mode:
                os.chmod(extracted_path, mode)


def mark_macos_bundle_executables(root_dir):
    macho_magics = {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }

    for current_root, _, files in os.walk(root_dir):
        for filename in files:
            path = os.path.join(current_root, filename)
            try:
                with open(path, "rb") as handle:
                    if handle.read(4) not in macho_magics:
                        continue
                current_mode = stat.S_IMODE(os.stat(path).st_mode)
                os.chmod(path, current_mode | 0o111)
            except OSError:
                continue


def extract_tgz(tgz_path, output_dir):
    with tarfile.open(tgz_path, "r:gz") as archive:
        archive.extractall(output_dir, filter="data")


def platform_targets():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if "windows" in system:
        return {
            "cft_platform": "win64",
            "cloudflared_name": "cloudflared.exe",
            "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        }

    if "darwin" in system:
        if "arm" in machine or "aarch" in machine:
            return {
                "cft_platform": "mac-arm64",
                "cloudflared_name": "cloudflared",
                "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
            }
        return {
            "cft_platform": "mac-x64",
            "cloudflared_name": "cloudflared",
            "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        }

    return {
        "cft_platform": "linux64",
        "cloudflared_name": "cloudflared",
        "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    }


def load_chrome_downloads():
    with urllib.request.urlopen(CHROME_JSON_URL) as response:
        payload = json.load(response)
    return payload["channels"]["Stable"]["downloads"]


def find_download(downloads, key, platform_name):
    for entry in downloads[key]:
        if entry["platform"] == platform_name:
            return entry["url"]
    raise RuntimeError(f"Could not find {key} download for platform={platform_name}")


def ensure_cloudflared(vendor_dir, targets):
    output_dir = os.path.join(vendor_dir, "cloudflared")
    final_path = os.path.join(output_dir, targets["cloudflared_name"])
    if os.path.exists(final_path):
        return final_path

    os.makedirs(output_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_name = os.path.join(tmp_dir, os.path.basename(targets["cloudflared_url"]))
        download_file(targets["cloudflared_url"], temp_name)

        if temp_name.endswith(".tgz"):
            extract_tgz(temp_name, output_dir)
        else:
            shutil.copy2(temp_name, final_path)

    if not final_path.endswith(".exe"):
        os.chmod(final_path, 0o755)
    return final_path


def ensure_chrome_bundle(vendor_dir, targets):
    downloads = load_chrome_downloads()
    chrome_url = find_download(downloads, "chrome", targets["cft_platform"])
    driver_url = find_download(downloads, "chromedriver", targets["cft_platform"])

    chrome_root = os.path.join(vendor_dir, "chrome")
    driver_root = os.path.join(vendor_dir, "chromedriver")
    os.makedirs(chrome_root, exist_ok=True)
    os.makedirs(driver_root, exist_ok=True)

    if not (os.listdir(chrome_root) and os.listdir(driver_root)):
        with tempfile.TemporaryDirectory() as tmp_dir:
            chrome_zip = os.path.join(tmp_dir, "chrome.zip")
            driver_zip = os.path.join(tmp_dir, "chromedriver.zip")

            download_file(chrome_url, chrome_zip)
            download_file(driver_url, driver_zip)

            extract_zip(chrome_zip, chrome_root)
            extract_zip(driver_zip, driver_root)

    if platform.system().lower() == "darwin":
        mark_macos_bundle_executables(chrome_root)
        mark_macos_bundle_executables(driver_root)


def main():
    parser = argparse.ArgumentParser(description="Prepare bundled runtime assets for desktop builds")
    parser.add_argument("--output-dir", default="vendor", help="Vendor directory")
    args = parser.parse_args()

    vendor_dir = os.path.abspath(args.output_dir)
    targets = platform_targets()

    cloudflared_path = ensure_cloudflared(vendor_dir, targets)
    ensure_chrome_bundle(vendor_dir, targets)

    print(f"[+] Cloudflared ready at {cloudflared_path}")
    print(f"[+] Browser bundle ready at {vendor_dir}")


if __name__ == "__main__":
    main()
