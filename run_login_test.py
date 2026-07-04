"""
Logs in as a given consultant headed and pauses so you can inspect any popups.
Dumps all visible button/dialog text after login.

Usage:
    python run_login_test.py
"""
import os
from dotenv import load_dotenv
load_dotenv()
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in as INTOUCH_USER from .env...")
    try:
        login_intouch(page, USERNAME, PASSWORD)
        print("Login succeeded — no popup blocked it.")
    except Exception as e:
        print(f"Login failed: {e}")

    # Dump visible buttons and dialog text
    print("\n--- Visible buttons ---")
    for b in page.get_by_role("button").all():
        if b.is_visible():
            txt = b.inner_text().strip()
            if txt:
                print(f"  [{txt}]")

    print("\n--- Visible dialogs/modals ---")
    for d in page.get_by_role("dialog").all():
        if d.is_visible():
            print(f"  {d.inner_text()[:300]}")

    print("\nCurrent URL:", page.url)
    print("\nPausing — inspect the browser then close it.")
    page.pause()
    browser.close()
