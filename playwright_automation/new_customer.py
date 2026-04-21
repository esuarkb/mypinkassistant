# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"


def ensure_mycustomers_ready(page: Page, timeout_ms: int = 20000) -> None:
    # When MyCustomers is ready, this button exists. If it doesn't appear in time, something is wrong.
    try:
        page.get_by_role("button", name="New Customer").wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("Timeout: MyCustomers page not ready — 'New Customer' button not found.")

def has_address(customer: dict) -> bool:
    # All four fields required — InTouch needs a complete address or none at all.
    return (
        bool((customer.get("Street") or "").strip())
        and bool((customer.get("City") or "").strip())
        and bool((customer.get("State") or "").strip())
        and bool((customer.get("Postal Code") or "").strip())
    )

def add_address_on_detail_page(page: Page, customer: dict) -> None:
    # Click the Add New Address button that appears AFTER saving
    
##new test

    add_address_btn = page.locator("c-cmt-no-info-available").get_by_role(
        "button", name="Add New Address"
    )



    first_name_field = page.locator('[id^="AddressFirstName-"]')

    max_attempts = 4
    success = False

    for _ in range(max_attempts):
    # 1) Click once
        add_address_btn.click()
        page.wait_for_timeout(500)
    # 2) Try to detect the First Name field quickly
        try:
            first_name_field.wait_for(state="visible", timeout=800)  # fast check
            success = True
            break  # if found, break out of the loop
        except PlaywrightTimeoutError:
            pass
    
    if not success:
        raise Exception("Add Address dialog failed to open after 3 attempts.")

    # 5) Fill once it's truly ready
    first_name_field.fill(str(customer.get("First Name") or ""))
    
    # Open address dialog
#    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
#   page.wait_for_timeout(300)    
#    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
#    page.wait_for_timeout(500)
#    page.locator('[id^="AddressFirstName-"]').fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(100)

    page.locator('[id^="AddressLastName-"]').fill(str(customer.get("Last Name") or ""))
    page.wait_for_timeout(100)
    
    page.locator('[id^="Street-"]').fill(str(customer.get("Street") or ""))
    page.wait_for_timeout(100)

    dialog = page.get_by_role("dialog")

    street2 = str(customer.get("Street2") or "").strip()
    if street2:
        dialog.get_by_role("button", name="Add Apartment/Suite/Etc").click()
        page.wait_for_timeout(500)
        page.locator('[id^="StreetLine2_t__c-"]').fill(street2)
        page.wait_for_timeout(100)

    page.locator('[id^="City-"]').fill(str(customer.get("City") or ""))
    page.wait_for_timeout(100)

    page.locator('[id^="PostalCode-"]').fill(str(customer.get("Postal Code") or ""))
    page.wait_for_timeout(100)

    #new state dropdown logic:

    dialog.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)

    dialog.get_by_role("option", name=str(customer.get("State") or ""), exact=True).click()
    page.wait_for_timeout(700)
    
    # OLD Select state from dropdown
    #page.get_by_role("button", name="Select an option").click()
    #page.wait_for_timeout(700)

    #page.get_by_role("option", name=str(customer.get("State", ""))).click()
    #page.wait_for_timeout(700)

    # Complete and Save address (button inside dialog)
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()

    # Wait for the address modal to fully close before moving on.
    # The AddressFirstName field is inside the dialog — when it goes hidden the modal is gone.
    # If still open it will intercept pointer events and block the subscription click.
    try:
        first_name_field.wait_for(state="hidden", timeout=10000)
    except PlaywrightTimeoutError:
        logger.warning("Address modal did not close cleanly — proceeding anyway.")
    page.wait_for_timeout(1000)
    

def create_customer_basic(page: Page, customer: dict) -> None:
    # Create a new customer with basic info (name, email, phone, birthday) and optionally address if provided.

    # Click "New Customer" to start
    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=30000)
    # Fill in customer info
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="First Name").fill(str(customer.get("First Name") or ""))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Last Name").fill(str(customer.get("Last Name") or ""))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Email Address (Optional)").fill(str(customer.get("Email") or ""))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(str(customer.get("Phone") or ""))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Birthday (Optional)").fill(str(customer.get("Birthday") or ""))
    page.wait_for_timeout(100)

    tags = str(customer.get("Tags") or "").strip()
    if tags:
        tags_field = page.locator('[id^="autocomplete-textarea"]')
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            tags_field.fill(tag)
            page.wait_for_timeout(200)
            tags_field.press("Enter")
            page.wait_for_timeout(200)

    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(1000)
    
    # If we have address info, fill that in too
    if has_address(customer):
        add_address_on_detail_page(page, customer)

    # Enable subscriptions if customer has email
    subscription_ok = True
    if str(customer.get("Email") or "").strip():
        try:
            subscriptions = page.locator("c-cmt-my-customer-details-subscriptions")
            subscriptions.wait_for(state="visible", timeout=20000)

            # Retry opening the subscriptions dialog (same pattern as address dialog)
            sub_btn = subscriptions.get_by_role("button")
            dialog_toggle = page.locator("c-cmt-custom-toggle").nth(0).locator("label")
            max_attempts = 3
            dialog_opened = False
            for attempt in range(max_attempts):
                if not dialog_toggle.is_visible():
                    sub_btn.click()
                    page.wait_for_timeout(500)
                try:
                    dialog_toggle.wait_for(state="visible", timeout=4000)
                    dialog_opened = True
                    break
                except PlaywrightTimeoutError:
                    logger.warning(f"Subscription dialog attempt {attempt + 1} failed, retrying...")

            if not dialog_opened:
                raise Exception("Subscription dialog failed to open after 3 attempts.")

            dialog = page.get_by_role("dialog")
            dialog.locator("c-cmt-custom-toggle").nth(0).locator("label").click()
            page.wait_for_timeout(800)
            dialog.locator("c-cmt-custom-toggle").nth(1).locator("label").click()
            page.wait_for_timeout(1000)
            dialog.get_by_role("button", name="Save & Exit").click()
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"Subscription toggle failed (non-fatal): {e}")
            subscription_ok = False

    # Save customer (goes to customer detail page)
    #page.get_by_role("button", name="Save New Customer").click()
    try:
        ensure_mycustomers_ready(page, timeout_ms=30000)
    except RuntimeError as e:
        if "Timeout" in str(e):
            raise RuntimeError("Timeout: Post-save confirmation — customer was already saved")
        raise
    return subscription_ok