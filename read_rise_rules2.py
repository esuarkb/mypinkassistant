# read_rise_rules2.py — go directly to FOReports URL and click Rules
import os
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

FOREPORTS_URL = "https://applications.marykayintouch.com/FOReports/Report?id=RiseAndRadiateIBCChallenge&noHeader=true"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    # Login via the standard MyCustomers path to get session cookies
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
    page.get_by_role("button", name="New Customer").wait_for(timeout=30000)
    print("Logged in. Navigating to FOReports directly...")

    # Navigate directly to the FOReports Rise & Radiate page
    page.goto(FOREPORTS_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    text = page.inner_text("body")
    print("\n--- PAGE TEXT ---")
    print(text[:3000])

    # Find all clickable elements
    print("\n--- ALL BUTTONS AND LINKS ---")
    els = page.eval_on_selector_all("a, button", "els => els.map(e => ({tag: e.tagName, text: e.innerText.trim(), href: e.href || '', visible: e.offsetParent !== null}))")
    for e in els:
        if e["text"].strip():
            print(f"  [{e['tag']}] '{e['text'][:80]}' -> {e['href'][:80]}")

    # Try to find and click Rules
    for label in ["Rules", "View Rules", "Contest Rules", "Challenge Rules"]:
        try:
            el = page.get_by_text(label, exact=False)
            if el.count() > 0:
                print(f"\nFound '{label}' ({el.count()} match(es)), clicking...")
                el.first.click()
                page.wait_for_timeout(4000)
                after_text = page.inner_text("body")
                print(f"\n--- PAGE TEXT AFTER CLICKING '{label}' ---")
                print(after_text[:8000])
                break
        except Exception as ex:
            print(f"  Error clicking '{label}': {ex}")

    # Also look for any modal/dialog/popup that may have appeared
    try:
        modal = page.locator(".modal, .modal-body, .rules, dialog, [role='dialog']")
        if modal.count() > 0:
            print(f"\n--- MODAL/DIALOG TEXT ---")
            print(modal.first.inner_text()[:5000])
    except Exception:
        pass

    print("\nDone. Closing browser.")
    browser.close()
