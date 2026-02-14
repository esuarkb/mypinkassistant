# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


MYCUSTOMERS_URL = "https://applications.marykayintouch.com/mycustomers"


#def ensure_mycustomers_ready(page: Page, timeout_ms: int = 20000) -> None:
#    """
#    Confirms MyCustomers page is usable by waiting for the New Customer button.
#    """
#    try:
#        page.get_by_role("button", name="New Customer").wait_for(timeout=timeout_ms)
#    except PlaywrightTimeoutError:
#        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found.")


def open_mycustomers(page: Page) -> None:
    """
    Navigates to MyCustomers and confirms it is ready.
    """
    page.goto(MYCUSTOMERS_URL)
    page.wait_for_timeout(6000)
#    ensure_mycustomers_ready(page)


def create_customer_basic(page: Page, customer: dict) -> None:
    """
    Creates ONE customer (name/email/phone) and clicks Save New Customer.
    Does NOT enter address.
    """
    # Add customer
    page.get_by_role("button", name="New Customer").click()
    page.wait_for_timeout(3000)

    # Fill in customer info
    page.get_by_role("textbox", name="First Name").fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(500)

    page.get_by_role("textbox", name="Last Name").fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(500)

    page.get_by_role("textbox", name="Email Address (Optional)").fill(str(customer.get("Email", "")))
    page.wait_for_timeout(500)

    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(str(customer.get("Phone", "")))
    page.wait_for_timeout(500)

    page.get_by_role("textbox", name="Birthday (Optional)").fill(str(customer.get("Birthday", "")))
    page.wait_for_timeout(500)

    # Save customer (goes to customer detail page)
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(5000)
