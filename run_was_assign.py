# run_was_assign.py
# One-shot test runner for the WAS auto-assign step. Headed browser.
# Usage: python run_was_assign.py [--dry-run] [--headless]
#   --dry-run  logs in and reads the sheet but NEVER clicks Add or fills a
#              field — prints exactly what a real run would have assigned.
#
# Notes:
#  - First run for a consultant only INITIALIZES was_assign_start_date (today)
#    and assigns nothing — that's the designed no-backfill line, not a bug.
#  - Uses INTOUCH_USER/INTOUCH_PASS from .env, same as run_report_sync.py.

import os
import sys
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.was_assign import run_was_assign
from db import connect, is_postgres

DRY_RUN = "--dry-run" in sys.argv
HEADLESS = "--headless" in sys.argv

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

PH = "%s" if is_postgres() else "?"

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
print(f"Running WAS assign for: {email} (id={cid})  dry_run={DRY_RUN}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=HEADLESS, slow_mo=50)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    conn = connect()
    try:
        cur = conn.cursor()
        summary = run_was_assign(page, cur, consultant_id=cid, ph=PH, dry_run=DRY_RUN)
        conn.commit()
    finally:
        conn.close()

    browser.close()

print(f"\nDone: {summary}")
if summary.get("planned"):
    print("\nPlanned row assignments:")
    for pl in summary["planned"]:
        nrst = f"  NRST ${pl['nrst']:.2f}" if pl["nrst"] is not None else ""
        scs = f"  SCS {pl['scs']}" if pl["scs"] else ""
        print(f"  {pl['date']}  {pl['hostess']:<28} ${pl['sales']:.2f}  → {pl['type']}{scs}{nrst}")
