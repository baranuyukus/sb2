#!/usr/bin/env python3
"""
SneakerBaker Bot - Flask Web Server v2
========================================
Dashboard API + Web arayüzü + Image Proxy
"""

import argparse
import atexit
import hashlib
import os
import socket
import threading
import time
import urllib.request
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

import tunnel_manager
from bot_engine import BotEngine
from curl_cffi import requests as cf_requests
from runtime_env import ensure_app_subdir, resource_path


def parse_args():
    parser = argparse.ArgumentParser(description="SneakerBaker Bot Dashboard")
    parser.add_argument("--profile", type=str, default="default", help="Profile name for isolated state")
    parser.add_argument("--port", type=int, default=5050, help="Preferred port to run on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind host")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the dashboard")
    parser.add_argument("--no-tunnel", action="store_true", help="Do not auto-start the Cloudflare tunnel")
    return parser.parse_args()


def resolve_port(preferred_port):
    port = preferred_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1


def open_browser_when_ready(url):
    if os.environ.get("SB_DISABLE_BROWSER") == "1":
        return

    def opener():
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1):
                    break
            except Exception:
                time.sleep(0.4)
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"[!] Tarayıcı otomatik açılamadı: {exc}")

    threading.Thread(target=opener, daemon=True).start()


ARGS = parse_args()
ARGS.port = resolve_port(ARGS.port)

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
    static_url_path="/static",
)
engine = BotEngine(profile=ARGS.profile)
IMG_CACHE_DIR = ensure_app_subdir("img_cache")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    status = engine.get_status()
    tunnel_status = tunnel_manager.get_tunnel_status()
    status["profile"] = ARGS.profile
    status["tunnel_url"] = tunnel_status["url"]
    status["tunnel_status"] = tunnel_status["status"]
    status["tunnel_error"] = tunnel_status["error"]
    status["tunnel_running"] = tunnel_status["running"]
    status["tunnel_logs"] = tunnel_status["logs"]
    status["local_url"] = f"http://127.0.0.1:{ARGS.port}"
    return jsonify(status)


@app.route("/api/logs")
def api_logs():
    since = request.args.get("since", 0, type=int)
    logs = engine.get_logs(since)
    return jsonify({"logs": logs, "total": len(engine.logs)})


@app.route("/api/bot/login", methods=["POST"])
def api_login():
    success = engine.open_browser()
    return jsonify({"success": success})


@app.route("/api/bot/auto-login", methods=["POST"])
def api_auto_login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"success": False, "error": "Email ve şifre zorunludur"}), 400

    result = engine.auto_login(email, password)
    if result.get("success"):
        engine.save_credentials(email, password)

    return jsonify(result)


@app.route("/api/bot/confirm-login", methods=["POST"])
def api_confirm_login():
    success = engine.confirm_login()
    return jsonify({"success": success})


@app.route("/api/products")
def api_products():
    products = list(engine.products)
    return jsonify({
        "products": products,
        "total": len(engine.products),
        "data_version": engine.data_version,
    })


@app.route("/api/products/refresh", methods=["POST"])
def api_refresh_products():
    products = engine.fetch_products()
    return jsonify({"success": True, "count": len(products)})


@app.route("/api/products/<product_id>/price", methods=["POST"])
def api_update_price(product_id):
    data = request.get_json(silent=True) or {}
    price = data.get("price")
    if not price:
        return jsonify({"success": False, "error": "Fiyat belirtilmedi"}), 400
    result = engine.update_price(product_id, int(price))
    return jsonify(result)


@app.route("/api/products/<product_id>/auto", methods=["POST"])
def api_toggle_auto(product_id):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", False)
    engine.set_product_auto(product_id, enabled)
    return jsonify({"success": True})


@app.route("/api/products/<product_id>/min-price", methods=["POST"])
def api_set_min_price(product_id):
    data = request.get_json(silent=True) or {}
    min_price = data.get("min_price", 0)
    engine.set_product_min_price(product_id, int(min_price))
    return jsonify({"success": True})


@app.route("/api/products/bulk-auto", methods=["POST"])
def api_bulk_auto():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    enabled = data.get("enabled", False)
    engine.set_bulk_auto(ids, enabled)
    return jsonify({"success": True, "count": len(ids)})


@app.route("/api/image-proxy")
def api_image_proxy():
    url = request.args.get("url", "")
    if not url:
        return Response("Missing url", status=400)

    cache_key = hashlib.md5(url.encode()).hexdigest()

    ext = "webp"
    if ".png" in url.lower():
        ext = "png"
    elif ".jpg" in url.lower() or ".jpeg" in url.lower():
        ext = "jpg"

    cache_path = os.path.join(IMG_CACHE_DIR, f"{cache_key}.{ext}")

    if os.path.exists(cache_path):
        content_types = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}
        with open(cache_path, "rb") as file_obj:
            return Response(
                file_obj.read(),
                content_type=content_types.get(ext, "image/webp"),
                headers={"Cache-Control": "public, max-age=86400"},
            )

    try:
        if engine.session:
            resp = engine.session.get(url, timeout=10)
        else:
            resp = cf_requests.get(url, timeout=10, impersonate="chrome131")

        if resp.status_code == 200 and len(resp.content) > 100:
            with open(cache_path, "wb") as file_obj:
                file_obj.write(resp.content)

            ct = resp.headers.get("content-type", "image/webp")
            return Response(
                resp.content,
                content_type=ct,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        return Response("Not found", status=404)
    except Exception as exc:
        return Response(f"Error: {exc}", status=500)


@app.route("/api/bot/start", methods=["POST"])
def api_start_bot():
    data = request.get_json(silent=True) or {}
    interval = data.get("interval")
    engine.start_bot(interval=interval)
    return jsonify({"success": True})


@app.route("/api/bot/stop", methods=["POST"])
def api_stop_bot():
    engine.stop_bot()
    return jsonify({"success": True})


@app.route("/api/tunnel/start", methods=["POST"])
def api_start_tunnel():
    data = request.get_json(silent=True) or {}
    force = data.get("force", True)
    success = tunnel_manager.start_tunnel(ARGS.port, force=force)
    return jsonify({"success": success, **tunnel_manager.get_tunnel_status()})


@app.route("/api/tunnel/stop", methods=["POST"])
def api_stop_tunnel():
    success = tunnel_manager.stop_tunnel()
    return jsonify({"success": success, **tunnel_manager.get_tunnel_status()})


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({
        "undercut_amount": engine.undercut_amount,
        "min_profit_margin": engine.min_profit_margin,
        "bot_interval": engine.bot_interval,
    })


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    data = request.get_json(silent=True) or {}
    engine.update_settings(
        undercut=data.get("undercut_amount"),
        min_profit=data.get("min_profit_margin"),
        interval=data.get("bot_interval"),
    )
    return jsonify({"success": True})


@atexit.register
def cleanup():
    engine.cleanup()


def main():
    local_url = f"http://127.0.0.1:{ARGS.port}"

    print("\n🔥 SneakerBaker Bot Dashboard")
    print(f"👤 Profil: {ARGS.profile}")
    print(f"📍 Local: {local_url}\n")

    if not ARGS.no_tunnel:
        tunnel_manager.start_tunnel(ARGS.port)

    if not ARGS.no_browser:
        open_browser_when_ready(local_url)

    app.run(host=ARGS.host, port=ARGS.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
