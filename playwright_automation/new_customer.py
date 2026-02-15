## update old with new logic

# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"


def ensure_mycustomers_ready(page: Page, timeout_ms: int = 20000) -> None:
    """
    Confirms MyCustomers page is usable by waiting for the New Customer button.
    """
    try:
        btn = page.get_by_role("button", name="New Customer")
        btn.wait_for(state="visible", timeout=timeout_ms)
        expect(btn).to_be_enabled(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found.")


def has_address(customer: dict) -> bool:
    """Only attempt address entry if Street is present."""
    return bool((customer.get("Street") or "").strip())


def _safe_fill(locator, value: str, timeout_ms: int = 20000) -> None:
    """
    Wait visible -> fill -> blur (tab). No sleeps.
    """
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.fill(value or "")
    try:
        locator.press("Tab")
    except Exception:
        pass


def _select_state_in_modal(modal, state_name: str, timeout_ms: int = 20000) -> None:
    """
    State dropdown ids change (197/203/etc). Use a stable selector:
    button[id^="dropdown-button-"] inside the modal, then click the option by name.
    """
    state_name = (state_name or "").strip()
    if not state_name:
        return

    dd = modal.locator('button[id^="dropdown-button-"]').first
    dd.wait_for(state="visible", timeout=timeout_ms)
    expect(dd).to_be_enabled(timeout=timeout_ms)
    dd.click()

    opt = modal.get_by_role("option", name=state_name).first
    opt.wait_for(state="visible", timeout=timeout_ms)
    opt.click()


def _add_address_via_modal(page: Page, customer: dict) -> None:
    """
    Clicks 'Add New Address', waits for the modal, fills address fields, saves.
    All selectors are scoped to the modal to avoid ambiguity.
    """
    # Click open-address button (page level)
    open_btn = page.get_by_role("button", name="Add New Address")
    open_btn.wait_for(state="visible", timeout=20000)
    expect(open_btn).to_be_enabled(timeout=20000)
    open_btn.click()

    # Wait for modal content (stable class used by Salesforce/LWC modals)
    modal = page.locator(".slds-modal__content.slds-p-around_medium").first
    modal.wait_for(state="visible", timeout=20000)

    # Optional: click inside modal once to ensure focus is inside it
    try:
        modal.click()
    except Exception:
        pass

    # Fill address fields INSIDE modal (IDs you said are stable)
    _safe_fill(modal.locator("#AddressFirstName-26"), str(customer.get("First Name", "")))
    _safe_fill(modal.locator("#AddressLastName-26"), str(customer.get("Last Name", "")))
    _safe_fill(modal.locator("#Street-26"), str(customer.get("Street", "")))
    _safe_fill(modal.locator("#City-26"), str(customer.get("City", "")))
    _safe_fill(modal.locator("#PostalCode-26"), str(customer.get("Postal Code", "")))

    # State dropdown (dynamic id) — do it by stable selector within modal
    _select_state_in_modal(modal, str(customer.get("State", "")).strip())

    # Save address button INSIDE modal
    # (There are two buttons named "Add New Address": open button and modal submit button)
    save_btn = modal.get_by_role("button", name="Add New Address")
    save_btn.wait_for(state="visible", timeout=20000)
    expect(save_btn).to_be_enabled(timeout=20000)
    save_btn.click()

    # Wait for modal to close (best signal that it actually saved)
    try:
        modal.wait_for(state="hidden", timeout=20000)
    except PlaywrightTimeoutError:
        # If it doesn't fully hide, don't hard-fail here — the next "Save New Customer"
        # will usually still work. We keep it resilient.
        pass


def create_customer_basic(page: Page, customer: dict) -> None:
    """
    Creates ONE customer and saves.
    Optionally adds address if Street is present.
    """

    # Click "New Customer"
    new_btn = page.get_by_role("button", name="New Customer")
    new_btn.wait_for(state="visible", timeout=20000)
    expect(new_btn).to_be_enabled(timeout=20000)
    new_btn.click()

    # Wait for form
    first_name = page.get_by_role("textbox", name="First Name")
    first_name.wait_for(state="visible", timeout=20000)

    # Fill customer info
    _safe_fill(first_name, str(customer.get("First Name", "")))
    _safe_fill(page.get_by_role("textbox", name="Last Name"), str(customer.get("Last Name", "")))
    _safe_fill(page.get_by_role("textbox", name="Email Address (Optional)"), str(customer.get("Email", "")))
    _safe_fill(page.get_by_role("textbox", name="Mobile Phone Number (Optional)"), str(customer.get("Phone", "")))
    _safe_fill(page.get_by_role("textbox", name="Birthday (Optional)"), str(customer.get("Birthday", "")))

    # Optional address
    if has_address(customer):
        _add_address_via_modal(page, customer)

    # Save customer
    save_btn = page.get_by_role("button", name="Save New Customer")
    save_btn.wait_for(state="visible", timeout=20000)
    expect(save_btn).to_be_enabled(timeout=20000)
    save_btn.click()

    # Stable end signal: we're back to the list ready state
    ensure_mycustomers_ready(page)