# playwright_automation/new_customer.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"


def ensure_mycustomers_ready(page: Page, timeout_ms: int = 20000) -> None:
    try:
        btn = page.get_by_role("button", name="New Customer")
        btn.wait_for(state="visible", timeout=timeout_ms)
        expect(btn).to_be_enabled(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found.")


def has_address(customer: dict) -> bool:
    return bool((customer.get("Street") or "").strip())


def _safe_fill(locator, value: str, timeout_ms: int = 20000) -> None:
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.fill(value or "")
    # commit blur (some LWC fields validate on blur)
    try:
        locator.press("Tab")
    except Exception:
        pass


def _wait_for_address_fields(page: Page, timeout_ms: int = 20000) -> None:
    """
    No modal assumptions. We treat the presence of AddressFirstName-26 as the "address UI is ready" signal.
    """
    page.locator("#AddressFirstName-26").wait_for(state="visible", timeout=timeout_ms)
    page.locator("#Street-26").wait_for(state="visible", timeout=timeout_ms)


def _select_state_no_modal(page: Page, state_name: str, timeout_ms: int = 20000) -> None:
    """
    Dropdown button id changes (197/203/206...). Avoid hardcoded id.
    Strategy:
      - Find the PostalCode field
      - Find the nearest dropdown button in the same address area
    """
    state_name = (state_name or "").strip()
    if not state_name:
        return

    postal = page.locator("#PostalCode-26")
    postal.wait_for(state="visible", timeout=timeout_ms)

    # Best-effort: find dropdown button near postal code in the DOM
    # We look "up" a bit then find first dropdown button.
    container = postal.locator("xpath=ancestor::*[self::div or self::section][1]")
    dd = container.locator('button[id^="dropdown-button-"]').first

    # Fallback if container guess fails
    if dd.count() == 0:
        dd = page.locator('button[id^="dropdown-button-"]').first

    dd.wait_for(state="visible", timeout=timeout_ms)
    expect(dd).to_be_enabled(timeout=timeout_ms)
    dd.click()

    opt = page.get_by_role("option", name=state_name).first
    opt.wait_for(state="visible", timeout=timeout_ms)
    opt.click()


def _click_add_address_submit(page: Page, timeout_ms: int = 20000) -> None:
    """
    There are two "Add New Address" buttons:
      1) the one that OPENS the address form
      2) the one that SUBMITS the address
    After fields are visible, the submit one is usually later in the DOM.
    We'll click the LAST visible enabled one.
    """
    btns = page.get_by_role("button", name="Add New Address")
    btns.first.wait_for(state="visible", timeout=timeout_ms)  # at least one exists

    # Click the last one (submit) — avoids the opener button
    last = btns.nth(btns.count() - 1)
    last.wait_for(state="visible", timeout=timeout_ms)
    expect(last).to_be_enabled(timeout=timeout_ms)
    last.click()


def _add_address_no_modal(page: Page, customer: dict) -> None:
    open_btn = page.get_by_role("button", name="Add New Address")
    open_btn.wait_for(state="visible", timeout=20000)
    expect(open_btn).to_be_enabled(timeout=20000)
    open_btn.click()

    # ✅ key change: wait for actual address field IDs, not modal
    _wait_for_address_fields(page, timeout_ms=20000)

    _safe_fill(page.locator("#AddressFirstName-26"), str(customer.get("First Name", "")))
    _safe_fill(page.locator("#AddressLastName-26"), str(customer.get("Last Name", "")))
    _safe_fill(page.locator("#Street-26"), str(customer.get("Street", "")))
    _safe_fill(page.locator("#City-26"), str(customer.get("City", "")))
    _safe_fill(page.locator("#PostalCode-26"), str(customer.get("Postal Code", "")))

    _select_state_no_modal(page, str(customer.get("State", "")), timeout_ms=20000)

    _click_add_address_submit(page, timeout_ms=20000)

    # Give the UI a moment to apply address (no hard sleep; wait for street field to go away OR remain but disabled)
    # If it doesn't change, don't fail — customer save can still succeed.
    try:
        page.locator("#AddressFirstName-26").wait_for(state="hidden", timeout=8000)
    except PlaywrightTimeoutError:
        pass


def create_customer_basic(page: Page, customer: dict) -> None:
    # Click "New Customer"
    new_btn = page.get_by_role("button", name="New Customer")
    new_btn.wait_for(state="visible", timeout=20000)
    expect(new_btn).to_be_enabled(timeout=20000)
    new_btn.click()

    # Wait for form
    first_name = page.get_by_role("textbox", name="First Name")
    first_name.wait_for(state="visible", timeout=20000)

    # Fill base fields
    _safe_fill(first_name, str(customer.get("First Name", "")))
    _safe_fill(page.get_by_role("textbox", name="Last Name"), str(customer.get("Last Name", "")))
    _safe_fill(page.get_by_role("textbox", name="Email Address (Optional)"), str(customer.get("Email", "")))
    _safe_fill(page.get_by_role("textbox", name="Mobile Phone Number (Optional)"), str(customer.get("Phone", "")))
    _safe_fill(page.get_by_role("textbox", name="Birthday (Optional)"), str(customer.get("Birthday", "")))

    # Optional address (no modal waits)
    if has_address(customer):
        _add_address_no_modal(page, customer)

    # Save customer
    save_btn = page.get_by_role("button", name="Save New Customer")
    save_btn.wait_for(state="visible", timeout=20000)
    expect(save_btn).to_be_enabled(timeout=20000)
    save_btn.click()

    # Stable end signal
    ensure_mycustomers_ready(page)