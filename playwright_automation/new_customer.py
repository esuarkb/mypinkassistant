# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"


def ensure_mycustomers_ready(page: Page, timeout_ms: int = 20000) -> None:
    # When MyCustomers is ready, this button exists. If it doesn't appear in time, something is wrong.
    try:
        page.get_by_role("button", name="New Customer").wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found.")

def has_address(customer: dict) -> bool:
    # Simple check: if Street is present and non-empty, assume we have an address to enter.
    return bool((customer.get("Street") or "").strip())

def add_address_on_detail_page(page: Page, customer: dict) -> None:
    # Click the Add New Address button that appears AFTER saving


    # Open address dialog
    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
    #page.get_by_role("button", name="Add New Address").click()
    #page.get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(2500)

    # Fill address fields (IDs from your known-working script)
    page.locator('[id^="AddressFirstName-"]').fill(str(customer.get("First Name", "")))
    #page.locator('[id^="AddressFirstName-"]')
    page.wait_for_timeout(100)

    page.locator('[id^="AddressLastName-"]').fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(100)

    page.locator('[id^="Street-"]').fill(str(customer.get("Street", "")))
    page.wait_for_timeout(100)

    page.locator('[id^="City-"]').fill(str(customer.get("City", "")))
    page.wait_for_timeout(100)

    page.locator('[id^="PostalCode-"]').fill(str(customer.get("Postal Code", "")))
    page.wait_for_timeout(100)

    # Select state from dropdown
    page.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)

    page.get_by_role("option", name=str(customer.get("State", ""))).click()
    page.wait_for_timeout(700)

    # Complete and Save address (button inside dialog)
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(2000)
    

def create_customer_basic(page: Page, customer: dict) -> None:
    # Create a new customer with basic info (name, email, phone, birthday) and optionally address if provided.
    
    # Click "New Customer" to start
    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=30000)
    # Fill in customer info
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="First Name").fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Last Name").fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Email Address (Optional)").fill(str(customer.get("Email", "")))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(str(customer.get("Phone", "")))
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Birthday (Optional)").fill(str(customer.get("Birthday", "")))
    page.wait_for_timeout(100)
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(1000)
    
    # If we have address info, fill that in too
    if has_address(customer):
        add_address_on_detail_page(page, customer)
    
    # Save customer (goes to customer detail page)
    #page.get_by_role("button", name="Save New Customer").click()
    ensure_mycustomers_ready(page,timeout_ms=30000)