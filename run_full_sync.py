# run_full_sync.py
# One-shot test runner for the nightly FULL_SYNC job (headed browser).
# Runs: customers + orders + inventory + report sync — same as the overnight job.
# Usage: python run_full_sync.py [email]
# Defaults to briankrause@gmail.com

import sys, os
from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres
from auth_core import decrypt_intouch_password
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.customer_api_import import fetch_customer_list
from playwright_automation.order_history_import import fetch_order_history
from playwright_automation.inventory_import import import_inventory_orders
from customer_api_import_store import import_customers_from_api
from order_history_import_store import import_order_history
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

cid      = row[0] if not hasattr(row, "keys") else row["id"]
username = row[1] if not hasattr(row, "keys") else row["intouch_username"]
enc      = row[2] if not hasattr(row, "keys") else row["intouch_password_enc"]
password = decrypt_intouch_password(enc)

print(f"Running FULL_SYNC for: {email} (id={cid}, intouch={username})")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    print("\nLogging in...")
    login_intouch(page, username, password)
    print("Logged in.")

    # Customers
    print("\n--- Customers ---")
    raw_customers = fetch_customer_list(page)
    print(f"Fetched {len(raw_customers)} customers")
    conn = connect()
    try:
        cur = conn.cursor()
        summary = import_customers_from_api(cur, consultant_id=cid, raw_customers=raw_customers)
        conn.commit()
    finally:
        conn.close()
    print(f"Customers: {summary}")

    # Orders
    print("\n--- Orders ---")
    raw_orders = fetch_order_history(page)
    print(f"Fetched {len(raw_orders)} orders")
    conn = connect()
    try:
        cur = conn.cursor()
        ord_summary = import_order_history(cur, consultant_id=cid, raw_orders=raw_orders)
        conn.commit()
    finally:
        conn.close()
    print(f"Orders: {ord_summary}")

    # Inventory
    print("\n--- Inventory ---")
    try:
        import_inventory_orders(
            page,
            consultant_id=cid,
            username=username,
            password=password,
            date_range="days90",
            seed_only=False,
        )
        print("Inventory import complete.")
    except Exception as e:
        print(f"Inventory import failed (non-fatal): {e}")

    # Reports
    print("\n--- Report Sync ---")
    try:
        conn = connect()
        try:
            cur = conn.cursor()
            rs = run_report_sync(page, cur, cid, ph=PH)
            conn.commit()
        finally:
            conn.close()
        print(f"Reports: {rs}")
    except Exception as e:
        print(f"Report sync failed (non-fatal): {e}")

    browser.close()

print("\nFULL_SYNC complete.")
