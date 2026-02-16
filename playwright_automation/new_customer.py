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

def create_customer_basic(page: Page, customer: dict) -> None:
    # Create a new customer with basic info (name, email, phone, birthday) and optionally address if provided.
    
    # Click "New Customer" to start
    page.get_by_role("button", name="New Customer").click()
    
    # Fill in customer info
    page.get_by_role("textbox", name="First Name").fill(str(customer.get("First Name", "")))

    page.get_by_role("textbox", name="Last Name").fill(str(customer.get("Last Name", "")))

    page.get_by_role("textbox", name="Email Address (Optional)").fill(str(customer.get("Email", "")))

    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(str(customer.get("Phone", "")))

    page.get_by_role("textbox", name="Birthday (Optional)").fill(str(customer.get("Birthday", "")))

    # If we have address info, fill that in too
    if has_address(customer):
        
        #click add new address button
        page.get_by_role("button", name="Add New Address").click()
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        #enter address information
        page.keyboard.type(str(customer.get("First Name", "")))
        page.keyboard.press("Tab")
        page.keyboard.type(str(customer.get("Last Name", "")))
        page.keyboard.press("Tab")
        page.keyboard.type(str(customer.get("Street", "")))
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        page.keyboard.type(str(customer.get("City", "")))
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        page.keyboard.insert_text(str(customer.get("State", "")))
        page.keyboard.press("Tab")
        page.keyboard.type(str(customer.get("Postal Code", "")))
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        # Fill address fields (IDs from your known-working script)
        #page.locator("#AddressFirstName-26").fill(str(customer.get("First Name", "")))
    
        #page.locator("#AddressLastName-26").fill(str(customer.get("Last Name", "")))
    
        #page.locator("#Street-26").fill(str(customer.get("Street", "")))
    
        #page.locator("#City-26").fill(str(customer.get("City", "")))
        #page.locator("#City-26").press("Tab")
        #page.get_by_role("option", name=str(customer.get("State", ""))).click()
        #page.locator("#PostalCode-26").fill(str(customer.get("Postal Code", "")))
    
        # Select state from dropdown
        #page.get_by_role("button", name="Select an option").click()
        #page.locator("#dropdown-button-197").click()
        
        #page.get_by_role("option", name=str(customer.get("State", ""))).click()
        #page.wait_for_timeout(500)

    #if not has_address(customer):
    #    # Save customer (goes to customer detail page)
    #    page.get_by_role("button", name="Save New Customer").click()
    #    page.wait_for_timeout(3000)
    #else
    #save address (button inside dialog)
        #page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
        
    # Save customer (goes to customer detail page)
    page.get_by_role("button", name="Save New Customer").click()
    ensure_mycustomers_ready(page,timeout_ms=30000)