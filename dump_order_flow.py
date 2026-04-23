"""
Walks through the order placement flow on MyCustomers and dumps the HTML
at each stage so we can identify broken selectors when MK updates their site.

Uses your first customer and a known SKU — navigates away without saving.

Usage:
    python dump_order_flow.py <intouch_username> <intouch_password> [sku]

    sku defaults to 10203701 (Hydrogel Eye Patches) — replace with any SKU
    you know exists in your inventory if that one doesn't show results.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"
DEFAULT_SKU   = "10094148"  # Clear Proof Deep-Cleansing Charcoal Mask
SEARCH_CUSTOMER = "Angie Davis"


def dump(page, name: str) -> None:
    path = Path(f"dump_order_{name}.html")
    path.write_text(page.content(), encoding="utf-8")
    print(f"  Saved {path} ({path.stat().st_size:,} bytes)")


def login(page, username: str, password: str) -> None:
    print("Logging in...")
    from playwright_automation.login import login_intouch
    login_intouch(page, username, password)
    print("  Logged in.")


def main(username: str, password: str, sku: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page()

        login(page, username, password)

        # --- Step 1: Customer list ---
        print("\nStep 1: Customer list")
        page.wait_for_timeout(1000)
        dump(page, "1_customer_list")

        # Search for specific customer
        print(f"  Searching for {SEARCH_CUSTOMER!r}...")
        page.get_by_role("searchbox", name="Note Title").fill(SEARCH_CUSTOMER)
        page.wait_for_timeout(1500)

        # --- Step 2: Customer detail ---
        print("\nStep 2: Customer detail page")
        page.get_by_text(SEARCH_CUSTOMER).first.click()
        page.wait_for_timeout(1500)
        dump(page, "2_customer_detail")

        # --- Step 3: Click Add Order ---
        print("\nStep 3: Clicking Add Order")
        try:
            page.get_by_role("button", name="Add Order").wait_for(state="visible", timeout=8000)
            page.get_by_role("button", name="Add Order").click()
            page.wait_for_timeout(3000)
            print("  Clicked Add Order.")
        except PlaywrightTimeoutError:
            print("  ERROR: 'Add Order' button not found.")
        dump(page, "3_after_add_order")

        # --- Step 4: Select My Inventory ---
        print("\nStep 4: Selecting My Inventory")
        try:
            page.get_by_text("My Inventory").wait_for(state="visible", timeout=8000)
            page.get_by_text("My Inventory").click()
            page.wait_for_timeout(1200)
            print("  Selected My Inventory.")
        except PlaywrightTimeoutError:
            print("  ERROR: 'My Inventory' option not found.")
        dump(page, "4_my_inventory_selected")

        # --- Step 5: Search for SKU ---
        print(f"\nStep 5: Searching for SKU {sku}")
        try:
            search = page.get_by_role("searchbox", name="Note Title")
            search.wait_for(state="visible", timeout=8000)
            search.fill(sku)
            page.wait_for_timeout(2000)
            print(f"  Typed SKU {sku}.")
        except PlaywrightTimeoutError:
            print("  ERROR: SKU search box not found.")
        dump(page, "5_sku_search_results")

        # --- Step 6: Add to Bag ---
        print("\nStep 6: Clicking Add to Bag")
        try:
            page.get_by_role("button", name="Add to Bag").wait_for(state="visible", timeout=8000)
            page.get_by_role("button", name="Add to Bag").click()
            page.wait_for_timeout(500)
            print("  Clicked Add to Bag.")
        except PlaywrightTimeoutError:
            print(f"  ERROR: 'Add to Bag' not found. SKU {sku} may not be in this consultant's inventory.")
        dump(page, "6_after_add_to_bag")

        # --- Step 7: Save and Review screen ---
        print("\nStep 7: Clicking Save and Review")
        try:
            page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=8000)
            page.get_by_role("button", name="Save and Review").click()
            page.wait_for_load_state("networkidle", timeout=15000)
            print("  Clicked Save and Review.")
        except PlaywrightTimeoutError:
            print("  ERROR: 'Save and Review' button not found.")
        dump(page, "7_save_and_review")

        # --- Step 8: Change Delivery Status ---
        print("\nStep 8: Looking for Change Delivery Status button")
        try:
            page.get_by_role("button", name="Change Delivery Status Icon").wait_for(state="visible", timeout=8000)
            print("  'Change Delivery Status Icon' button found.")
            dump(page, "8_delivery_status")
        except PlaywrightTimeoutError:
            print("  ERROR: 'Change Delivery Status Icon' button not found.")
            dump(page, "8_delivery_status")

        # --- Navigate away WITHOUT confirming ---
        print("\nNavigating away without confirming order...")
        page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        try:
            page.get_by_role("button", name="Leave").wait_for(state="visible", timeout=3000)
            page.get_by_role("button", name="Leave").click()
            print("  Dismissed leave-page dialog.")
        except PlaywrightTimeoutError:
            pass

        print("\nAll done. Check dump_order_*.html files.")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python dump_order_flow.py <username> <password> [sku]")
        sys.exit(1)
    sku = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SKU
    main(sys.argv[1], sys.argv[2], sku)
