"""
Walks through a CDS order flow on MyCustomers and dumps HTML at each stage
so we can see what InTouch renders when a SKU is not CDS-eligible.

Usage:
    python dump_cds_order_flow.py <intouch_username> <intouch_password> [sku]

    sku defaults to 10208549 (TimeWise Repair Foaming Cleanser)
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"
DEFAULT_SKU   = "10208549"


def dump(page, name: str) -> None:
    path = Path(f"dump_cds_{name}.html")
    path.write_text(page.content(), encoding="utf-8")
    print(f"  Saved {path} ({path.stat().st_size:,} bytes)")


def main(username: str, password: str, sku: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page()

        # --- Login ---
        print("Logging in...")
        from playwright_automation.login import login_intouch
        login_intouch(page, username, password)
        print("  Logged in.")

        # --- Step 1: Find first customer with an address ---
        print("\nStep 1: Customer list")
        page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="New Customer").wait_for(timeout=20000)
        dump(page, "1_customer_list")

        # Click the first "New Order" button directly — takes us to that customer's order page
        new_order_btns = page.get_by_role("button", name="New Order").all()
        if not new_order_btns:
            print("  ERROR: No 'New Order' buttons found.")
            browser.close()
            return

        print(f"  Found {len(new_order_btns)} customers, using first.")
        new_order_btns[0].click()
        page.wait_for_timeout(3000)
        dump(page, "2_customer_detail")

        dump(page, "3_after_new_order")

        # --- Step 3: Select Customer Delivery (CDS) ---
        print("\nStep 3: Selecting Customer Delivery")
        try:
            page.get_by_text("Customer Delivery").wait_for(state="visible", timeout=8000)
            page.get_by_text("Customer Delivery").click()
            page.wait_for_timeout(1200)
            print("  Selected Customer Delivery.")
        except PlaywrightTimeoutError:
            print("  ERROR: 'Customer Delivery' option not found.")
        dump(page, "4_cds_selected")

        # --- Step 4: Search for SKU ---
        print(f"\nStep 4: Searching for SKU {sku}")
        try:
            search = page.get_by_role("searchbox", name="Note Title")
            search.wait_for(state="visible", timeout=8000)
            search.fill(sku)
            page.wait_for_timeout(2000)
            print(f"  Typed SKU {sku}.")
        except PlaywrightTimeoutError:
            print("  ERROR: SKU search box not found.")
        dump(page, "5_sku_search_results")

        # --- Step 5: Check Add to Bag state ---
        print("\nStep 5: Checking Add to Bag button state")
        try:
            btn = page.locator(f'button[data-sku="{sku}"]')
            btn.wait_for(state="attached", timeout=5000)
            is_disabled = btn.is_disabled()
            print(f"  Add to Bag button disabled={is_disabled}")
            # Dump full page HTML so we can see any no-CDS labels
            dump(page, "6_add_to_bag_state")
        except PlaywrightTimeoutError:
            print("  ERROR: Add to Bag button not found at all.")
            dump(page, "6_add_to_bag_state")

        # --- Navigate away WITHOUT saving ---
        print("\nNavigating away without saving...")
        page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        try:
            page.get_by_role("button", name="Leave").wait_for(state="visible", timeout=3000)
            page.get_by_role("button", name="Leave").click()
            print("  Dismissed leave-page dialog.")
        except PlaywrightTimeoutError:
            pass

        print("\nDone. Check dump_cds_*.html files.")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python dump_cds_order_flow.py <username> <password> [sku]")
        sys.exit(1)
    sku = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SKU
    main(sys.argv[1], sys.argv[2], sku)
