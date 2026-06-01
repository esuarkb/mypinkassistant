# run_report_sync.py
# One-shot test runner for REPORT_SYNC. Headed browser so you can watch.
# Usage: python run_report_sync.py

import os
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.report_sync import run_report_sync
from db import connect, is_postgres

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

PH = "%s" if is_postgres() else "?"

# Find the consultant_id for this InTouch username
conn = connect()
cur = conn.cursor()
cur.execute(f"SELECT id, email FROM consultants WHERE LOWER(intouch_username) = LOWER({PH})", (USERNAME,))
row = cur.fetchone()
conn.close()

if not row:
    print(f"No consultant found with intouch_username={USERNAME}")
    exit(1)

cid = row[0] if not hasattr(row, "keys") else row["id"]
email = row[1] if not hasattr(row, "keys") else row["email"]
print(f"Running report sync for: {email} (id={cid})")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    conn = connect()
    try:
        cur = conn.cursor()
        summary = run_report_sync(page, cur, consultant_id=cid, ph=PH)
        conn.commit()
    finally:
        conn.close()

    browser.close()

print(f"\nDone: {summary}")
