"""
Quick sanity check that all critical InTouch selectors still work.
No customers are created. No orders are placed. No cleanup needed.

If MK updates their site and a selector breaks, this script will tell you
exactly which one failed so you can fix it in one line.

Usage:
    python verify_selectors.py <intouch_username> <intouch_password>

Address dialog selectors (only reachable post-save, verified manually):
    - page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address")
    - page.locator('[id^="AddressFirstName-"]')
    - page.locator('[id^="AddressLastName-"]')
    - page.locator('[id^="Street-"]')
    - page.locator('[id^="City-"]')
    - page.locator('[id^="PostalCode-"]')
    - page.get_by_role("dialog").get_by_role("button", name="Select an option")
    - page.get_by_role("dialog").get_by_role("button", name="Add New Address")
"""
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"
TIMEOUT       = 8000

passed = []
failed = []


def check(label: str, fn):
    try:
        fn()
        passed.append(label)
        print(f"  ✓  {label}")
    except Exception as e:
        failed.append(label)
        print(f"  ✗  {label}")
        print(f"       {e}")


def login(page, username: str, password: str) -> None:
    page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_text("Log In").click()
    page.get_by_role("button", name="New Customer").wait_for(timeout=45000)


def verify_new_customer_form(page) -> None:
    print("\n── New Customer Form ───────────────────────────────")

    check("'New Customer' button",
        lambda: page.get_by_role("button", name="New Customer").wait_for(timeout=TIMEOUT))

    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=15000)

    check("First Name field",
        lambda: page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=TIMEOUT))

    check("Last Name field",
        lambda: page.get_by_role("textbox", name="Last Name").wait_for(state="visible", timeout=TIMEOUT))

    check("Email field",
        lambda: page.get_by_role("textbox", name="Email Address (Optional)").wait_for(state="visible", timeout=TIMEOUT))

    check("Phone field",
        lambda: page.get_by_role("textbox", name="Mobile Phone Number (Optional)").wait_for(state="visible", timeout=TIMEOUT))

    check("Birthday field",
        lambda: page.get_by_role("textbox", name="Birthday (Optional)").wait_for(state="visible", timeout=TIMEOUT))

    check("Save New Customer button",
        lambda: page.get_by_role("button", name="Save New Customer").wait_for(state="visible", timeout=TIMEOUT))

    # Cancel without saving — navigate away cleanly
    page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
    page.get_by_role("button", name="New Customer").wait_for(timeout=15000)


def verify_order_flow(page) -> None:
    print("\n── Order Flow ──────────────────────────────────────")

    check("Customer search box",
        lambda: page.get_by_role("searchbox", name="Note Title").wait_for(state="visible", timeout=TIMEOUT))

    # Find first customer in list
    page.wait_for_timeout(1000)
    cards = page.locator(".customer-row:not(.customer-row-header)").all()
    if not cards:
        print("  ⚠  No customers in list — skipping customer detail checks.")
        return

    cards[0].click()
    page.wait_for_timeout(1500)

    check("'Add Order' button on customer detail",
        lambda: page.get_by_role("button", name="Add Order").wait_for(state="visible", timeout=TIMEOUT))

    page.get_by_role("button", name="Add Order").click()
    page.wait_for_timeout(3000)

    check("'My Inventory' option",
        lambda: page.get_by_text("My Inventory").wait_for(state="visible", timeout=TIMEOUT))

    page.get_by_text("My Inventory").click()
    page.wait_for_timeout(1200)

    check("SKU search box",
        lambda: page.get_by_role("searchbox", name="Note Title").wait_for(state="visible", timeout=TIMEOUT))

    # Search a known SKU to verify Add to Bag
    page.get_by_role("searchbox", name="Note Title").fill("10203701")
    try:
        page.locator("text=10203701").first.wait_for(timeout=8000)
        check("SKU result appears",
            lambda: page.locator("text=10203701").first.wait_for(timeout=TIMEOUT))
        check("'Add to Bag' button",
            lambda: page.get_by_role("button", name="Add to Bag").wait_for(state="visible", timeout=TIMEOUT))
    except PlaywrightTimeoutError:
        print("  ⚠  SKU 10203701 not in this consultant's inventory — Add to Bag not verified.")
        print("     Update the SKU in verify_selectors.py to one that exists in your inventory.")

    # Navigate away without saving — dismiss leave dialog if it appears
    page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    try:
        page.get_by_role("button", name="Leave").wait_for(state="visible", timeout=2000)
        page.get_by_role("button", name="Leave").click()
    except PlaywrightTimeoutError:
        pass

    # Save and Review / Change Delivery Status / Yes Confirm only appear
    # mid-order — check manually if those are suspected broken.
    print("  ℹ  'Save and Review', 'Change Delivery Status', 'Yes, Confirm'")
    print("     only appear mid-order — verify manually if suspected broken.")


def main(username: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page()

        print("Logging in...")
        login(page, username, password)
        print("Logged in.")

        verify_new_customer_form(page)
        verify_order_flow(page)

        browser.close()

    total = len(passed) + len(failed)
    print(f"\n══ Results: {len(passed)}/{total} passed ══════════════════════════")
    if failed:
        print("FAILED:")
        for f in failed:
            print(f"  ✗  {f}")
        print("\n⚠  One or more selectors broken — InTouch may have updated.")
    else:
        print("All selectors OK — no changes detected.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python verify_selectors.py <username> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
