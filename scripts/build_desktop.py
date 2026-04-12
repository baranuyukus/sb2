#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys


APP_NAME = "SneakerBaker"


def add_data_argument(path, target):
    separator = ";" if os.name == "nt" else ":"
    return f"{path}{separator}{target}"


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    vendor_dir = os.path.join(repo_root, "vendor")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "curl_cffi",
        "--collect-submodules",
        "selenium",
        "--collect-submodules",
        "urllib3",
        "--collect-submodules",
        "bs4",
        "--add-data",
        add_data_argument(os.path.join(repo_root, "templates"), "templates"),
        "--add-data",
        add_data_argument(os.path.join(repo_root, "static"), "static"),
    ]

    if sys.platform == "darwin":
        command.extend(["--osx-bundle-identifier", "com.sneakerbaker.desktop"])

    command.append(os.path.join(repo_root, "app.py"))

    print("[*] Running:", " ".join(command))
    subprocess.run(command, cwd=repo_root, check=True)

    if os.path.isdir(vendor_dir):
        if sys.platform == "darwin":
            vendor_target = os.path.join(repo_root, "dist", f"{APP_NAME}.app", "Contents", "Resources", "vendor")
        else:
            vendor_target = os.path.join(repo_root, "dist", APP_NAME, "_internal", "vendor")

        shutil.rmtree(vendor_target, ignore_errors=True)
        shutil.copytree(vendor_dir, vendor_target)
        print(f"[*] Copied vendor assets to {vendor_target}")


if __name__ == "__main__":
    main()
