from __future__ import annotations

import os
import re
import time
import json
import csv
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =========================
# URL CLEANER
# =========================

def clean_google_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None

    p = urlparse(href)
    domain = p.netloc

    # translate.google.* -> "u" contains real URL
    if domain.startswith("translate.google."):
        qs = parse_qs(p.query)
        if qs.get("u"):
            return qs["u"][0]

    # www.google.*/url -> q or url contains real URL
    if domain.startswith("www.google.") and p.path == "/url":
        qs = parse_qs(p.query)
        if qs.get("q"):
            return qs["q"][0]
        if qs.get("url"):
            return qs["url"][0]

    # ignore google-owned urls
    if "google." in domain:
        return None

    return href


def safe_filename(s: str, max_len: int = 70) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_\-\.]+", "", s)
    s = (s[:max_len] or "dork").strip("_-.")
    return s or "dork"


# =========================
# DRIVER SETUP (QUIET)
# =========================

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


# =========================
# SCRAPER CORE
# =========================

ORGANIC_A_SELECTOR = "div.MjjYud div.yuRUbf a"

NEXT_SELECTORS: List[Tuple[str, str]] = [
    (By.ID, "pnnext"),
    (By.CSS_SELECTOR, "a#pnnext"),
    (By.CSS_SELECTOR, "a.LLNLxf#pnnext"),
    (By.XPATH, "//a[@id='pnnext']"),
    (By.XPATH, "//a[contains(text(),'Next')]"),
]


def get_next_button(driver: webdriver.Chrome):
    for by, sel in NEXT_SELECTORS:
        try:
            return driver.find_element(by, sel)
        except Exception:
            pass
    return None


def has_organic_results(driver: webdriver.Chrome) -> bool:
    return len(driver.find_elements(By.CSS_SELECTOR, ORGANIC_A_SELECTOR)) > 0


def wait_for_results_or_captcha(driver: webdriver.Chrome, timeout: int = 12) -> bool:
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ORGANIC_A_SELECTOR)) > 0
        )
        return True
    except Exception:
        return has_organic_results(driver)


def perform_search(driver: webdriver.Chrome, query: str) -> bool:
    driver.get("https://www.google.com/ncr")
    try:
        box = WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.NAME, "q")))
        box.clear()
        box.send_keys(query)
        box.send_keys(Keys.ENTER)
    except Exception:
        return False

    return wait_for_results_or_captcha(driver, timeout=12)


def scrape_current_page(driver: webdriver.Chrome) -> List[str]:
    urls: List[str] = []
    elements = driver.find_elements(By.CSS_SELECTOR, ORGANIC_A_SELECTOR)
    for el in elements:
        raw = el.get_attribute("href")
        clean = clean_google_href(raw)
        if clean:
            urls.append(clean)
    return urls


def crawl_until_last_page(
    driver: webdriver.Chrome,
    dork: str,
    global_seen: Set[str],
    per_dork_seen: Set[str],
    per_dork_urls: List[str],
    url_to_dorks: Dict[str, Set[str]],
    sleep_between_pages: float = 2.0,
    page_offset: int = 0,            # ✅ NEW: absolute page offset
) -> Tuple[str, int]:
    """
    Crawls from the CURRENT results page until:
      - last page (no Next)
      - captcha/block (no organic results)
    Returns (status, pages_crawled_in_this_call)
      status: "done" | "captcha"
    """
    pages = 0

    while True:
        if not has_organic_results(driver):
            return "captcha", pages

        pages += 1
        abs_page = page_offset + pages  # ✅ NEW: show absolute page number across resume sessions

        page_urls = scrape_current_page(driver)

        new_global = 0
        new_for_this_dork = 0

        for u in page_urls:
            if u not in global_seen:
                global_seen.add(u)
                new_global += 1

            if u not in per_dork_seen:
                per_dork_seen.add(u)
                per_dork_urls.append(u)
                new_for_this_dork += 1

            url_to_dorks.setdefault(u, set()).add(dork)

        print(
            f"    [*] Page {abs_page}: +{new_for_this_dork} (dork), +{new_global} (global). "
            f"Global total: {len(global_seen)}"
        )

        next_btn = get_next_button(driver)
        if not next_btn:
            return "done", pages

        try:
            next_btn.click()
        except Exception:
            return "captcha", pages

        time.sleep(sleep_between_pages)


# =========================
# PIPELINE STATE
# =========================

@dataclass
class PipelineState:
    dorks: List[str]
    index: int = 0
    last_status: str = "idle"  # idle|running|captcha|done


def load_dorks(path: str = "dorks.txt") -> List[str]:
    if not os.path.exists(path):
        return []
    dorks: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            q = line.strip()
            if not q or q.startswith("#"):
                continue
            dorks.append(q)
    return dorks


# =========================
# MAIN APP
# =========================

def pipeline_process_from_current_state(
    driver: webdriver.Chrome,
    state: PipelineState,
    global_seen: Set[str],
    per_dork_urls: Dict[str, List[str]],
    per_dork_seen: Dict[str, Set[str]],
    url_to_dorks: Dict[str, Set[str]],
    dork_page_offset: Dict[str, int],     # ✅ NEW: store per-dork absolute offset
    mode: str
) -> None:
    """
    mode:
      - "run": perform_search() for current dork, then crawl
      - "resume": do NOT perform_search() (expects user solved captcha and stayed on results page)
    """
    state.last_status = "running"

    while state.index < len(state.dorks):
        dork = state.dorks[state.index]
        print(f"\n[+] Dork {state.index + 1}/{len(state.dorks)}: {dork}")

        per_dork_urls.setdefault(dork, [])
        per_dork_seen.setdefault(dork, set())
        dork_page_offset.setdefault(dork, 0)  # ✅ init

        if mode == "run":
            ok = perform_search(driver, dork)
            if not ok:
                print("[!] Could not load results (CAPTCHA/block likely).")
                print("[!] Solve CAPTCHA manually in the browser, then type 'resume' to continue.\n")
                state.last_status = "captcha"
                return

        elif mode == "resume":
            ok = wait_for_results_or_captcha(driver, timeout=6)
            if not ok:
                print("[!] Still no organic results.")
                print("[!] Make sure CAPTCHA is solved AND you are on the Google results page, then type 'resume' again.\n")
                state.last_status = "captcha"
                return

        status, pages = crawl_until_last_page(
            driver=driver,
            dork=dork,
            global_seen=global_seen,
            per_dork_seen=per_dork_seen[dork],
            per_dork_urls=per_dork_urls[dork],
            url_to_dorks=url_to_dorks,
            sleep_between_pages=2.0,
            page_offset=dork_page_offset[dork],  # ✅ absolute page numbering
        )

        # ✅ IMPORTANT: update offset regardless of status
        dork_page_offset[dork] += pages

        if status == "captcha":
            print("[!] CAPTCHA/block detected during crawling.")
            print("[!] Solve CAPTCHA manually, then type 'resume' to continue.\n")
            state.last_status = "captcha"
            return

        print(f"[✓] Dork finished: {dork_page_offset[dork]} total pages crawled for this dork.")
        state.index += 1

        # After finishing one dork, next dork should always start with a new search
        mode = "run"

    state.last_status = "done"
    print("\n[✓] Pipeline complete. All dorks processed.\n")


def main():
    dorks = load_dorks("dorks.txt")
    if not dorks:
        print("[!] dorks.txt not found or empty.")
        print("    Create dorks.txt in the same folder, one dork per line.")
        return

    driver = get_silent_driver()
    driver.maximize_window()

    state = PipelineState(dorks=dorks)

    global_seen: Set[str] = set()
    per_dork_urls: Dict[str, List[str]] = {}
    per_dork_seen: Dict[str, Set[str]] = {}
    url_to_dorks: Dict[str, Set[str]] = {}

    # ✅ NEW: keeps absolute page progress per dork (fixes resume log page number)
    dork_page_offset: Dict[str, int] = {}

    print("[*] Multi-dork Google crawler started.")
    print("[*] Commands:")
    print("    run    → start pipeline (auto search each dork + next until end)")
    print("    resume → continue AFTER CAPTCHA from current page/dork")
    print("    status → show current progress")
    print("    save   → save outputs (success.txt, results/, url_to_dorks.csv/json)")
    print("    clear  → clear collected data (keeps dorks)")
    print("    exit   → quit\n")

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "run":
            pipeline_process_from_current_state(
                driver=driver,
                state=state,
                global_seen=global_seen,
                per_dork_urls=per_dork_urls,
                per_dork_seen=per_dork_seen,
                url_to_dorks=url_to_dorks,
                dork_page_offset=dork_page_offset,
                mode="run"
            )

        elif cmd == "resume":
            if state.last_status != "captcha":
                print("[!] 'resume' is only meaningful after a CAPTCHA stop.\n")
                continue

            pipeline_process_from_current_state(
                driver=driver,
                state=state,
                global_seen=global_seen,
                per_dork_urls=per_dork_urls,
                per_dork_seen=per_dork_seen,
                url_to_dorks=url_to_dorks,
                dork_page_offset=dork_page_offset,
                mode="resume"
            )

        elif cmd == "status":
            print(f"[*] Status: {state.last_status}")
            print(f"[*] Dork progress: {state.index}/{len(state.dorks)}")
            if state.index < len(state.dorks):
                print(f"[*] Current dork: {state.dorks[state.index]}")
            print(f"[*] Global unique URLs: {len(global_seen)}")
            print(f"[*] URL→dorks mappings: {len(url_to_dorks)}")

            # show current dork page progress if available
            if state.index < len(state.dorks):
                d = state.dorks[state.index]
                if d in dork_page_offset:
                    print(f"[*] Current dork pages crawled so far: {dork_page_offset[d]}")
            print()

        elif cmd == "save":
            with open("success.txt", "w", encoding="utf-8") as f:
                for u in sorted(global_seen):
                    f.write(u + "\n")
            print(f"[+] Saved {len(global_seen)} unique URLs to success.txt")

            os.makedirs("results", exist_ok=True)
            for dork, urls in per_dork_urls.items():
                fname = safe_filename(dork) + ".txt"
                path = os.path.join("results", fname)
                with open(path, "w", encoding="utf-8") as f:
                    for u in urls:
                        f.write(u + "\n")
            print("[+] Saved per-dork files to ./results/")

            with open("url_to_dorks.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["url", "dorks"])
                for url in sorted(url_to_dorks.keys()):
                    dlist = sorted(url_to_dorks[url])
                    w.writerow([url, ";".join(dlist)])
            print("[+] Saved url_to_dorks.csv")

            json_dump = {url: sorted(list(ds)) for url, ds in url_to_dorks.items()}
            with open("url_to_dorks.json", "w", encoding="utf-8") as f:
                json.dump(json_dump, f, ensure_ascii=False, indent=2)
            print("[+] Saved url_to_dorks.json\n")

        elif cmd == "clear":
            global_seen.clear()
            per_dork_urls.clear()
            per_dork_seen.clear()
            url_to_dorks.clear()
            dork_page_offset.clear()
            state.index = 0
            state.last_status = "idle"
            print("[*] Cleared collected data and reset pipeline index.\n")

        elif cmd == "exit":
            driver.quit()
            print("[*] Exiting...")
            break

        else:
            print("[!] Unknown command. Use: run | resume | status | save | clear | exit\n")


if __name__ == "__main__":
    main()
