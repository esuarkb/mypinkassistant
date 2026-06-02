# explore_reports.py
# One-shot explorer: logs into InTouch, navigates to the reports hub,
# captures all network calls and page text to identify available reports.
# Usage: python explore_reports.py

import os, json, re, time
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

REPORTS_URL = "https://mk.marykayintouch.com/s/reports"

captured_requests = []

def handle_response(response):
    url = response.url
    # Capture FOReports API calls and Aura/Salesforce calls
    if any(k in url for k in ("FOReports", "aura", "apexremote", "graphql", "report", "seminar", "rise")):
        try:
            body = response.text()
            captured_requests.append({
                "url": url,
                "status": response.status,
                "body_preview": body[:2000],
            })
        except Exception:
            captured_requests.append({"url": url, "status": response.status, "body_preview": "(unreadable)"})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()
    page.on("response", handle_response)

    # --- Login (replicating login.py logic) ---
    print("Navigating to login...")
    page.goto("https://apps.marykayintouch.com/customer-list", wait_until="domcontentloaded")
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    page.get_by_role("textbox", name="Consultant Number").fill(USERNAME)
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Password").fill(PASSWORD)
    page.wait_for_timeout(100)
    page.get_by_text("Log In").click()
    page.wait_for_timeout(2000)

    # Handle "Finish Logging In" if present
    try:
        btn = page.get_by_role("button", name="Finish Logging In")
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # Make sure we're logged in
    try:
        page.get_by_role("button", name="New Customer").wait_for(timeout=30000)
        print("Logged in successfully.")
    except Exception:
        print("WARNING: Login may not have completed — proceeding anyway.")

    # --- Navigate to reports hub ---
    print(f"\nNavigating to {REPORTS_URL} ...")
    page.goto(REPORTS_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)  # let Salesforce/LWC fully render

    # Grab all visible text (report names, categories, links)
    page_text = page.inner_text("body")

    # Also grab all links/anchors on the page
    links = page.eval_on_selector_all("a[href]", "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))")

    print("\n--- PAGE TEXT (first 5000 chars) ---")
    print(page_text[:5000])

    print("\n--- ALL LINKS ON PAGE ---")
    for lnk in links:
        if lnk["text"] or lnk["href"]:
            print(f"  [{lnk['text'][:60]}] -> {lnk['href'][:120]}")

    # Look specifically for Rise & Radiate and Seminar
    print("\n--- RISE & RADIATE MENTIONS ---")
    for line in page_text.splitlines():
        if re.search(r'rise|radiate', line, re.IGNORECASE):
            print(" ", line.strip())

    print("\n--- SEMINAR MENTIONS ---")
    for line in page_text.splitlines():
        if re.search(r'seminar', line, re.IGNORECASE):
            print(" ", line.strip())

    # Try clicking on any Rise & Radiate report link
    rise_links = [l for l in links if re.search(r'rise|radiate', l.get("text",""), re.IGNORECASE)]
    if rise_links:
        print(f"\nFound {len(rise_links)} Rise/Radiate link(s), clicking first one...")
        page.goto(rise_links[0]["href"], wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        rise_text = page.inner_text("body")
        print("--- Rise & Radiate Report Page Text ---")
        print(rise_text[:4000])
    else:
        print("\nNo Rise & Radiate links found directly on page — may need to navigate sub-sections.")

    # Try clicking on any Seminar report link
    sem_links = [l for l in links if re.search(r'seminar', l.get("text",""), re.IGNORECASE)]
    if sem_links:
        print(f"\nFound {len(sem_links)} Seminar link(s), clicking first one...")
        page.goto(sem_links[0]["href"], wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        sem_text = page.inner_text("body")
        print("--- Seminar Report Page Text ---")
        print(sem_text[:4000])

    # Dump captured network calls
    print(f"\n--- CAPTURED NETWORK CALLS ({len(captured_requests)}) ---")
    for req in captured_requests[:30]:
        print(f"\nURL: {req['url'][:120]}")
        print(f"Status: {req['status']}")
        print(f"Body: {req['body_preview'][:300]}")

    print("\nLeaving browser open for manual inspection. Press Enter to close.")
    input()
    browser.close()
