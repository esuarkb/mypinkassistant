# explore_rise_seminar.py
# Navigates to Rise + Radiate and Seminar report pages, intercepts API calls.
# Usage: python explore_rise_seminar.py

import os, json, re
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

TARGETS = [
    ("Rise + Radiate IBC Selling Challenge",     "https://mk.marykayintouch.com/s/reports/rise-radiate-ibc-selling-challenge"),
    ("Rise + Radiate ISD Unit Growth Challenge", "https://mk.marykayintouch.com/s/reports/rise-radiate-isd-unit-growth-challenge"),
    ("Seminar Recognition",                      "https://mk.marykayintouch.com/s/reports/seminar-recognition"),
    ("Registration List",                        "https://mk.marykayintouch.com/s/reports/registration-list"),
]

def scrape_page(page, label, url, api_calls):
    print(f"\n{'='*60}")
    print(f"NAVIGATING TO: {label}")
    print(f"URL: {url}")
    api_calls.clear()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)  # let Salesforce/LWC render + fire API calls

    text = page.inner_text("body")
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
    )

    print(f"\n--- PAGE TEXT ---")
    print(text[:3000])

    print(f"\n--- RELEVANT LINKS ---")
    for lnk in links:
        if lnk["text"].strip():
            print(f"  [{lnk['text'][:80]}] -> {lnk['href'][:120]}")

    print(f"\n--- API CALLS INTERCEPTED ({len(api_calls)}) ---")
    for call in api_calls:
        print(f"\n  URL: {call['url'][:120]}")
        print(f"  Status: {call['status']}")
        # Pretty-print JSON if possible
        try:
            parsed = json.loads(call["body"])
            print(f"  Body (JSON): {json.dumps(parsed, indent=2)[:1500]}")
        except Exception:
            print(f"  Body: {call['body'][:500]}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    api_calls = []

    def handle_response(response):
        url = response.url
        if any(k in url for k in ("FOReports/api", "aura?r=", "apexremote", "graphql")):
            try:
                body = response.text()
                api_calls.append({"url": url, "status": response.status, "body": body})
            except Exception:
                api_calls.append({"url": url, "status": response.status, "body": "(unreadable)"})

    page.on("response", handle_response)

    # --- Login ---
    print("Logging in...")
    page.goto("https://apps.marykayintouch.com/customer-list", wait_until="domcontentloaded")
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    page.get_by_role("textbox", name="Consultant Number").fill(USERNAME)
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Password").fill(PASSWORD)
    page.wait_for_timeout(100)
    page.get_by_text("Log In").click()
    page.wait_for_timeout(2000)

    try:
        page.get_by_role("button", name="Finish Logging In").wait_for(state="visible", timeout=5000)
        page.get_by_role("button", name="Finish Logging In").click()
        page.wait_for_timeout(2000)
    except Exception:
        pass

    try:
        page.get_by_role("button", name="New Customer").wait_for(timeout=30000)
        print("Logged in OK.")
    except Exception:
        print("WARNING: may not be logged in fully, continuing...")

    # --- Scrape each target ---
    for label, url in TARGETS:
        scrape_page(page, label, url, api_calls)

    print("\n\nAll pages scraped. Browser open for manual inspection.")
    print("Check output above for FOReports API call URLs and response shapes.")
    input("Press Enter to close browser...")
    browser.close()
