# explore_rise_seminar2.py
# Deeper dive: captures FOReports API calls + full page text for Rise+Radiate and Seminar.
# Output saved to explore_output.txt so nothing is truncated.
# Usage: python explore_rise_seminar2.py

import os, json, re, sys
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

TARGETS = [
    ("Rise + Radiate IBC Selling Challenge",     "https://mk.marykayintouch.com/s/reports/rise-radiate-ibc-selling-challenge"),
    ("Rise + Radiate ISD Unit Growth Challenge", "https://mk.marykayintouch.com/s/reports/riseandradiateisdchallenge"),
    ("Seminar Recognition",                      "https://mk.marykayintouch.com/s/reports/seminarrecognition"),
    ("Registration List",                        "https://mk.marykayintouch.com/s/reports/registration-list"),
]

out = open("explore_output.txt", "w")

def log(s=""):
    print(s)
    out.write(s + "\n")
    out.flush()

all_api_calls = []

def handle_response(response):
    url = response.url
    # Capture FOReports REST API (the actual report data) and Aura calls
    if "FOReports" in url or "applications.marykayintouch.com" in url:
        try:
            body = response.text()
            all_api_calls.append({"url": url, "status": response.status, "body": body, "page": "?"})
        except Exception:
            all_api_calls.append({"url": url, "status": response.status, "body": "(unreadable)", "page": "?"})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=30)
    page = browser.new_page()
    page.on("response", handle_response)

    # Login
    log("Logging in...")
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
        log("Logged in OK.")
    except Exception:
        log("WARNING: login may not be complete.")

    for label, url in TARGETS:
        log(f"\n{'='*70}")
        log(f"REPORT: {label}")
        log(f"URL: {url}")

        # Tag new calls with this page label
        snapshot_before = len(all_api_calls)
        for c in all_api_calls:
            if c["page"] == "?":
                c["page"] = "previous"

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(10000)  # longer wait for LWC render

        # Tag calls from this page
        for c in all_api_calls:
            if c["page"] == "?":
                c["page"] = label

        text = page.inner_text("body")
        log(f"\n--- FULL PAGE TEXT ---")
        log(text)

        new_calls = [c for c in all_api_calls if c["page"] == label]
        log(f"\n--- FOReports API CALLS ({len(new_calls)}) ---")
        for call in new_calls:
            log(f"\n  URL: {call['url']}")
            log(f"  Status: {call['status']}")
            try:
                parsed = json.loads(call["body"])
                log(f"  Body (JSON):\n{json.dumps(parsed, indent=2)[:3000]}")
            except Exception:
                log(f"  Body (raw):\n{call['body'][:1000]}")

    log("\n\nDone. Output saved to explore_output.txt")
    out.close()
    browser.close()
