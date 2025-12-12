from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from urllib.parse import urlparse, parse_qs
import time
import subprocess
from typing import List, Set, Optional


# ----------------- URL CLEANER -----------------

def clean_google_href(href: Optional[str]) -> Optional[str]:
    """
    Cleans Google redirect/translation URLs and extracts the REAL URL.
    Returns None if the link belongs to Google itself.
    """
    if not href:
        return None

    p = urlparse(href)
    domain = p.netloc

    # translate.google.* → u parameter contains real URL
    if domain.startswith("translate.google."):
        qs = parse_qs(p.query)
        if "u" in qs and qs["u"]:
            return qs["u"][0]

    # google.com/url → q or url parameters contain real URL
    if domain.startswith("www.google.") and p.path == "/url":
        qs = parse_qs(p.query)
        if "q" in qs and qs["q"]:
            return qs["q"][0]
        if "url" in qs and qs["url"]:
            return qs["url"][0]

    # Ignore all Google-owned URLs
    if "google." in domain:
        return None

    return href


# ----------------- QUIET CHROME SETUP -----------------

def get_silent_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--silent")

    chrome_options.add_experimental_option(
        "excludeSwitches", ["enable-logging", "enable-automation"]
    )
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(log_output=subprocess.DEVNULL)

    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# ----------------- GLOBAL STORAGE -----------------

results: List[str] = []
seen: Set[str] = set()


# ----------------- SCRAPE CURRENT PAGE -----------------

def scrape_current_page(driver: webdriver.Chrome) -> bool:
    """
    Extracts organic search result URLs from the current Google search page.
    Returns False if no results exist (CAPTCHA or blocked page).
    """

    elements = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud div.yuRUbf a")

    if not elements:
        print("[!] No organic results found → CAPTCHA or block detected.")
        print("[!] Solve CAPTCHA manually and run 'auto' again.\n")
        return False

    new_urls = []

    for el in elements:
        raw = el.get_attribute("href")
        clean = clean_google_href(raw)
        if not clean:
            continue

        if clean not in seen:
            seen.add(clean)
            results.append(clean)
            new_urls.append(clean)

    print(f"[*] Added {len(new_urls)} new URLs. Total collected: {len(results)}")
    return True


# ----------------- FIND NEXT BUTTON -----------------

def get_next_button(driver: webdriver.Chrome):
    selectors = [
        (By.ID, "pnnext"),
        (By.CSS_SELECTOR, "a#pnnext"),
        (By.CSS_SELECTOR, "a.LLNLxf#pnnext"),
        (By.XPATH, "//a[@id='pnnext']"),
        (By.XPATH, "//a[contains(text(),'Next')]"),
    ]

    for by, sel in selectors:
        try:
            return driver.find_element(by, sel)
        except:
            pass

    return None


# ----------------- ONE CRAWL STEP -----------------

def crawl_step(driver: webdriver.Chrome) -> bool:
    """
    Scrapes current page, clicks Next, returns True.
    If cannot continue (CAPTCHA or last page), returns False.
    """

    if not scrape_current_page(driver):
        return False

    next_btn = get_next_button(driver)
    if not next_btn:
        print("[✓] No 'Next' button → Last page reached.\n")
        return False

    next_btn.click()
    time.sleep(2)
    return True


# ----------------- FULL AUTO CRAWLER -----------------

def crawl_until_last_page(driver: webdriver.Chrome):
    print("[*] Auto-crawl started...\n")

    step = 0

    while True:
        step += 1
        print(f"[+] Step {step} running...")

        if not crawl_step(driver):
            break

    print(f"[✓] Auto-crawl finished. Total URLs collected: {len(results)}\n")


# ----------------- MAIN PROGRAM -----------------

def main():
    global results, seen

    driver = get_silent_driver()
    driver.maximize_window()
    driver.get("https://www.google.com/ncr")

    print("[*] Google opened.")
    print("[*] Perform your Google search manually in Chrome.")
    print("[*] After the first results page loads, use these commands:\n")

    print("Commands:")
    print("  auto   → Start auto-crawling until last page")
    print("  show   → Display collected URLs")
    print("  save   → Save URLs to success.txt")
    print("  clear  → Reset URL storage")
    print("  exit   → Quit program\n")

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "auto":
            crawl_until_last_page(driver)

        elif cmd == "show":
            print("\n=== COLLECTED URLS ===")
            if not results:
                print("(No URLs collected yet)")
            else:
                for u in results:
                    print("→", u)
            print("=======================\n")

        elif cmd == "save":
            if not results:
                print("[!] No URLs to save.\n")
                continue

            with open("success.txt", "w", encoding="utf-8") as f:
                for u in results:
                    f.write(u + "\n")

            print(f"[+] Saved {len(results)} URLs to success.txt\n")

        elif cmd == "clear":
            results = []
            seen = set()
            print("[*] URL list cleared.\n")

        elif cmd == "exit":
            driver.quit()
            print("[*] Exiting...")
            break

        else:
            print("[!] Unknown command:", cmd)


if __name__ == "__main__":
    main()
