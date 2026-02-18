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
    
    def _insert_firstname_modal(max_attempts: int = 3, timeout_ms: int = 45000):
            addr_first = page.locator('[id^="AddressFirstName-"]:visible').first
            add_firstname = page.locator('[id^="AddressFirstName-"]').fill(str(customer.get("First Name", "")))

            last_err = None
            for _ in range(max_attempts):
                try:
                    # Click without waiting for it to be "visible" (sometimes it is, but Playwright misses state)
                    add_firstname
                    # Wait for the visible address input to show up
                    addr_first.wait_for(state="visible", timeout=timeout_ms)
                    return
                except Exception as e:
                    last_err = e
                    # tiny pause then try clicking again
                    page.wait_for_timeout(300)
            raise RuntimeError(f"Address modal did not open after {max_attempts} tries: {last_err}")

    # Open address dialog
    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(300)    
    page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address").click()

    page.wait_for_timeout(1000)

    #_insert_firstname_modal()
    # Fill address fields (IDs from your known-working script)
    
#    first_name_field = page.locator('[id^="AddressFirstName-"]').first
#    first_name_field.wait_for(state="visible")
#    first_name_field.fill(str(customer.get("First Name", "")))

    #page.locator('[id^="AddressFirstName-"]').fill(str(customer.get("First Name", "")))
    #page.locator('[id^="AddressFirstName-"]')
    

    page.locator('[id^="AddressLastName-"]').fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(100)

    page.locator('[id^="AddressFirstName-"]').fill(str(customer.get("First Name", "")))
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