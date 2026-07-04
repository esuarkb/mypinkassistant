# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
import logging
import sys

from playwright_automation.step_log import step

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

    step("new_customer.addr", 1, 5, "open_address_dialog", "clicking 'Add New Address' (up to 4 attempts)")
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
    step("new_customer.addr", 2, 5, "fill_address_fields", "filling name/street/city/postal fields")
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

    step("new_customer.addr", 3, 5, "select_state", f"selecting state '{str(customer.get('State') or '')}' from dropdown")
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
    step("new_customer.addr", 4, 5, "submit_address_dialog", "clicking dialog 'Add New Address'")
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()

    # Wait for the address modal to fully close before moving on.
    # The AddressFirstName field is inside the dialog — when it goes hidden the modal is gone.
    # If still open it will intercept pointer events and block the subscription click.
    step("new_customer.addr", 5, 5, "wait_dialog_closed", "waiting for address dialog to close")
    try:
        first_name_field.wait_for(state="hidden", timeout=10000)
    except PlaywrightTimeoutError:
        logger.warning("Address modal did not close cleanly — proceeding anyway.")
    page.wait_for_timeout(1000)
    

def create_customer_basic(page: Page, customer: dict) -> None:
    # Create a new customer with basic info (name, email, phone, birthday) and optionally address if provided.
    _name = f"{customer.get('First Name', '')} {customer.get('Last Name', '')}".strip()
    print(f"[NewCustomer] Starting: {_name}")

    # Click "New Customer" to start
    step("new_customer", 1, 10, "click_new_customer", "clicking 'New Customer'")
    page.get_by_role("button", name="New Customer").click()
    step("new_customer", 2, 10, "wait_first_name_field", "waiting for 'First Name' textbox")
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=30000)
    # Fill in customer info
    page.wait_for_timeout(2000)
    step("new_customer", 3, 10, "fill_basic_fields", f"filling name/email/phone/birthday for {_name}")
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

    referred_by = str(customer.get("Referred By") or "").strip()
    if referred_by:
        step("new_customer", 4, 10, "fill_referred_by", "filling 'Referred By (Optional)'")
        page.get_by_role("textbox", name="Referred By (Optional)").fill(referred_by)
        page.wait_for_timeout(100)

    tags = str(customer.get("Tags") or "").strip()
    if tags:
        step("new_customer", 5, 10, "fill_tags", f"entering tags: {tags}")
        tags_field = page.locator('[id^="autocomplete-textarea"]')
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            tags_field.fill(tag)
            page.wait_for_timeout(200)
            tags_field.press("Enter")
            page.wait_for_timeout(200)

    step("new_customer", 6, 10, "click_save_new_customer", "clicking 'Save New Customer'")
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(1500)
    step("new_customer", 7, 10, "check_error_banner", "checking for InTouch error banner")
    if page.locator('.slds-notify.slds-theme_error').is_visible():
        err = page.locator('.slds-notify.slds-theme_error').first.inner_text()
        lines = [l.strip() for l in err.split('\n') if l.strip() and l.strip().lower() not in ('error', 'close')]
        raise RuntimeError(f"InTouch: {' '.join(lines)}")
    print(f"[NewCustomer] Basic info saved: {_name}")

    # If we have address info, fill that in too
    if has_address(customer):
        step("new_customer", 8, 10, "add_address", "starting address sub-flow (see new_customer.addr steps)")
        print(f"[NewCustomer] Adding address")
        add_address_on_detail_page(page, customer)
        print(f"[NewCustomer] Address saved")

    # Enable subscriptions if customer has email
    subscription_ok = True
    if str(customer.get("Email") or "").strip():
        step("new_customer", 9, 10, "enable_subscriptions", "starting subscription sub-flow (see new_customer.subs steps; failures non-fatal)")
        print(f"[NewCustomer] Starting subscription toggles")
        try:
            step("new_customer.subs", 1, 4, "wait_subscriptions_section", "waiting for subscriptions section")
            subscriptions = page.locator("c-cmt-my-customer-details-subscriptions")
            subscriptions.wait_for(state="visible", timeout=20000)

            # Retry opening the subscriptions dialog (same pattern as address dialog)
            sub_btn = subscriptions.get_by_role("button")
            dialog_toggle = page.locator("c-cmt-custom-toggle").nth(0).locator("label")
            max_attempts = 3
            dialog_opened = False
            step("new_customer.subs", 2, 4, "open_subscription_dialog", "opening subscriptions dialog (up to 3 attempts)")
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

            print(f"[NewCustomer] Subscription dialog opened")
            dialog = page.get_by_role("dialog")
            for nth in (0, 1):
                step("new_customer.subs", 3, 4, "toggle_switch", f"switching on toggle {nth} (up to 3 attempts)")
                label = dialog.locator("c-cmt-custom-toggle").nth(nth).locator("label")
                toggle_input = dialog.locator("c-cmt-custom-toggle").nth(nth).locator("input.toggle-input")
                for attempt in range(3):
                    label.click()
                    page.wait_for_timeout(500)
                    if toggle_input.is_checked():
                        break
                else:
                    raise Exception(f"Toggle {nth} did not switch on after 3 attempts")
                page.wait_for_timeout(300)
            step("new_customer.subs", 4, 4, "save_and_exit", "clicking 'Save & Exit', waiting for dialog to close")
            dialog.get_by_role("button", name="Save & Exit").click()
            dialog.wait_for(state="hidden", timeout=8000)
            print(f"[NewCustomer] Subscriptions saved")
        except Exception as e:
            logger.warning(f"Subscription toggle failed (non-fatal): {e}")
            subscription_ok = False

    # Save customer (goes to customer detail page)
    #page.get_by_role("button", name="Save New Customer").click()
    step("new_customer", 10, 10, "wait_mycustomers_ready_post_save", "waiting for MyCustomers ready after save")
    try:
        ensure_mycustomers_ready(page, timeout_ms=30000)
    except RuntimeError as e:
        if "Timeout" in str(e):
            raise RuntimeError("Timeout: Post-save confirmation — customer was already saved")
        raise
    print(f"[NewCustomer] Complete: {_name} subscription_ok={subscription_ok}")
    return subscription_ok