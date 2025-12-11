from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from urllib.parse import urlparse, parse_qs
import time
import subprocess
from typing import List, Set, Optional


# ----------------- URL TEMİZLEYİCİ -----------------

def clean_google_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None

    p = urlparse(href)
    domain = p.netloc

    # 1) translate.google domainleri temizle
    if domain.startswith("translate.google."):
        qs = parse_qs(p.query)
        if "u" in qs and qs["u"]:
            return qs["u"][0]

    # 2) google.com/url redirect temizle
    if domain.startswith("www.google.") and p.path == "/url":
        qs = parse_qs(p.query)
        if "q" in qs and qs["q"]:
            return qs["q"][0]
        if "url" in qs and qs["url"]:
            return qs["url"][0]

    # 3) Google linklerini tamamen at
    if "google." in domain:
        return None

    return href


# ----------------- SESSİZ CHROME BAŞLAT -----------------

def get_silent_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--silent")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(log_output=subprocess.DEVNULL)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# ----------------- GLOBAL VERİ -----------------

results: List[str] = []
seen: Set[str] = set()


# ----------------- SAYFADAN URL TOPLAMA -----------------

def scrape_current_page(driver: webdriver.Chrome) -> bool:
    elements = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud div.yuRUbf a")

    if not elements:
        print("[!] Organik sonuç bulunamadı → Muhtemelen CAPTCHA veya blok.")
        print("[!] CAPTCHA'yı çöz ve tekrar 'auto' yaz.\n")
        return False

    yeni = []

    for el in elements:
        raw = el.get_attribute("href")
        clean = clean_google_href(raw)
        if not clean:
            continue

        if clean not in seen:
            seen.add(clean)
            results.append(clean)
            yeni.append(clean)

    print(f"[*] Bu sayfadan {len(yeni)} yeni URL eklendi. Toplam: {len(results)}")
    return True


# ----------------- NEXT BUTONU -----------------

def get_next_button(driver: webdriver.Chrome):
    selectors = [
        (By.ID, "pnnext"),
        (By.CSS_SELECTOR, "a#pnnext"),
        (By.CSS_SELECTOR, "a.LLNLxf#pnnext"),
        (By.XPATH, "//a[@id='pnnext']"),
        (By.XPATH, "//a[contains(text(),'Next')]")
    ]

    for by, sel in selectors:
        try:
            return driver.find_element(by, sel)
        except:
            pass

    return None


# ----------------- TEK ADIMLIK TARAYICI -----------------

def crawl_step(driver: webdriver.Chrome) -> bool:
    if not scrape_current_page(driver):
        return False

    next_btn = get_next_button(driver)
    if not next_btn:
        print("[✓] Next butonu yok → Son sayfa olabilir.\n")
        return False

    next_btn.click()
    time.sleep(2)
    return True


# ----------------- OTOMATİK TARAYICI -----------------

def crawl_until_last_page(driver: webdriver.Chrome):
    print("[*] Otomatik tarama başladı...\n")
    step = 0

    while True:
        step += 1
        print(f"[+] Adım {step} çalışıyor...")

        if not crawl_step(driver):
            break

    print(f"[✓] Tarama tamamlandı. Toplam URL: {len(results)}\n")


# ----------------- ANA PROGRAM -----------------

def main():
    global results, seen

    driver = get_silent_driver()
    driver.maximize_window()
    driver.get("https://www.google.com/ncr")

    print("[*] Google açıldı.")
    print("[*] Aramanı tarayıcıda manuel yap, ardından aşağıdaki komutları kullanabilirsin:\n")
    print("Komutlar:")
    print("  auto      → Next yok olana kadar otomatik tarama")
    print("  show      → Toplanan URL'leri göster")
    print("  save      → URL'leri success.txt'ye yaz")
    print("  clear     → Listeyi ve hafızayı sıfırla")
    print("  exit      → Çıkış\n")

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "auto":
            crawl_until_last_page(driver)

        elif cmd == "show":
            print("\n=== TOPLANAN URL'LER ===")
            if not results:
                print("(Henüz URL toplanmadı)")
            else:
                for u in results:
                    print("→", u)
            print("========================\n")

        elif cmd == "save":
            if not results:
                print("[!] Kaydedilecek URL yok.\n")
                continue

            with open("success.txt", "w", encoding="utf-8") as f:
                for u in results:
                    f.write(u + "\n")

            print(f"[+] success.txt dosyasına {len(results)} URL yazıldı.\n")

        elif cmd == "clear":
            results = []
            seen = set()
            print("[*] Liste sıfırlandı.\n")

        elif cmd == "exit":
            driver.quit()
            print("[*] Çıkılıyor...")
            break

        else:
            print("[!] Bilinmeyen komut:", cmd)


if __name__ == "__main__":
    main()
