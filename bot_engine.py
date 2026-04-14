#!/usr/bin/env python3
"""
SneakerBaker Bot Engine
========================
Mevcut bot.py'den refactor edilmiş motor sınıfı.
Thread-safe, Flask API ile entegre çalışır.
"""

import time
import hashlib
import random
import re
import json
import os
import platform
import tempfile
import threading
from datetime import datetime

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options

from browser_manager import create_webdriver
from runtime_env import app_data_path, ensure_app_subdir, resource_path

BASE_URL = "https://sneakerbaker.com"
PRODUCTS_URL = f"{BASE_URL}/sat/urunler"
DEBUG_DIR = ensure_app_subdir("debug")


class BotEngine:
    def __init__(self, profile="default"):
        self.profile = profile
        self.state_file = app_data_path(f"state_{profile}.json")
        self.legacy_state_file = resource_path(f"state_{profile}.json")
        self.driver = None
        self.session = None
        self.products = []
        self.product_settings = {}  # {product_id: {auto: bool, min_price: int}}
        self.logs = []
        self.max_logs = 200

        # Bot loop
        self.bot_running = False
        self.bot_thread = None
        self.bot_interval = 300
        self.last_check_time = None

        # Global settings
        self.undercut_amount = 1
        self.min_profit_margin = 500
        
        # Credentials & Cookies
        self.login_email = None
        self.login_password = None
        self.saved_cookies = []

        # Status
        self.logged_in = False
        self.login_waiting = False

        # Data version - increments on every change so frontend can detect updates
        self.data_version = 0

        # Lock for thread safety
        self.lock = threading.Lock()

        # Load saved state
        self._load_state()

    # ─── STATE MANAGEMENT ────────────────────────────────────────

    def _load_state(self):
        try:
            state_path = self.state_file
            if not os.path.exists(state_path) and os.path.exists(self.legacy_state_file):
                state_path = self.legacy_state_file

            if os.path.exists(state_path):
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.product_settings = data.get("product_settings", {})
                self.undercut_amount = data.get("undercut_amount", 1)
                self.min_profit_margin = data.get("min_profit_margin", 500)
                self.bot_interval = data.get("bot_interval", 300)
                self.login_email = data.get("login_email")
                self.login_password = data.get("login_password")
                self.saved_cookies = data.get("saved_cookies", [])
                if state_path != self.state_file:
                    self._save_state()
                self.log(f"💾 [{self.profile}] Kaydedilmiş ayarlar yüklendi")
        except Exception as e:
            self.log(f"⚠️ State yüklenemedi: {e}")

    def _save_state(self):
        try:
            data = {
                "product_settings": self.product_settings,
                "undercut_amount": self.undercut_amount,
                "min_profit_margin": self.min_profit_margin,
                "bot_interval": self.bot_interval,
                "login_email": self.login_email,
                "login_password": self.login_password,
                "saved_cookies": self.saved_cookies,
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"⚠️ State kaydedilemedi: {e}")

    # ─── LOGGING ─────────────────────────────────────────────────

    def log(self, message, level="info"):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]
        print(f"[{entry['time']}] [{level.upper()}] {message}")

    def get_logs(self, since=0):
        with self.lock:
            return self.logs[since:]

    # ─── SELENIUM / LOGIN ────────────────────────────────────────

    def _sec_ch_ua_platform(self):
        system = platform.system().lower()
        if "windows" in system:
            return '"Windows"'
        if "darwin" in system:
            return '"macOS"'
        return '"Linux"'

    def is_driver_alive(self):
        if self.driver is None:
            return False
        try:
            _ = self.driver.current_url
            return True
        except:
            return False

    def open_browser(self):
        """Chrome tarayıcı aç, giriş sayfasına git"""
        self.log("🌐 Chrome tarayıcı açılıyor...")
        self.login_waiting = True

        try:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass

            chrome_options = Options()
            profile_root = ensure_app_subdir("chrome-profile", self.profile)
            profile_dir = tempfile.mkdtemp(prefix="session-", dir=profile_root)
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            chrome_options.add_argument("--no-default-browser-check")
            chrome_options.add_argument("--disable-search-engine-choice-screen")
            chrome_options.add_argument(f"--user-data-dir={profile_dir}")

            self.driver = create_webdriver(chrome_options)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            
            # Timeout ayarları
            self.driver.set_page_load_timeout(30)
            self.driver.implicitly_wait(10)

            self.driver.get(f"{BASE_URL}/giris")
            self.log("✅ Chrome açıldı! Giriş yapmanız bekleniyor...")
            return True
        except Exception as e:
            self.log(f"❌ Chrome açılamadı: {e}", "error")
            self.login_waiting = False
            return False

    def auto_login(self, email, password):
        """Kullanıcının emaili ve şifresi ile otomatik giriş yapar"""
        self.log("🤖 Otomatik giriş başlatılıyor...")
        
        # Tarayıcı açık değilse aç
        if not self.is_driver_alive():
            if not self.open_browser():
                return {"success": False, "error": "Tarayıcı açılamadı"}

        try:
            if self.saved_cookies:
                self.log("🍪 Kayıtlı çerezler (cookieler) bulundu, tarayıcıya ekleniyor...")
                self.driver.get(f"{BASE_URL}/404-bypass-login")
                for cookie in self.saved_cookies:
                    try:
                        # Selenium requires some dictionary keys to be absent or handle strictly
                        self.driver.add_cookie(cookie)
                    except:
                        pass
                
                # Doğrula
                self.driver.get(f"{BASE_URL}/sat/urunler")
                time.sleep(2)
                if "giris" not in self.driver.current_url.lower() and "login" not in self.driver.current_url.lower():
                    self.log("✅ Çerezler geçerli, şifre girmeden anında giriş yapıldı!")
                    if self.confirm_login():
                        return {"success": True}
                else:
                    self.log("⚠️ Çerezlerin süresi dolmuş, form ile giriş deneniyor...", "warning")
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
            
            # /hesabim/ sayfasına git
            self.driver.get(f"{BASE_URL}/hesabim/")
            
            wait = WebDriverWait(self.driver, 10)
            
            # Email gir
            self.log("📧 Email giriliyor...")
            username_input = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            username_input.clear()
            username_input.send_keys(email)
            time.sleep(1)
            
            # Şifre moduna geç
            self.log("🔑 Şifre alanı açılıyor...")
            toggle_mode = wait.until(EC.element_to_be_clickable((By.ID, "sb-toggle-mode")))
            toggle_mode.click()
            time.sleep(1)
            
            # Şifre gir ve enter'a bas
            self.log("🔐 Şifre giriliyor ve onaylanıyor...")
            password_input = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            password_input.clear()
            password_input.send_keys(password)
            time.sleep(0.5)
            password_input.send_keys(Keys.RETURN)
            
            # Girişin başarılı olmasını bekle (URL'nin değişmesi veya sayfanın yüklenmesi)
            self.log("⏳ Giriş yapılması bekleniyor...")
            time.sleep(5) # Basit bir bekleme
            
            # confirm_login çağırarak cookie'leri yakala
            if self.confirm_login():
                return {"success": True}
            else:
                return {"success": False, "error": "Giriş yapılamadı, bilgilerinizi kontrol edin"}
                
        except Exception as e:
            self.log(f"❌ Otomatik giriş hatası: {e}", "error")
            return {"success": False, "error": str(e)}

    def save_credentials(self, email, password):
        self.login_email = email
        self.login_password = password
        self._save_state()

    def confirm_login(self):
        """Kullanıcı giriş yaptığını onayladıktan sonra cookie'leri yakala"""
        if not self.is_driver_alive():
            self.log("❌ Chrome tarayıcı bulunamadı", "error")
            self.login_waiting = False
            return False

        try:
            # /sat/urunler'e git
            current = self.driver.current_url
            if "/sat/urunler" not in current:
                self.driver.get(f"{BASE_URL}/sat/urunler")
                time.sleep(3)

            # Cookie'leri yakala
            selenium_cookies = self.driver.get_cookies()
            cookies = {}
            for cookie in selenium_cookies:
                cookies[cookie["name"]] = cookie["value"]

            user_agent = self.driver.execute_script("return navigator.userAgent")

            # curl_cffi session oluştur
            self.session = cf_requests.Session(impersonate="chrome131")
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            self.session.headers.update({
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": self._sec_ch_ua_platform(),
                "Upgrade-Insecure-Requests": "1",
                "Cookie": cookie_str,
            })
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain="sneakerbaker.com")

            self.saved_cookies = selenium_cookies
            self._save_state()
            self.logged_in = True
            self.login_waiting = False
            self.log(f"✅ Giriş başarılı! {len(cookies)} cookie yakalandı ve kaydedildi [Profil: {self.profile}]")
            return True

        except Exception as e:
            self.log(f"❌ Giriş onaylanamadı: {e}", "error")
            self.login_waiting = False
            return False

    # ─── ÜRÜN ÇEKME ──────────────────────────────────────────────

    def _parse_price(self, price_str):
        if not price_str:
            return 0
        digits = re.sub(r"[^\d]", "", price_str)
        return int(digits) if digits else 0

    def _fetch_page(self, page=1):
        url = f"{PRODUCTS_URL}?page={page}" if page > 1 else PRODUCTS_URL
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Referer": f"{BASE_URL}/sat/urunler",
        }

        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return [], False

            # Debug
            os.makedirs(DEBUG_DIR, exist_ok=True)
            with open(os.path.join(DEBUG_DIR, f"page_{page}.html"), "w", encoding="utf-8") as f:
                f.write(resp.text)

        except Exception as e:
            self.log(f"❌ Sayfa {page} çekilemedi: {e}", "error")
            return [], False

        soup = BeautifulSoup(resp.text, "html.parser")
        products = []
        cards = soup.select("article.card[data-id]")

        for card in cards:
            try:
                pid = card.get("data-id", "")
                title_el = card.select_one(".card-content .title")
                title = title_el.get_text(strip=True) if title_el else "?"

                # Thumbnail URL - proxy üzerinden serve edilecek
                img_el = card.select_one(".thumb")
                img_src = ""
                if img_el:
                    raw_src = img_el.get("src", "")
                    if raw_src:
                        # /api/image-proxy?url=... olarak serve et
                        if raw_src.startswith("http"):
                            img_src = f"/api/image-proxy?url={raw_src}"
                        else:
                            img_src = f"/api/image-proxy?url={BASE_URL}/sat/{raw_src}"

                size_el = card.select_one(".size-badge")
                size = size_el.get_text(strip=True) if size_el else "-"

                sell_el = card.select_one(".sell[data-current-price]")
                current_price = int(sell_el.get("data-current-price", "0")) if sell_el else 0

                cost_el = card.select_one(".cost")
                cost_text = cost_el.get_text(strip=True) if cost_el else "0"
                cost_price = self._parse_price(cost_text)

                min_el = card.select_one(".minPrice[data-min-fiyat]")
                min_price = int(min_el.get("data-min-fiyat", "0")) if min_el else 0

                competitors = []
                if min_el:
                    for p in min_el.select("p"):
                        if "visibility:hidden" in p.get("style", ""):
                            continue
                        pv = self._parse_price(p.get_text(strip=True))
                        if pv > 0:
                            competitors.append(pv)

                # Settings overlay
                settings = self.product_settings.get(str(pid), {})

                products.append({
                    "id": str(pid),
                    "title": title,
                    "image": img_src,
                    "size": size,
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "min_price": min_price,
                    "competitors": competitors,
                    "auto_enabled": settings.get("auto", False),
                    "auto_min_price": settings.get("min_price", 0),
                })
            except Exception as e:
                continue

        has_next = False
        for link in soup.select(".pagination a"):
            if f"page={page + 1}" in link.get("href", ""):
                has_next = True
                break
        if not has_next and len(cards) >= 10:
            has_next = True

        return products, has_next

    def fetch_products(self):
        """Tüm ürünleri çek"""
        if not self.session:
            self.log("⚠️ Önce giriş yapmalısınız", "warning")
            return []

        self.log("📦 Ürünler çekiliyor...")
        all_products = []
        page = 1

        while True:
            products, has_next = self._fetch_page(page)
            if not products:
                if page == 1:
                    self.log("❌ Ürün bulunamadı", "error")
                break
            all_products.extend(products)
            self.log(f"📄 Sayfa {page}: {len(products)} ürün")
            if not has_next:
                break
            page += 1
            time.sleep(random.uniform(0.5, 1.2))

        with self.lock:
            self.products = all_products
            self.data_version += 1

        self.log(f"✅ Toplam {len(all_products)} ürün çekildi!")
        return all_products

    # ─── FİYAT GÜNCELLEME (SELENIUM) ─────────────────────────────

    def _wait_for_antibot(self, timeout=15):
        """SB_ANTIBOT ve jQuery hazır olana kadar bekle"""
        for _ in range(timeout * 2):
            try:
                ready = self.driver.execute_script(
                    "return typeof window.SB_ANTIBOT !== 'undefined' && typeof $ !== 'undefined'"
                )
                if ready:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _simulate_human_behavior(self, min_duration=35, max_duration=65):
        """
        Sayfada insan davranışı simüle et.
        Gerçek DOM event'leri dispatch ederek SB_ANTIBOT'un
        mouse/scroll/key sayaçlarını doldurur.
        """
        if not self.is_driver_alive():
            return

        duration = random.uniform(min_duration, max_duration)
        self.log(f"🧑 İnsan davranışı simüle ediliyor ({duration:.0f}s)...")

        try:
            vw = self.driver.execute_script("return window.innerWidth") or 1200
            vh = self.driver.execute_script("return window.innerHeight") or 800
        except Exception:
            vw, vh = 1200, 800

        start = time.time()

        # Hafif scroll + mouse olayları
        while time.time() - start < duration:
            if not self.bot_running:
                break

            action = random.choice(["scroll", "mouse", "mouse", "pause"])

            if action == "scroll":
                amount = random.randint(80, 350) * random.choice([1, -1])
                self.driver.execute_script(f"""
                    window.scrollBy(0, {amount});
                    window.dispatchEvent(new Event('scroll', {{bubbles: true}}));
                """)
                time.sleep(random.uniform(0.6, 1.8))

            elif action == "mouse":
                # Birkaç arka arkaya mouse hareketi
                for _ in range(random.randint(2, 6)):
                    x = random.randint(60, vw - 60)
                    y = random.randint(60, vh - 60)
                    self.driver.execute_script(f"""
                        document.dispatchEvent(new MouseEvent('mousemove', {{
                            bubbles: true, cancelable: true,
                            clientX: {x}, clientY: {y},
                            movementX: {random.randint(-30, 30)},
                            movementY: {random.randint(-30, 30)}
                        }}));
                    """)
                    time.sleep(random.uniform(0.15, 0.5))

            else:
                # Sessiz bekleme (okuma gibi)
                time.sleep(random.uniform(1.5, 4.0))

        # Sayfanın tepesine dön
        try:
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(random.uniform(0.5, 1.2))
        except Exception:
            pass

        # Kaç olay biriktiğini logla
        try:
            antibot_data = self.driver.execute_script("""
                if (window.SB_ANTIBOT) {
                    var d = window.SB_ANTIBOT.getFormData ? window.SB_ANTIBOT.getFormData() : {};
                    return JSON.stringify(d);
                }
                return '{}';
            """)
            parsed = json.loads(antibot_data or "{}")
            self.log(
                f"📊 SB_ANTIBOT: mouse={parsed.get('sb_mouse_events', '?')} "
                f"key={parsed.get('sb_key_events', '?')} "
                f"scroll={parsed.get('sb_scroll_events', '?')} "
                f"time={parsed.get('sb_time_on_page', '?')}ms"
            )
        except Exception:
            pass

    def _navigate_to_products_page(self):
        """
        Ürünler sayfasına doğal bir yoldan git ve SB_ANTIBOT'un
        hazır olmasını bekle. Batch güncellemeler öncesi bir kez çağrılır.
        """
        if not self.is_driver_alive():
            self.log("❌ Tarayıcı bağlantısı yok!", "error")
            return False

        try:
            current = self.driver.current_url or ""
            already_there = "/sat/urunler" in current

            if not already_there:
                # Doğal navigasyon: önce /sat/ ana sayfasına git
                self.driver.get(f"{BASE_URL}/sat/")
                time.sleep(random.uniform(1.5, 3.0))
                self.driver.get(f"{BASE_URL}/sat/urunler")
            else:
                self.driver.refresh()

            time.sleep(random.uniform(2.0, 3.5))

            if not self._wait_for_antibot(timeout=15):
                self.log("⚠️ SB_ANTIBOT yüklenemedi", "warning")
                return False

            return True
        except Exception as e:
            self.log(f"❌ Ürünler sayfasına gidilemedi: {e}", "error")
            return False

    def _is_on_products_page(self):
        """Tarayıcının /sat/urunler sayfasında olup olmadığını kontrol et"""
        try:
            return "/sat/urunler" in (self.driver.current_url or "")
        except Exception:
            return False

    def update_price(self, product_id, new_price):
        """
        Tek ürünün fiyatını güncelle (Selenium JS ile).
        Sayfaya navigasyon YAPMAZ – çağıran run_auto_cycle/toplu güncelleme
        önceden _navigate_to_products_page() + _simulate_human_behavior() çağırmış olmalı.
        """
        if not self.is_driver_alive():
            return {"success": False, "error": "Tarayıcı bağlantısı yok"}

        if not self._is_on_products_page():
            self.log("⚠️ Sayfa değişmiş, yeniden navigate ediliyor...", "warning")
            if not self._navigate_to_products_page():
                return {"success": False, "error": "Sayfa hazır değil"}
            # Yeniden navigasyon sonrası kısa bir insan simülasyonu
            self._simulate_human_behavior(min_duration=20, max_duration=35)

        self.log(f"💰 Fiyat güncelleniyor: #{product_id} → ₺{new_price:,}")

        js_code = """
        var callback = arguments[arguments.length - 1];
        var productId = arguments[0];
        var newPrice = arguments[1];
        try {
            $.post('generate_sb_token.php', function(data) {
                try {
                    var sb_token = data.sb_token;
                    if (!sb_token) {
                        callback(JSON.stringify({success: false, error: 'Token boş'}));
                        return;
                    }
                    var postData = { num: parseInt(productId), sb_token: sb_token };
                    if (window.SB_ANTIBOT) {
                        var ab = window.SB_ANTIBOT.getFormData();
                        for (var k in ab) postData[k] = ab[k];
                    }
                    postData.price = parseInt(newPrice);
                    $.post('fiyatduzenle.php', postData, function(resp) {
                        callback(JSON.stringify({
                            success: true,
                            response: (typeof resp === 'object') ? JSON.stringify(resp) : String(resp)
                        }));
                    }).fail(function(xhr) {
                        callback(JSON.stringify({success: false, error: 'POST hata: ' + xhr.status}));
                    });
                } catch(e) {
                    callback(JSON.stringify({success: false, error: e.message}));
                }
            }, 'json').fail(function(xhr) {
                callback(JSON.stringify({success: false, error: 'Token hata: ' + xhr.status}));
            });
        } catch(e) {
            callback(JSON.stringify({success: false, error: e.message}));
        }
        """

        try:
            self.driver.set_script_timeout(30)
            result_str = self.driver.execute_async_script(js_code, str(product_id), str(new_price))
            result = json.loads(result_str)

            if result.get("success"):
                resp_text = result.get("response", "")
                if "başarısız" in resp_text.lower() or "geçersiz" in resp_text.lower() or "hata" in resp_text.lower():
                    self.log(f"⚠️ #{product_id}: {resp_text}", "warning")
                    return {"success": False, "error": resp_text}
                self.log(f"✅ #{product_id} fiyat güncellendi: ₺{new_price:,}", "success")
                with self.lock:
                    for p in self.products:
                        if str(p["id"]) == str(product_id):
                            p["current_price"] = new_price
                            break
                    self.data_version += 1
            else:
                self.log(f"❌ #{product_id}: {result.get('error')}", "error")

            return result
        except Exception as e:
            self.log(f"❌ JS execute hata: {e}", "error")
            return {"success": False, "error": str(e)}

    # ─── AUTO UNDERCUT ───────────────────────────────────────────

    def set_product_auto(self, product_id, enabled):
        pid = str(product_id)
        if pid not in self.product_settings:
            self.product_settings[pid] = {}
        self.product_settings[pid]["auto"] = enabled
        # Update product cache
        with self.lock:
            for p in self.products:
                if p["id"] == pid:
                    p["auto_enabled"] = enabled
                    break
        self._save_state()
        self.log(f"{'🟢' if enabled else '🔴'} #{pid} auto undercut {'açıldı' if enabled else 'kapatıldı'}")

    def set_product_min_price(self, product_id, min_price):
        pid = str(product_id)
        if pid not in self.product_settings:
            self.product_settings[pid] = {}
        self.product_settings[pid]["min_price"] = min_price
        with self.lock:
            for p in self.products:
                if p["id"] == pid:
                    p["auto_min_price"] = min_price
                    break
        self._save_state()
        self.log(f"📌 #{pid} min fiyat: ₺{min_price:,}")

    def set_bulk_auto(self, product_ids, enabled):
        for pid in product_ids:
            self.set_product_auto(pid, enabled)

    def calculate_undercut(self, product):
        """Bir ürün için undercut fiyatı hesapla"""
        current = product["current_price"]
        min_market = product["min_price"]
        cost = product["cost_price"]
        auto_min = product.get("auto_min_price", 0)

        if current <= min_market:
            return None, "Zaten en ucuz"

        new_price = min_market - self.undercut_amount
        floor = cost + self.min_profit_margin
        if auto_min > 0:
            floor = max(floor, auto_min)

        if new_price < floor:
            return None, f"Min fiyat engeli (₺{floor:,})"

        return new_price, f"₺{current:,} → ₺{new_price:,}"

    def run_auto_cycle(self):
        """
        Tek döngü auto-undercut çalıştır.
        Akış:
          1. Ürünleri HTTP session ile çek (tarayıcı açmaz)
          2. Tarayıcıyı /sat/urunler'e yönlendir (bir kez)
          3. İnsan davranışı simüle et (mouse/scroll/bekleme)
          4. Tüm fiyat güncellemelerini sıralı yap (sayfayı yenilemeden)
        """
        self.log("🔄 Auto-undercut döngüsü başlıyor...")

        # Güncel ürün listesini çek
        self.fetch_products()

        # Güncellenecek ürünleri belirle
        to_update = []
        skipped = 0
        for product in self.products:
            if not product.get("auto_enabled"):
                continue
            new_price, reason = self.calculate_undercut(product)
            if new_price is None:
                skipped += 1
                self.log(f"⏭ #{product['id']} atlandı: {reason}")
                continue
            to_update.append((product, new_price, reason))

        if not to_update:
            self.last_check_time = datetime.now().strftime("%H:%M:%S")
            self.log(f"✅ Döngü tamamlandı: güncellenecek ürün yok, {skipped} atlandı")
            return

        self.log(f"📋 {len(to_update)} ürün güncellenecek, tarayıcıya geçiliyor...")

        # Tarayıcıya geç ve sayfaya git (bir kez)
        if not self._navigate_to_products_page():
            self.log("❌ Ürünler sayfasına erişilemedi, döngü iptal.", "error")
            return

        # İnsan davranışı simülasyonu – SB_ANTIBOT sayaçlarını doldur
        self._simulate_human_behavior(min_duration=35, max_duration=65)

        updated = 0
        for product, new_price, reason in to_update:
            if not self.bot_running:
                break
            self.log(f"🎯 #{product['id']} {reason}")
            result = self.update_price(product["id"], new_price)
            if result.get("success"):
                updated += 1
            # Ürünler arası doğal bekleme
            time.sleep(random.uniform(2.5, 5.5))

        self.last_check_time = datetime.now().strftime("%H:%M:%S")
        self.log(f"✅ Döngü tamamlandı: {updated} güncellendi, {skipped} atlandı")

    def _bot_loop(self):
        """Arka plan bot döngüsü (ayrı thread'de çalışır)"""
        last_keep_alive = time.time()
        
        while self.bot_running:
            # Otomatik giriş kontrolü
            if not self.logged_in and self.login_email and self.login_password:
                self.log("🤖 Kayıtlı bilgilerle otomatik giriş deneniyor...")
                self.auto_login(self.login_email, self.login_password)
                
            try:
                self.run_auto_cycle()
            except Exception as e:
                self.log(f"❌ Bot döngü hatası: {e}", "error")

            # Interval kadar bekle (erken durdurabilmek için 1s aralıklarla kontrol)
            for _ in range(self.bot_interval):
                if not self.bot_running:
                    break
                
                # Keep Alive - Her 60 saniyede bir tarayıcıyı kontrol et/canlı tut
                if time.time() - last_keep_alive > 60:
                    try:
                        if self.is_driver_alive():
                            # Sadece bir title sorgusu atarak tarayıcı bağlantısını aktif tutarız
                            _ = self.driver.title
                        last_keep_alive = time.time()
                    except:
                        pass
                        
                time.sleep(1)

    def start_bot(self, interval=None):
        if interval:
            self.bot_interval = interval
            self._save_state()

        if self.bot_running:
            self.log("⚠️ Bot zaten çalışıyor")
            return

        self.bot_running = True
        self.bot_thread = threading.Thread(target=self._bot_loop, daemon=True)
        self.bot_thread.start()
        self.log(f"🚀 Bot başlatıldı! Aralık: {self.bot_interval}s")

    def stop_bot(self):
        self.bot_running = False
        self.log("⏹️ Bot durduruldu")

    # ─── STATUS / STATS ──────────────────────────────────────────

    def get_status(self):
        total = len(self.products)
        auto_count = sum(1 for p in self.products if p.get("auto_enabled"))
        needs_cut = sum(1 for p in self.products if p["current_price"] > p["min_price"] and p["min_price"] > 0)

        return {
            "logged_in": self.logged_in,
            "login_waiting": self.login_waiting,
            "browser_alive": self.is_driver_alive(),
            "bot_running": self.bot_running,
            "bot_interval": self.bot_interval,
            "last_check": self.last_check_time,
            "total_products": total,
            "auto_enabled_count": auto_count,
            "needs_undercut_count": needs_cut,
            "undercut_amount": self.undercut_amount,
            "min_profit_margin": self.min_profit_margin,
            "data_version": self.data_version,
        }

    def update_settings(self, undercut=None, min_profit=None, interval=None):
        if undercut is not None:
            self.undercut_amount = undercut
        if min_profit is not None:
            self.min_profit_margin = min_profit
        if interval is not None:
            self.bot_interval = interval
        self._save_state()
        self.log(f"⚙️ Ayarlar güncellendi: Undercut=₺{self.undercut_amount}, MinKâr=₺{self.min_profit_margin}, Aralık={self.bot_interval}s")

    def cleanup(self):
        self.stop_bot()
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
