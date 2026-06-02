# read_rise_rules.py — navigate to Rise+Radiate IBC page and read the contest rules
import os
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    # Login
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
    print("Logged in.")

    # Navigate to Rise + Radiate IBC page
    print("Navigating to Rise + Radiate IBC Selling Challenge...")
    page.goto("https://mk.marykayintouch.com/s/reports/rise-radiate-ibc-selling-challenge",
              wait_until="domcontentloaded")
    page.wait_for_timeout(8000)

    # Print initial page text
    text = page.inner_text("body")
    print("\n--- INITIAL PAGE TEXT ---")
    print(text[:2000])

    # Look for a Rules button/link
    print("\n--- LOOKING FOR RULES LINK ---")
    links = page.eval_on_selector_all("a, button", "els => els.map(e => ({tag: e.tagName, text: e.innerText.trim(), href: e.href || ''}))")
    for l in links:
        if l["text"].strip():
            print(f"  [{l['tag']}] '{l['text'][:60]}' -> {l['href'][:80]}")

    # Try clicking Rules
    try:
        rules_btn = page.get_by_text("Rules", exact=False)
        if rules_btn.count() > 0:
            print(f"\nFound {rules_btn.count()} 'Rules' element(s), clicking first...")
            rules_btn.first.click()
            page.wait_for_timeout(4000)
            rules_text = page.inner_text("body")
            print("\n--- PAGE TEXT AFTER CLICKING RULES ---")
            print(rules_text[:8000])
        else:
            print("No 'Rules' element found on page.")
    except Exception as e:
        print(f"Error clicking Rules: {e}")

    # Also check for any iframe that might contain the report
    iframes = page.frames
    print(f"\n--- FRAMES ON PAGE ({len(iframes)}) ---")
    for i, frame in enumerate(iframes):
        try:
            ft = frame.inner_text("body")
            if ft.strip() and len(ft) > 50:
                print(f"\nFrame {i} ({frame.url[:80]}):")
                print(ft[:3000])
                # Look for Rules in this frame
                try:
                    rb = frame.get_by_text("Rules", exact=False)
                    if rb.count() > 0:
                        print(f"  -> Found Rules in frame {i}, clicking...")
                        rb.first.click()
                        page.wait_for_timeout(4000)
                        print(frame.inner_text("body")[:6000])
                except Exception:
                    pass
        except Exception:
            pass

    browser.close()
