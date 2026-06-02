# run_pcp_sync.py
# One-shot test runner for PCP_SYNC + report sync (headed browser).
# Usage: python run_pcp_sync.py [email]
# Defaults to briankrause@gmail.com

import sys, os
from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres
from auth_core import decrypt_intouch_password
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from scrape_pcp import scrape_enrolled, save_to_db, current_quarter
from playwright_automation.report_sync import run_report_sync

email = sys.argv[1] if len(sys.argv) > 1 else "briankrause@gmail.com"
PH = "%s" if is_postgres() else "?"

conn = connect()
cur = conn.cursor()
cur.execute(
    f"SELECT id, intouch_username, intouch_password_enc FROM consultants WHERE LOWER(email) = LOWER({PH})",
    (email,),
)
row = cur.fetchone()
conn.close()

if not row:
    print(f"No consultant found with email={email}")
    sys.exit(1)

cid   = row[0] if not hasattr(row, "keys") else row["id"]
uname = row[1] if not hasattr(row, "keys") else row["intouch_username"]
enc   = row[2] if not hasattr(row, "keys") else row["intouch_password_enc"]

password = decrypt_intouch_password(enc)
print(f"Running PCP + report sync for: {email} (id={cid}, intouch={uname})")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, uname, password)
    print("Logged in.")

    # PCP sync
    print("\n--- PCP Sync ---")
    try:
        enrolled = scrape_enrolled(page, uname, password, skip_login=True)
        if enrolled:
            conn = connect()
            try:
                cur = conn.cursor()
                save_to_db(cur, enrolled, cid, current_quarter())
                conn.commit()
            finally:
                conn.close()
            print(f"PCP: {len(enrolled)} enrolled customers saved.")
        else:
            print("PCP: no enrolled customers found.")
    except RuntimeError as e:
        print(f"PCP: skipped — {e}")
    except Exception as e:
        print(f"PCP: error — {e}")

    # Report sync
    print("\n--- Report Sync ---")
    conn = connect()
    try:
        cur = conn.cursor()
        summary = run_report_sync(page, cur, cid, ph=PH)
        conn.commit()
    finally:
        conn.close()
    print(f"Reports: {summary}")

    browser.close()

print("\nDone.")
