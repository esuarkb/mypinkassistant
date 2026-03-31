"""
Runs the inventory import for a single consultant locally.
Pulls latest cosmetic orders from InTouch and updates local inventory.

Usage:
    python run_inventory_import.py <intouch_username> <intouch_password> [consultant_id]

    consultant_id defaults to 2 (Andrea)
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.inventory_import import import_inventory_orders
from inventory_import_store import ensure_import_table

ensure_import_table()

username = sys.argv[1] if len(sys.argv) > 1 else None
password = sys.argv[2] if len(sys.argv) > 2 else None
consultant_id = int(sys.argv[3]) if len(sys.argv) > 3 else 2

if not username or not password:
    print("Usage: python run_inventory_import.py <username> <password> [consultant_id]")
    sys.exit(1)

print(f"\nRunning inventory import for consultant_id={consultant_id}...")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/Chicago",
    )
    page = context.new_page()

    print("Logging in...")
    login_intouch(page, username, password)
    print("Logged in.")

    result = import_inventory_orders(
        page,
        consultant_id=consultant_id,
        username=username,
        password=password,
        date_range="days90",
        seed_only=False,
    )

    context.close()
    browser.close()

imported = result.get("imported", [])
skipped = result.get("skipped", [])
sku_totals = result.get("sku_totals", {})

print(f"\n--- Results ---")
print(f"Orders imported: {len(imported)}")
print(f"Orders skipped:  {len(skipped)}")
print(f"SKUs updated:    {len(sku_totals)}")

if sku_totals:
    print(f"\nSKU breakdown:")
    for sku, qty in sorted(sku_totals.items()):
        print(f"  {sku}: +{qty}")

if skipped:
    print(f"\nSkipped orders: {skipped}")
