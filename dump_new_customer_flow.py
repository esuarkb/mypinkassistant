"""
Walks through the New Customer creation flow on MyCustomers and dumps
the HTML at each stage so we can verify selectors.

Uses a fake test customer — does NOT save (cancels before final submit).

Usage:
    python dump_new_customer_flow.py <intouch_username> <intouch_password>
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"

TEST_CUSTOMER = {
    "First Name":  "Test",
    "Last Name":   "Deleteme",
    "Email":       "test.deleteme@example.com",
    "Phone":       "5550001234",
    "Birthday":    "01/15",
    "Street":      "123 Main St",
    "City":        "Dallas",
    "State":       "Texas",
    "Postal Code": "75201",
}


def dump(page, name: str) -> None:
    path = Path(f"dump_nc_{name}.html")
    path.write_text(page.content(), encoding="utf-8")
    print(f"  Saved {path} ({path.stat().st_size:,} bytes)")


def login(page, username: str, password: str) -> None:
    print("Navigating to MyCustomers login...")
    page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Password").fill(password)
    page.wait_for_timeout(100)
    page.get_by_text("Log In").click()
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="New Customer").wait_for(timeout=45000)
    print("  Logged in, MyCustomers ready.")


def main(username: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        login(page, username, password)

        # --- Step 1: Customer list ---
        print("\nStep 1: Loading customer list...")
        page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
        try:
            page.get_by_role("button", name="New Customer").wait_for(timeout=20000)
            print("  'New Customer' button found.")
        except PlaywrightTimeoutError:
            print("  ERROR: 'New Customer' button not found after 20s.")
        dump(page, "1_customer_list")

        # --- Step 2: Click New Customer ---
        print("\nStep 2: Clicking New Customer...")
        page.get_by_role("button", name="New Customer").click()
        try:
            page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=15000)
            print("  New customer form is open.")
        except PlaywrightTimeoutError:
            print("  ERROR: New customer form did not open.")
        page.wait_for_timeout(1000)
        dump(page, "2_new_customer_form")

        # --- Step 3: Fill the form ---
        print("\nStep 3: Filling form fields...")
        page.get_by_role("textbox", name="First Name").fill(TEST_CUSTOMER["First Name"])
        page.wait_for_timeout(100)
        page.get_by_role("textbox", name="Last Name").fill(TEST_CUSTOMER["Last Name"])
        page.wait_for_timeout(100)
        page.get_by_role("textbox", name="Email Address (Optional)").fill(TEST_CUSTOMER["Email"])
        page.wait_for_timeout(100)
        page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(TEST_CUSTOMER["Phone"])
        page.wait_for_timeout(100)
        page.get_by_role("textbox", name="Birthday (Optional)").press_sequentially("01151990", delay=50)
        page.wait_for_timeout(500)
        dump(page, "3_form_filled")

        # --- Step 4: Save ---
        print("\nStep 4: Clicking Save New Customer...")
        page.get_by_role("button", name="Save New Customer").click()
        try:
            page.get_by_role("button", name="Save New Customer").wait_for(state="detached", timeout=15000)
            print("  Save completed — form closed.")
        except PlaywrightTimeoutError:
            print("  WARNING: Form may not have closed.")
        page.wait_for_timeout(2000)
        dump(page, "4_after_save")

        # --- Step 5: Find Add New Address button ---
        print("\nStep 5: Looking for Add New Address button...")
        try:
            add_btn = page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address")
            add_btn.wait_for(state="visible", timeout=10000)
            print("  'Add New Address' button found inside c-cmt-no-info-available.")
        except PlaywrightTimeoutError:
            print("  Not found via c-cmt-no-info-available — trying broader search...")
            try:
                add_btn = page.get_by_role("button", name="Add New Address")
                add_btn.wait_for(state="visible", timeout=5000)
                print("  Found via broader get_by_role.")
            except PlaywrightTimeoutError:
                print("  ERROR: 'Add New Address' button not found at all.")
                add_btn = None
        dump(page, "5_customer_detail")

        # --- Step 6: Click Add New Address ---
        if add_btn:
            print("\nStep 6: Clicking Add New Address...")
            for attempt in range(1, 4):
                add_btn.click()
                page.wait_for_timeout(500)
                try:
                    page.locator('[id^="AddressFirstName-"]').wait_for(state="visible", timeout=1500)
                    print(f"  Address dialog opened on attempt {attempt}.")
                    break
                except PlaywrightTimeoutError:
                    print(f"  Attempt {attempt}: dialog not open yet...")
            else:
                print("  WARNING: Address dialog may not have opened.")

            page.wait_for_timeout(500)
            dump(page, "6_address_dialog")

            # --- Step 7: Check state dropdown ---
            print("\nStep 7: Checking state dropdown...")
            try:
                dialog = page.get_by_role("dialog")
                state_btn = dialog.get_by_role("button", name="Select an option")
                state_btn.wait_for(state="visible", timeout=5000)
                print("  State dropdown button found inside dialog.")
                state_btn.click()
                page.wait_for_timeout(700)
                dump(page, "7_state_dropdown_open")
            except PlaywrightTimeoutError:
                print("  WARNING: State dropdown not found inside dialog.")

        # --- Step 8: Close address dialog and open Subscriptions edit ---
        print("\nStep 8: Closing address dialog and opening Subscriptions edit...")
        try:
            dialog = page.get_by_role("dialog")
            cancel_btn = dialog.get_by_role("button", name="Cancel")
            cancel_btn.wait_for(state="visible", timeout=3000)
            cancel_btn.click()
            page.wait_for_timeout(1000)
            print("  Address dialog closed via Cancel button.")
        except PlaywrightTimeoutError:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
                print("  Address dialog closed via Escape.")
            except Exception:
                pass

        try:
            sub_edit_btn = page.locator("c-cmt-my-customer-details-subscriptions").get_by_role("button")
            sub_edit_btn.wait_for(state="visible", timeout=10000)
            print("  Subscriptions edit button found.")
            sub_edit_btn.click()
            page.wait_for_timeout(1500)
            dump(page, "8_subscriptions_dialog")
            print("  Subscriptions dialog dumped.")
        except PlaywrightTimeoutError:
            print("  ERROR: Subscriptions edit button not found.")

        # --- Cleanup: Cancel without saving ---
        print("\nCleaning up — looking for Cancel or close button...")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass

        print("  Please manually delete 'Test Deleteme' from MyCustomers.")

        print("\nAll done. Check dump_nc_*.html files.")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python dump_new_customer_flow.py <username> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
