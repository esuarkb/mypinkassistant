# playwright_automation/new_customer_address.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


def has_address(customer: dict) -> bool:
    """
    Only attempt address entry if Street is present.
    This prevents opening the dialog and hanging on blank addresses.
    """
    return bool((customer.get("Street") or "").strip())


def add_customer_address(page: Page, customer: dict) -> None:
    """
    On the customer detail page, opens Add New Address dialog and fills it.
    Skips entirely if Street is missing.
    """
    if not has_address(customer):
        return

    # Open address dialog
    page.get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(8000)

    # Fill address fields (IDs from your known-working script)
    page.locator("#AddressFirstName-32").fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(500)

    page.locator("#AddressLastName-32").fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(500)

    page.locator("#Street-32").fill(str(customer.get("Street", "")))
    page.wait_for_timeout(500)

    page.locator("#City-32").fill(str(customer.get("City", "")))
    page.wait_for_timeout(500)

    page.locator("#PostalCode-32").fill(str(customer.get("Postal Code", "")))
    page.wait_for_timeout(500)

    # Select state from dropdown
    page.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)

    page.get_by_role("option", name=str(customer.get("State", ""))).click()
    page.wait_for_timeout(700)

    # Save address (button inside dialog)
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(4000)
