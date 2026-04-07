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
    "Street2":     "Apt 4B",
    "City":        "Dallas",
    "State":       "Texas",
    "Postal Code": "75201",
    "Tags":        "loyal customer, skincare",
    "Note Title":  "Test Note",
    "Note Body":   "This is a test note entry.",
}


def dump(page, name: str) -> None:
    path = Path(f"dump_nc_{name}.html")
    path.write_text(page.content(), encoding="utf-8")
    print(f"  Saved {path} ({path.stat().st_size:,} bytes)")


def login(page, username: str, password: str) -> None:
    print("Navigating to MyCustomers login...")
    from playwright_automation.login import login_intouch
    login_intouch(page, username, password)
    page.goto(CUSTOMERS_URL, wait_until="domcontentloaded")
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

        # --- Tags ---
        print("  Filling tags...")
        tags_field = page.locator('[id^="autocomplete-textarea"]')
        if tags_field.count():
            tags_field.fill(TEST_CUSTOMER["Tags"])
            print(f"  Tags filled: {TEST_CUSTOMER['Tags']}")
        else:
            print("  WARNING: Tags field not found")

        # --- Note ---
        print("  Adding note...")
        page.get_by_role("button", name="Add New Note").click()
        page.wait_for_timeout(1000)
        note_title = page.locator('[id^="noteTitle"]')
        note_body = page.locator('[id^="noteBody"]')
        if note_title.count() and note_body.count():
            note_title.fill(TEST_CUSTOMER["Note Title"])
            note_body.fill(TEST_CUSTOMER["Note Body"])
            page.get_by_role("button", name="Save & Exit").click()
            page.wait_for_timeout(1000)
            print("  Note saved.")
        else:
            print("  WARNING: Note fields not found")

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

            # --- Inspect all address dialog fields ---
            print("\n  Address dialog fields (before apt click):")
            dialog = page.get_by_role("dialog")
            for inp in dialog.locator("input, textarea").all():
                try:
                    iid = inp.get_attribute("id") or ""
                    ph = inp.get_attribute("placeholder") or ""
                    nm = inp.get_attribute("name") or ""
                    vis = inp.is_visible()
                    print(f"    visible={vis} id={iid!r} ph={ph!r} name={nm!r}")
                except:
                    pass

            # --- Click apt/suite expander ---
            print("\n  Looking for apt/suite expander button...")
            for btn in dialog.get_by_role("button").all():
                try:
                    txt = btn.inner_text().strip()
                    print(f"    BUTTON: {txt!r}")
                except:
                    pass
            try:
                apt_btn = dialog.get_by_role("button", name="Add Apartment")
                if not apt_btn.count():
                    apt_btn = dialog.locator("button", has_text="Apartment")
                if not apt_btn.count():
                    apt_btn = dialog.locator("button", has_text="Suite")
                apt_btn.first.click()
                page.wait_for_timeout(1000)
                print("  Clicked apt expander.")
                print("\n  Address dialog fields (after apt click):")
                for inp in dialog.locator("input, textarea").all():
                    try:
                        iid = inp.get_attribute("id") or ""
                        ph = inp.get_attribute("placeholder") or ""
                        nm = inp.get_attribute("name") or ""
                        vis = inp.is_visible()
                        print(f"    visible={vis} id={iid!r} ph={ph!r} name={nm!r}")
                    except:
                        pass
            except Exception as e:
                print(f"  Could not click apt expander: {e}")

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
