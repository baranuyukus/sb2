#!/usr/bin/env python3
"""
SneakerBaker Auto Fiyat Kırma & Düzenleme Botu v3
===================================================
- Selenium tarayıcı açık kalır (Cloudflare + anti-bot bypass)
- Ürün çekme: curl_cffi ile hızlı parse
- Fiyat güncelleme: Selenium üzerinden JS execute (sitenin kendi anti-bot tokenı)
"""

import time
import hashlib
import random
import re
import json
import os
from urllib.parse import urljoin

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from colorama import Fore, Style, init

init(autoreset=True)

# ─── AYARLAR ────────────────────────────────────────────────────────────────────
BASE_URL = "https://sneakerbaker.com"
PRODUCTS_URL = f"{BASE_URL}/sat/urunler"

UNDERCUT_AMOUNT = 1    # Rakibin fiyatından kaç TL düşük
MIN_PROFIT_MARGIN = 500  # Maliyet üzeri minimum kâr

DEBUG = True
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")

# Global Selenium driver (açık tutulacak)
driver = None


def debug_save(filename, content):
    if not DEBUG:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    filepath = os.path.join(DEBUG_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def print_banner():
    banner = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════╗
║  {Fore.WHITE}🔥 SneakerBaker Auto Fiyat Kırma Botu v3 🔥{Fore.CYAN}                ║
║  {Fore.YELLOW}Selenium + curl_cffi hibrit sistem{Fore.CYAN}                        ║
╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)


def open_browser_for_login():
    """Chrome tarayıcı açar, kullanıcı giriş yapar. Driver açık kalır."""
    global driver

    print(f"\n{Fore.YELLOW}[*] Chrome tarayıcı açılıyor...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[i] Lütfen sneakerbaker.com'a giriş yapın.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[i] Giriş yaptıktan sonra /sat/urunler sayfasına gidin.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[i] Hazır olduğunuzda terminale dönüp ENTER'a basın.{Style.RESET_ALL}\n")

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    driver.get(f"{BASE_URL}/giris")

    input(f"\n{Fore.GREEN}[?] Giriş yaptınız mı? ENTER'a basın...{Style.RESET_ALL}")

    # /sat/urunler sayfasına git (SB_ANTIBOT JS'inin yüklenmesi için)
    current_url = driver.current_url
    if "/sat/urunler" not in current_url:
        print(f"{Fore.YELLOW}[*] /sat/urunler sayfasına gidiliyor...{Style.RESET_ALL}")
        driver.get(f"{BASE_URL}/sat/urunler")
        time.sleep(3)

    # Cookie'leri yakala (curl_cffi session için)
    selenium_cookies = driver.get_cookies()
    cookies = {}
    for cookie in selenium_cookies:
        cookies[cookie["name"]] = cookie["value"]

    user_agent = driver.execute_script("return navigator.userAgent")

    print(f"{Fore.GREEN}[✓] {len(cookies)} adet cookie yakalandı!{Style.RESET_ALL}")
    print(f"{Fore.GREEN}[✓] User-Agent: {user_agent[:60]}...{Style.RESET_ALL}")
    print(f"{Fore.GREEN}[✓] Tarayıcı AÇIK KALIYOR (fiyat güncelleme için gerekli){Style.RESET_ALL}")

    if DEBUG:
        debug_save("cookies.json", json.dumps(cookies, indent=2, ensure_ascii=False))

    return cookies, user_agent


def create_session(cookies, user_agent):
    """curl_cffi Session oluştur (sadece ürün çekme için)"""
    session = cf_requests.Session(impersonate="chrome131")

    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Upgrade-Insecure-Requests": "1",
        "Cookie": cookie_str,
    })

    for name, value in cookies.items():
        session.cookies.set(name, value, domain="sneakerbaker.com")

    return session


def parse_price(price_str):
    if not price_str:
        return 0
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else 0


def fetch_products_page(session, page=1):
    """Ürün sayfasını curl_cffi ile çek ve parse et"""
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
        resp = session.get(url, headers=headers, timeout=30)
        print(f"{Fore.WHITE}  [HTTP] Status: {resp.status_code} | URL: {url}{Style.RESET_ALL}")
        debug_save(f"page_{page}_response.html", resp.text)

        if resp.status_code != 200:
            print(f"{Fore.RED}[!] HTTP {resp.status_code}{Style.RESET_ALL}")
            return [], False
    except Exception as e:
        print(f"{Fore.RED}[!] Sayfa {page} çekilemedi: {e}{Style.RESET_ALL}")
        return [], False

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []
    cards = soup.select("article.card[data-id]")

    if not cards:
        title = soup.select_one("title")
        print(f"{Fore.YELLOW}  [DEBUG] Sayfa title: {title.text if title else 'YOK'}{Style.RESET_ALL}")

    for card in cards:
        try:
            product_id = card.get("data-id", "")
            title_el = card.select_one(".card-content .title")
            title = title_el.get_text(strip=True) if title_el else "Bilinmiyor"
            size_el = card.select_one(".size-badge")
            size = size_el.get_text(strip=True) if size_el else "-"
            sell_el = card.select_one(".sell[data-current-price]")
            current_price = int(sell_el.get("data-current-price", "0")) if sell_el else 0
            cost_el = card.select_one(".cost")
            cost_text = cost_el.get_text(strip=True) if cost_el else "0"
            cost_price = parse_price(cost_text)
            min_price_el = card.select_one(".minPrice[data-min-fiyat]")
            min_price = int(min_price_el.get("data-min-fiyat", "0")) if min_price_el else 0

            competitor_prices = []
            if min_price_el:
                for p in min_price_el.select("p"):
                    style = p.get("style", "")
                    if "visibility:hidden" in style:
                        continue
                    pv = parse_price(p.get_text(strip=True))
                    if pv > 0:
                        competitor_prices.append(pv)

            products.append({
                "id": product_id,
                "title": title,
                "size": size,
                "current_price": current_price,
                "cost_price": cost_price,
                "min_price": min_price,
                "competitor_prices": competitor_prices,
            })
        except Exception as e:
            print(f"{Fore.RED}[!] Parse hatası: {e}{Style.RESET_ALL}")

    has_next = False
    for link in soup.select("a.page-link, a.next, .pagination a"):
        if f"page={page + 1}" in link.get("href", ""):
            has_next = True
            break
    if not has_next and len(cards) >= 10:
        has_next = True

    return products, has_next


def fetch_all_products(session):
    """Tüm sayfalardan ürünleri çek"""
    all_products = []
    page = 1
    print(f"\n{Fore.CYAN}[*] Ürünler çekiliyor...{Style.RESET_ALL}")

    while True:
        products, has_next = fetch_products_page(session, page)
        if not products:
            if page == 1:
                print(f"{Fore.RED}[!] Hiç ürün bulunamadı.{Style.RESET_ALL}")
            break
        all_products.extend(products)
        print(f"{Fore.GREEN}  [✓] Sayfa {page}: {len(products)} ürün (Toplam: {len(all_products)}){Style.RESET_ALL}")
        if not has_next:
            break
        page += 1
        time.sleep(random.uniform(0.5, 1.5))

    print(f"\n{Fore.GREEN}[✓] Toplam {len(all_products)} ürün çekildi!{Style.RESET_ALL}")
    return all_products


def display_products(products):
    print(f"\n{Fore.CYAN}{'='*110}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{'ID':<10} {'Ürün Adı':<45} {'Beden':<8} {'Fiyatın':<12} {'Maliyet':<12} {'En Ucuz':<12} {'Durum'}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*110}{Style.RESET_ALL}")

    for p in products:
        if p["current_price"] <= p["min_price"]:
            status = f"{Fore.GREEN}✓ EN UCUZ{Style.RESET_ALL}"
        else:
            status = f"{Fore.RED}⬇ KIRMA{Style.RESET_ALL}"
        print(f"{p['id']:<10} {p['title'][:44]:<45} {p['size']:<8} ₺{p['current_price']:<11,} ₺{p['cost_price']:<11,} ₺{p['min_price']:<11,} {status}")

    print(f"{Fore.CYAN}{'='*110}{Style.RESET_ALL}")


# ─── FİYAT GÜNCELLEME (SELENIUM İLE) ────────────────────────────────────────────

def is_driver_alive():
    """Driver'ın hala çalışıp çalışmadığını kontrol et"""
    global driver
    if driver is None:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def reconnect_browser():
    """Tarayıcı bağlantısı koptuysa yeniden aç"""
    global driver

    print(f"\n{Fore.RED}[!] Tarayıcı bağlantısı koptu!{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Yeni Chrome penceresi açılıyor...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[i] Lütfen tekrar giriş yapın ve ENTER'a basın.{Style.RESET_ALL}\n")

    # Eski driver'ı temizle
    try:
        driver.quit()
    except:
        pass

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    driver.get(f"{BASE_URL}/giris")

    input(f"\n{Fore.GREEN}[?] Giriş yaptınız mı? ENTER'a basın...{Style.RESET_ALL}")

    # /sat/urunler'e git
    driver.get(f"{BASE_URL}/sat/urunler")
    time.sleep(3)

    # Cookie'leri güncelle (curl_cffi session için de)
    selenium_cookies = driver.get_cookies()
    cookies = {}
    for cookie in selenium_cookies:
        cookies[cookie["name"]] = cookie["value"]
    user_agent = driver.execute_script("return navigator.userAgent")

    print(f"{Fore.GREEN}[✓] Tarayıcı yeniden bağlandı! ({len(cookies)} cookie){Style.RESET_ALL}")
    return cookies, user_agent


def ensure_driver_on_urunler(force_refresh=False):
    """Driver'ın /sat/urunler sayfasında olduğundan emin ol, gerekirse yenile"""
    global driver

    # Driver hayatta mı kontrol et
    if not is_driver_alive():
        cookies, ua = reconnect_browser()
        return cookies, ua

    try:
        current = driver.current_url
        if "/sat/urunler" not in current or force_refresh:
            print(f"{Fore.WHITE}  [*] Sayfa yenileniyor (fresh session)...{Style.RESET_ALL}")
            driver.get(f"{BASE_URL}/sat/urunler")
            time.sleep(3)
            # SB_ANTIBOT'un yüklenmesini bekle
            for _ in range(10):
                ready = driver.execute_script("return typeof window.SB_ANTIBOT !== 'undefined' && typeof $ !== 'undefined'")
                if ready:
                    break
                time.sleep(0.5)
    except Exception as e:
        print(f"{Fore.RED}[!] Tarayıcı hatası: {e}{Style.RESET_ALL}")
        # Bağlantı koptuysa yeniden bağlan
        cookies, ua = reconnect_browser()
        return cookies, ua

    return None, None


def update_price_via_browser(product_id, new_price):
    """
    Fiyat güncellemeyi doğrudan tarayıcıda JavaScript ile yap.
    Sitenin kendi akışını birebir taklit eder:
    1. Sayfayı yenile (fresh session)
    2. $.post('generate_sb_token.php', ..., 'json') ile token al
    3. SB_ANTIBOT.getFormData() ile anti-bot verilerini al
    4. $.post('fiyatduzenle.php', postData) ile fiyat güncelle
    """
    global driver
    # Her güncelleme öncesi sayfayı yenile (fresh PHPSESSID)
    ensure_driver_on_urunler(force_refresh=True)

    # Sitenin kendi JS akışını birebir taklit eden kod
    js_code = """
    var callback = arguments[arguments.length - 1];
    var productId = arguments[0];
    var newPrice = arguments[1];
    
    try {
        // 1. Token al (site: $.post('generate_sb_token.php', fn, 'json'))
        $.post('generate_sb_token.php', function(data) {
            try {
                var sb_token = data.sb_token;
                
                if (!sb_token) {
                    callback(JSON.stringify({success: false, error: 'Token boş döndü', data: JSON.stringify(data)}));
                    return;
                }
                
                // 2. Post verilerini oluştur (site: {num, sb_token})
                var postData = {
                    num: parseInt(productId),
                    sb_token: sb_token
                };
                
                // 3. Anti-bot verileri ekle (site: postData = {...postData, ...antiBotData})
                if (window.SB_ANTIBOT) {
                    var antiBotData = window.SB_ANTIBOT.getFormData();
                    for (var key in antiBotData) {
                        postData[key] = antiBotData[key];
                    }
                }
                
                // 4. Fiyat ekle ve güncelle
                postData.price = parseInt(newPrice);
                
                $.post('fiyatduzenle.php', postData, function(response) {
                    callback(JSON.stringify({
                        success: true, 
                        response: (typeof response === 'object') ? JSON.stringify(response) : String(response),
                        token: sb_token
                    }));
                }).fail(function(xhr, status, error) {
                    callback(JSON.stringify({
                        success: false, 
                        error: 'fiyatduzenle hatası: ' + error,
                        status: xhr.status,
                        responseText: xhr.responseText
                    }));
                });
                
            } catch(innerErr) {
                callback(JSON.stringify({success: false, error: 'İç hata: ' + innerErr.message}));
            }
        }, 'json').fail(function(xhr, status, error) {
            callback(JSON.stringify({success: false, error: 'Token isteği başarısız: ' + error, status: xhr.status}));
        });
    } catch(e) {
        callback(JSON.stringify({success: false, error: 'JS hatası: ' + e.message}));
    }
    """

    try:
        driver.set_script_timeout(30)
        result_str = driver.execute_async_script(js_code, str(product_id), str(new_price))
        result = json.loads(result_str)
        return result
    except Exception as e:
        error_msg = str(e)
        # Bağlantı koptuysa yeniden bağlan ve tekrar dene
        if "Connection refused" in error_msg or "no such session" in error_msg or "not connected" in error_msg:
            print(f"{Fore.YELLOW}  [*] Tarayıcı koptu, yeniden bağlanılıyor...{Style.RESET_ALL}")
            reconnect_browser()
            ensure_driver_on_urunler(force_refresh=True)
            try:
                driver.set_script_timeout(30)
                result_str = driver.execute_async_script(js_code, str(product_id), str(new_price))
                result = json.loads(result_str)
                return result
            except Exception as e2:
                return {"success": False, "error": f"Yeniden deneme başarısız: {e2}"}
        return {"success": False, "error": error_msg}


def calculate_undercut_price(product, undercut_amount=None, min_profit=None):
    if undercut_amount is None:
        undercut_amount = UNDERCUT_AMOUNT
    if min_profit is None:
        min_profit = MIN_PROFIT_MARGIN

    current = product["current_price"]
    min_price = product["min_price"]
    cost = product["cost_price"]

    if current <= min_price:
        return None, "Zaten en ucuz fiyatta"

    new_price = min_price - undercut_amount

    min_allowed = cost + min_profit
    if new_price < min_allowed:
        return None, f"Kâr marjı yetersiz (min: ₺{min_allowed:,}, hesaplanan: ₺{new_price:,})"

    return new_price, f"₺{current:,} → ₺{new_price:,} (₺{current - new_price:,} indirim)"


def auto_undercut(products):
    print(f"\n{Fore.YELLOW}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}  🔪 OTOMATİK FİYAT KIRMA{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Undercut: ₺{UNDERCUT_AMOUNT} | Min kâr: ₺{MIN_PROFIT_MARGIN}{Style.RESET_ALL}")

    to_update = []
    for p in products:
        new_price, reason = calculate_undercut_price(p)
        if new_price is not None:
            to_update.append((p, new_price, reason))
            print(f"{Fore.YELLOW}  [→] {p['title']} ({p['size']}): {reason}{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}  [✓] {p['title']} ({p['size']}): {reason}{Style.RESET_ALL}")

    if not to_update:
        print(f"\n{Fore.GREEN}[✓] Tüm ürünler zaten en uygun fiyatta!{Style.RESET_ALL}")
        return

    print(f"\n{Fore.YELLOW}[!] {len(to_update)} ürünün fiyatı güncellenecek.{Style.RESET_ALL}")
    confirm = input(f"{Fore.CYAN}[?] Devam etmek istiyor musunuz? (e/h): {Style.RESET_ALL}").strip().lower()
    if confirm != "e":
        print(f"{Fore.RED}[!] İptal edildi.{Style.RESET_ALL}")
        return

    success_count = 0
    fail_count = 0

    for product, new_price, reason in to_update:
        print(f"\n{Fore.CYAN}  [*] {product['title']} ({product['size']}) güncelleniyor...{Style.RESET_ALL}")

        result = update_price_via_browser(product["id"], new_price)

        if result.get("success"):
            resp_text = str(result.get("response", ""))
            print(f"{Fore.GREEN}  [✓] ₺{product['current_price']:,} → ₺{new_price:,}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}      Yanıt: {resp_text[:150]}{Style.RESET_ALL}")
            success_count += 1
        else:
            error = result.get("error", "Bilinmeyen hata")
            print(f"{Fore.RED}  [✗] Hata: {error}{Style.RESET_ALL}")
            fail_count += 1

        time.sleep(random.uniform(1, 2.5))

    print(f"\n{Fore.GREEN}{'='*50}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  Sonuç: {success_count} başarılı, {fail_count} başarısız{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'='*50}{Style.RESET_ALL}")


def manual_price_update(products):
    print(f"\n{Fore.CYAN}[*] Manuel fiyat güncelleme modu{Style.RESET_ALL}")

    product_id = input(f"{Fore.CYAN}[?] Ürün ID girin: {Style.RESET_ALL}").strip()
    new_price_str = input(f"{Fore.CYAN}[?] Yeni fiyat (TL): {Style.RESET_ALL}").strip()

    try:
        new_price = int(new_price_str)
    except ValueError:
        print(f"{Fore.RED}[!] Geçersiz fiyat.{Style.RESET_ALL}")
        return

    product = next((p for p in products if str(p["id"]) == str(product_id)), None)
    if product:
        print(f"{Fore.YELLOW}  Ürün: {product['title']} ({product['size']}){Style.RESET_ALL}")
        print(f"{Fore.YELLOW}  Mevcut: ₺{product['current_price']:,} → Yeni: ₺{new_price:,}{Style.RESET_ALL}")

    confirm = input(f"{Fore.CYAN}[?] Güncellensin mi? (e/h): {Style.RESET_ALL}").strip().lower()
    if confirm != "e":
        return

    print(f"{Fore.CYAN}  [*] Tarayıcı üzerinden güncelleniyor...{Style.RESET_ALL}")
    result = update_price_via_browser(product_id, new_price)

    if result.get("success"):
        resp_text = str(result.get("response", ""))
        print(f"{Fore.GREEN}[✓] Fiyat güncellendi! Yanıt: {resp_text[:200]}{Style.RESET_ALL}")
    else:
        error = result.get("error", "Bilinmeyen hata")
        print(f"{Fore.RED}[✗] Hata: {error}{Style.RESET_ALL}")


def continuous_mode(session):
    interval = input(f"{Fore.CYAN}[?] Kontrol aralığı (saniye, varsayılan 300): {Style.RESET_ALL}").strip()
    interval = int(interval) if interval else 300

    print(f"\n{Fore.YELLOW}[*] Sürekli mod. Her {interval}s kontrol. Ctrl+C ile durdur.{Style.RESET_ALL}\n")

    cycle = 0
    while True:
        try:
            cycle += 1
            print(f"\n{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}  📡 Döngü #{cycle} - {time.strftime('%H:%M:%S')}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")

            products = fetch_all_products(session)
            if not products:
                print(f"{Fore.RED}[!] Ürün çekilemedi.{Style.RESET_ALL}")
                break

            to_update = []
            for p in products:
                new_price, reason = calculate_undercut_price(p)
                if new_price is not None:
                    to_update.append((p, new_price, reason))

            if to_update:
                print(f"{Fore.YELLOW}[!] {len(to_update)} ürün güncellenmeli!{Style.RESET_ALL}")
                for product, new_price, reason in to_update:
                    result = update_price_via_browser(product["id"], new_price)
                    status = f"{Fore.GREEN}✓" if result.get("success") else f"{Fore.RED}✗"
                    print(f"  {status} {product['title']} ({product['size']}): {reason}{Style.RESET_ALL}")
                    time.sleep(random.uniform(1, 2.5))
            else:
                print(f"{Fore.GREEN}[✓] Tüm fiyatlar güncel!{Style.RESET_ALL}")

            print(f"\n{Fore.CYAN}[*] Sonraki kontrol: {interval}s sonra...{Style.RESET_ALL}")
            time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}[!] Sürekli mod durduruldu.{Style.RESET_ALL}")
            break


def change_settings():
    global UNDERCUT_AMOUNT, MIN_PROFIT_MARGIN
    print(f"\n{Fore.CYAN}[*] Mevcut: Undercut=₺{UNDERCUT_AMOUNT}, Min kâr=₺{MIN_PROFIT_MARGIN}{Style.RESET_ALL}")
    v = input(f"{Fore.CYAN}[?] Yeni undercut (boş=değiştirme): {Style.RESET_ALL}").strip()
    if v:
        UNDERCUT_AMOUNT = int(v)
    v = input(f"{Fore.CYAN}[?] Yeni min kâr (boş=değiştirme): {Style.RESET_ALL}").strip()
    if v:
        MIN_PROFIT_MARGIN = int(v)
    print(f"{Fore.GREEN}[✓] Ayarlar güncellendi!{Style.RESET_ALL}")


def main_menu(session, products):
    while True:
        print(f"\n{Fore.CYAN}╔══════════════════════════════════════╗{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}📋 ANA MENÜ{Fore.CYAN}                         ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}╠══════════════════════════════════════╣{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}1. Ürünleri Listele{Fore.CYAN}                 ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}2. Ürünleri Yenile{Fore.CYAN}                  ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}3. Otomatik Fiyat Kırma{Fore.CYAN}             ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}4. Manuel Fiyat Güncelle{Fore.CYAN}            ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}5. Sürekli Mod (Auto-Loop){Fore.CYAN}          ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.WHITE}6. Ayarları Değiştir{Fore.CYAN}                ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║  {Fore.RED}0. Çıkış{Fore.CYAN}                            ║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}╚══════════════════════════════════════╝{Style.RESET_ALL}")

        choice = input(f"\n{Fore.CYAN}[?] Seçiminiz: {Style.RESET_ALL}").strip()

        if choice == "1":
            display_products(products)
        elif choice == "2":
            products = fetch_all_products(session)
        elif choice == "3":
            auto_undercut(products)
        elif choice == "4":
            manual_price_update(products)
        elif choice == "5":
            continuous_mode(session)
        elif choice == "6":
            change_settings()
        elif choice == "0":
            print(f"{Fore.YELLOW}[*] Çıkılıyor...{Style.RESET_ALL}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            break
        else:
            print(f"{Fore.RED}[!] Geçersiz seçim.{Style.RESET_ALL}")


def main():
    global driver
    print_banner()

    # 1. Tarayıcı aç (açık kalacak)
    cookies, user_agent = open_browser_for_login()

    # 2. curl_cffi session (ürün çekme için)
    session = create_session(cookies, user_agent)

    # 3. Ürünleri çek
    products = fetch_all_products(session)
    if products:
        display_products(products)

    # 4. Ana menü
    main_menu(session, products)


if __name__ == "__main__":
    main()
