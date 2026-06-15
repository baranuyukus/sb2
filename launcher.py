#!/usr/bin/env python3

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from tkinter import END, StringVar, Tk
from tkinter import messagebox, simpledialog, ttk

from app import main as run_dashboard
from profile_store import (
    cleanup_stale_runtime,
    create_profile,
    delete_profile,
    list_profiles,
    rename_profile,
)


def parse_launcher_args(argv=None):
    parser = argparse.ArgumentParser(description="SneakerBaker Launcher")
    parser.add_argument("--app-server", action="store_true", help="Run the Flask dashboard server instead of the launcher")
    return parser.parse_known_args(argv)


def resolve_port(preferred_port):
    port = preferred_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1


def build_launch_command(profile_id, port):
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
    return base + ["--app-server", "--profile", profile_id, "--port", str(port), "--open-browser"]


def launch_cwd():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class LauncherWindow:
    def __init__(self):
        self.root = Tk()
        self.root.title("SneakerBaker Launcher")
        self.root.geometry("760x520")
        self.root.minsize(720, 480)
        self.status_var = StringVar(value="Profil seçin ve başlatın.")
        self.details_var = StringVar(value="Aynı anda birden fazla farklı profil çalışabilir.")
        self.profile_rows = {}
        self.spawn_locks = set()

        self._build_ui()
        self.refresh_profiles()
        self.root.after(3000, self.poll_profiles)

    def _build_ui(self):
        self.root.configure(padx=18, pady=18)

        header = ttk.Frame(self.root)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="SneakerBaker", font=("Arial", 18, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Profil seç, ister yeni profil oluştur, ardından paneli ayrı oturum olarak başlat.",
        ).pack(anchor="w", pady=(6, 0))

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True)

        columns = ("name", "status", "port", "last_used")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        self.tree.heading("name", text="Profil")
        self.tree.heading("status", text="Durum")
        self.tree.heading("port", text="Port")
        self.tree.heading("last_used", text="Son Kullanım")
        self.tree.column("name", width=250)
        self.tree.column("status", width=130, anchor="center")
        self.tree.column("port", width=90, anchor="center")
        self.tree.column("last_used", width=180, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_selection_details())
        self.tree.bind("<Double-1>", lambda _event: self.start_selected_profile())

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        action_row = ttk.Frame(self.root)
        action_row.pack(fill="x", pady=14)

        ttk.Button(action_row, text="Başlat", command=self.start_selected_profile).pack(side="left")
        ttk.Button(action_row, text="Açık Paneli Aç", command=self.open_selected_profile).pack(side="left", padx=8)
        ttk.Button(action_row, text="Yeni Profil", command=self.create_profile_dialog).pack(side="left")
        ttk.Button(action_row, text="Yeniden Adlandır", command=self.rename_selected_profile).pack(side="left", padx=8)
        ttk.Button(action_row, text="Sil", command=self.delete_selected_profile).pack(side="left")
        ttk.Button(action_row, text="Yenile", command=self.refresh_profiles).pack(side="right")

        info_box = ttk.Frame(self.root)
        info_box.pack(fill="x", pady=(0, 8))
        ttk.Label(info_box, textvariable=self.status_var, font=("Arial", 11, "bold")).pack(anchor="w")
        ttk.Label(info_box, textvariable=self.details_var, wraplength=700).pack(anchor="w", pady=(6, 0))

    def profile_runtime(self, profile_id):
        return cleanup_stale_runtime(profile_id)

    def selected_profile_id(self):
        selection = self.tree.selection()
        return selection[0] if selection else None

    def update_selection_details(self):
        profile_id = self.selected_profile_id()
        if not profile_id:
            self.status_var.set("Profil seçin ve başlatın.")
            self.details_var.set("Aynı anda birden fazla farklı profil çalışabilir.")
            return

        profile = self.profile_rows.get(profile_id)
        runtime = self.profile_runtime(profile_id)
        if runtime:
            self.status_var.set(f"{profile['name']} şu an çalışıyor.")
            self.details_var.set(f"Local panel: {runtime.get('local_url')}  |  PID: {runtime.get('pid')}")
        else:
            self.status_var.set(f"{profile['name']} başlatılmaya hazır.")
            self.details_var.set(f"Tercih edilen port: {profile.get('preferred_port', 5050)}  |  Profil id: {profile_id}")

    def refresh_profiles(self):
        profiles = list_profiles()
        self.profile_rows = {profile["id"]: profile for profile in profiles}

        existing = set(self.tree.get_children())
        seen = set()
        for profile in profiles:
            runtime = self.profile_runtime(profile["id"])
            status = "Çalışıyor" if runtime else "Hazır"
            port = runtime.get("port") if runtime else profile.get("preferred_port", "—")
            last_used = profile.get("last_used_at") or "—"

            values = (profile["name"], status, port, last_used)
            if profile["id"] in existing:
                self.tree.item(profile["id"], values=values)
            else:
                self.tree.insert("", END, iid=profile["id"], values=values)
            seen.add(profile["id"])

        for item in existing - seen:
            self.tree.delete(item)

        if not self.tree.selection():
            items = self.tree.get_children()
            if items:
                self.tree.selection_set(items[0])

        self.update_selection_details()

    def poll_profiles(self):
        self.refresh_profiles()
        self.root.after(3000, self.poll_profiles)

    def open_selected_profile(self):
        profile_id = self.selected_profile_id()
        if not profile_id:
            messagebox.showwarning("Profil Seçin", "Önce bir profil seçin.")
            return

        runtime = self.profile_runtime(profile_id)
        if not runtime:
            messagebox.showinfo("Açık Oturum Yok", "Bu profil şu an çalışmıyor.")
            return

        webbrowser.open(runtime["local_url"])

    def start_selected_profile(self):
        profile_id = self.selected_profile_id()
        if not profile_id:
            messagebox.showwarning("Profil Seçin", "Önce bir profil seçin.")
            return

        if profile_id in self.spawn_locks:
            return

        profile = self.profile_rows[profile_id]
        runtime = self.profile_runtime(profile_id)
        if runtime:
            self.status_var.set(f"{profile['name']} zaten çalışıyor.")
            self.details_var.set(f"Mevcut local panel açılıyor: {runtime['local_url']}")
            webbrowser.open(runtime["local_url"])
            return

        port = resolve_port(int(profile.get("preferred_port", 5050)))
        command = build_launch_command(profile_id, port)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.spawn_locks.add(profile_id)
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                cwd=launch_cwd(),
            )
            self.status_var.set(f"{profile['name']} başlatılıyor...")
            self.details_var.set(f"Beklenen local panel: http://127.0.0.1:{port}")
            threading.Thread(target=self._release_spawn_lock, args=(profile_id,), daemon=True).start()
        except Exception as exc:
            self.spawn_locks.discard(profile_id)
            messagebox.showerror("Başlatılamadı", str(exc))

    def _release_spawn_lock(self, profile_id):
        time.sleep(4)
        self.spawn_locks.discard(profile_id)
        self.root.after(0, self.refresh_profiles)

    def create_profile_dialog(self):
        name = simpledialog.askstring("Yeni Profil", "Profil adı:", parent=self.root)
        if not name:
            return
        clean_name = name.strip()
        if not clean_name:
            return
        create_profile(clean_name)
        self.refresh_profiles()

    def rename_selected_profile(self):
        profile_id = self.selected_profile_id()
        if not profile_id:
            messagebox.showwarning("Profil Seçin", "Önce bir profil seçin.")
            return

        profile = self.profile_rows[profile_id]
        name = simpledialog.askstring("Yeniden Adlandır", "Yeni profil adı:", initialvalue=profile["name"], parent=self.root)
        if not name:
            return
        clean_name = name.strip()
        if not clean_name:
            return
        rename_profile(profile_id, clean_name)
        self.refresh_profiles()

    def delete_selected_profile(self):
        profile_id = self.selected_profile_id()
        if not profile_id:
            messagebox.showwarning("Profil Seçin", "Önce bir profil seçin.")
            return

        profile = self.profile_rows[profile_id]
        if not messagebox.askyesno("Profili Sil", f"{profile['name']} silinsin mi? Bu profilin kayıtlı verileri kaldırılır."):
            return

        try:
            delete_profile(profile_id)
            self.refresh_profiles()
        except RuntimeError as exc:
            messagebox.showwarning("Profil Çalışıyor", str(exc))

    def run(self):
        self.root.mainloop()


def main(argv=None):
    known, remaining = parse_launcher_args(argv)
    if known.app_server:
        return run_dashboard(remaining)

    LauncherWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
