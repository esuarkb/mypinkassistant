# run_order_detail_sync.py
# One-shot test runner for order detail sync. Headed browser so you can watch.
# Fetches order history + CSRF token, then hits the detail API for every
# non-archived order and updates quantities in the local DB.
# Usage: python run_order_detail_sync.py

import os
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.order_history_import import fetch_order_history
from playwright_automation.order_detail_sync import fetch_order_details
from order_history_import_store import import_order_history, update_order_item_quantities
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
print(f"Running order detail sync for: {email} (id={cid})")

# Snapshot before
conn = connect()
cur = conn.cursor()
cur.execute(f"SELECT COUNT(*) FROM order_items WHERE quantity > 1")
qty_before = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id = {PH})", (cid,))
items_before = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM orders WHERE consultant_id = {PH}", (cid,))
orders_before = cur.fetchone()[0]
conn.close()

print(f"\nBefore: {orders_before} orders, {items_before} order_items, {qty_before} items with qty > 1")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/Chicago",
    )
    page = context.new_page()

    print("\nLogging in...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    print("\nFetching order history + CSRF token...")
    raw_orders, csrf_token = fetch_order_history(page)
    print(f"Got {len(raw_orders)} orders, csrf_token present: {bool(csrf_token)}")

    if not csrf_token:
        print("ERROR: no csrf_token captured — cannot proceed with detail sync")
        browser.close()
        exit(1)

    # Import orders first (so they exist in DB for quantity updates)
    print("\nImporting order history into DB...")
    conn = connect()
    try:
        cur = conn.cursor()
        summary = import_order_history(cur, consultant_id=cid, raw_orders=raw_orders)
        conn.commit()
    finally:
        conn.close()
    print(f"Import summary: {summary}")

    # Build list of non-archived order IDs with dates
    non_archived = [
        (o["Id"], (o.get("OrderedDate_f__c") or o.get("OrderedDate") or "")[:10])
        for o in raw_orders if o.get("Id") and not o.get("IsArchived_cb__c")
    ]
    print(f"\nFetching detail for {len(non_archived)} non-archived orders...")

    detail_map = fetch_order_details(page, non_archived, csrf_token)
    print(f"\nDetail API returned data for {len(detail_map)} orders")

    if detail_map:
        print("Updating order item quantities in DB...")
        conn = connect()
        try:
            cur = conn.cursor()
            result = update_order_item_quantities(cur, consultant_id=cid, order_details_map=detail_map)
            conn.commit()
        finally:
            conn.close()
        print(f"Update result: {result}")

    browser.close()

# Snapshot after
conn = connect()
cur = conn.cursor()
cur.execute(f"SELECT COUNT(*) FROM order_items WHERE quantity > 1")
qty_after = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id = {PH})", (cid,))
items_after = cur.fetchone()[0]
conn.close()

print(f"\nAfter:  {orders_before} orders, {items_after} order_items, {qty_after} items with qty > 1")
print(f"\nDelta: items with qty > 1: {qty_before} → {qty_after} (+{qty_after - qty_before})")
