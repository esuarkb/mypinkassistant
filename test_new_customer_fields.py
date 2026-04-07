"""
Inspection script: creates a Test Customer in MyCustomers and prints
all field IDs/names found in the address dialog after saving.
Also tests filling tags and note fields on the new customer form.
"""
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from auth_core import get_consultant_intouch_creds
from playwright_automation.login import login_intouch

CONSULTANT_ID = 1

customer = {
    "First Name": "Test",
    "Last Name": "Customer",
    "Email": "",
    "Phone": "2565550001",
    "Birthday": "",
    "Street": "123 Main St",
    "Street2": "Apt 4B",
    "City": "Arab",
    "State": "Alabama",
    "Postal Code": "35976",
    "Tags": "test, inspection",
    "Note Title": "Test Note",
    "Note Body": "This is a test note for field inspection.",
}

username, password = get_consultant_intouch_creds(CONSULTANT_ID)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    login_intouch(page, username, password)
    page.goto("https://apps.marykayintouch.com/customer-list")
    page.get_by_role("button", name="New Customer").wait_for(timeout=30000)
    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(1500)

    # Fill basic fields
    page.get_by_role("textbox", name="First Name").fill(customer["First Name"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Last Name").fill(customer["Last Name"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(customer["Phone"])
    page.wait_for_timeout(100)

    # Fill tags
    tags_field = page.locator('[id^="autocomplete-textarea"]')
    if tags_field.count():
        tags_field.fill(customer["Tags"])
        print(f"✅ Tags filled: {customer['Tags']}")
    else:
        print("❌ Tags field not found")

    # Fill note
    page.get_by_role("button", name="Add New Note").click()
    page.wait_for_timeout(1000)
    note_title = page.locator('[id^="noteTitle"]')
    note_body = page.locator('[id^="noteBody"]')
    if note_title.count() and note_body.count():
        note_title.fill(customer["Note Title"])
        note_body.fill(customer["Note Body"])
        print(f"✅ Note filled: {customer['Note Title']} / {customer['Note Body']}")
        # Save note
        page.get_by_role("button", name="Save & Exit").click()
        page.wait_for_timeout(1000)
    else:
        print("❌ Note fields not found")

    # Save customer
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(2000)

    # Now on customer detail page — click Add New Address
    try:
        from playwright_automation.new_customer import add_address_on_detail_page
        # First inspect the dialog fields manually
        page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
        page.wait_for_timeout(1500)

        dialog = page.get_by_role("dialog")
        print("\n--- Address Dialog Fields ---")
        inputs = dialog.locator("input, textarea").all()
        for inp in inputs:
            try:
                iid = inp.get_attribute("id") or ""
                ph = inp.get_attribute("placeholder") or ""
                nm = inp.get_attribute("name") or ""
                vis = inp.is_visible()
                print(f"  visible={vis} id={iid!r} ph={ph!r} name={nm!r}")
            except:
                pass

        print("\n--- Address Dialog Buttons ---")
        for b in dialog.get_by_role("button").all():
            try:
                print(f"  BUTTON: {b.inner_text().strip()[:80]}")
            except:
                pass

        # Close without saving
        page.keyboard.press("Escape")

    except PlaywrightTimeoutError as e:
        print(f"❌ Address dialog error: {e}")

    print("\nDone — closing browser.")
    browser.close()
