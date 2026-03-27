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
    try:
        page.get_by_role("button", name="New Customer").wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found.")


def has_address(customer: dict) -> bool:
    return bool((customer.get("Street") or "").strip())


def add_address_on_detail_page(page: Page, customer: dict) -> None:
    # Wait for LWC components to finish initializing after save before clicking
    page.wait_for_load_state("networkidle")

    add_address_btn = page.locator("c-cmt-no-info-available").get_by_role(
        "button", name="Add New Address"
    )
    first_name_field = page.locator('[id^="AddressFirstName-"]')

    # LWC renders the button before attaching its click handler — retry until dialog opens
    max_attempts = 4
    success = False
    for attempt in range(max_attempts):
        add_address_btn.click()
        page.wait_for_timeout(500)
        try:
            first_name_field.wait_for(state="visible", timeout=800)
            success = True
            break
        except PlaywrightTimeoutError:
            logger.error(f"Add Address attempt {attempt + 1} failed. Retrying...")

    if not success:
        raise Exception("Add Address dialog failed to open after 4 attempts.")

    first_name_field.fill(str(customer.get("First Name") or ""))
    page.wait_for_timeout(100)

    page.locator('[id^="AddressLastName-"]').fill(str(customer.get("Last Name") or ""))
    page.wait_for_timeout(100)

    page.locator('[id^="Street-"]').fill(str(customer.get("Street") or ""))
    page.wait_for_timeout(100)

    page.locator('[id^="City-"]').fill(str(customer.get("City") or ""))
    page.wait_for_timeout(100)

    page.locator('[id^="PostalCode-"]').fill(str(customer.get("Postal Code") or ""))
    page.wait_for_timeout(100)

    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)

    dialog.get_by_role("option", name=str(customer.get("State", ""))).click()
    page.wait_for_timeout(700)

    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(2000)


def create_customer_basic(page: Page, customer: dict) -> None:
    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=30000)

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

    page.get_by_role("button", name="Save New Customer").click()
    logger.info(f"Clicked Save New Customer. URL: {page.url}")

    try:
        page.get_by_role("button", name="Save New Customer").wait_for(state="detached", timeout=10000)
        logger.info(f"Save New Customer form closed. URL: {page.url}")
    except PlaywrightTimeoutError:
        logger.error(f"Save New Customer form did not close after 10s. URL: {page.url}")
        raise Exception("Save New Customer did not complete — form is still open after 10s. Customer was not saved.")

    if has_address(customer):
        add_address_on_detail_page(page, customer)

    ensure_mycustomers_ready(page, timeout_ms=30000)
