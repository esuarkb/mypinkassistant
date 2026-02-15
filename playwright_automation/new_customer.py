## update for speed

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
        # also ensure it's clickable (enabled)
        expect(btn).to_be_enabled(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers not ready: 'New Customer' button not found at end of customer entry.")


def has_address(customer: dict) -> bool:
    """
    Only attempt address entry if Street is present.
    """
    return bool((customer.get("Street") or "").strip())


def open_mycustomers(page: Page) -> None:
    """
    Navigates to MyCustomers and confirms it is ready.
    NOTE: If login.py already lands you here, you can stop calling this.
    """
    page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")
    ensure_mycustomers_ready(page)


def _safe_fill(locator, value: str, timeout_ms: int = 15000) -> None:
    """
    Faster than adding sleeps: wait visible -> fill -> blur (tab) to trigger UI validation.
    """
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.fill(value or "")
    # blur/commit (many LWC forms update on blur)
    try:
        locator.press("Tab")
    except Exception:
        pass


def create_customer_basic(page: Page, customer: dict) -> None:
    """
    Creates ONE customer (name/email/phone/birthday) and clicks Save New Customer.
    Optionally adds address if Street is present.
    """

    # 1) Click "New Customer"
    new_btn = page.get_by_role("button", name="New Customer")
    new_btn.wait_for(state="visible", timeout=20000)
    expect(new_btn).to_be_enabled(timeout=20000)
    new_btn.click()

    # 2) Wait for the form fields to appear (this replaces the 3s sleep)
    first_name = page.get_by_role("textbox", name="First Name")
    first_name.wait_for(state="visible", timeout=20000)

    # 3) Fill customer info (no sleeps)
    _safe_fill(first_name, str(customer.get("First Name", "")))
    _safe_fill(page.get_by_role("textbox", name="Last Name"), str(customer.get("Last Name", "")))

    _safe_fill(
        page.get_by_role("textbox", name="Email Address (Optional)"),
        str(customer.get("Email", "")),
    )
    _safe_fill(
        page.get_by_role("textbox", name="Mobile Phone Number (Optional)"),
        str(customer.get("Phone", "")),
    )
    _safe_fill(
        page.get_by_role("textbox", name="Birthday (Optional)"),
        str(customer.get("Birthday", "")),
    )

    # 4) Optional address flow
    if has_address(customer):
        add_addr_btn = page.get_by_role("button", name="Add New Address")
        add_addr_btn.wait_for(state="visible", timeout=20000)
        expect(add_addr_btn).to_be_enabled(timeout=20000)
        add_addr_btn.click()

        # Wait for dialog
        dlg = page.get_by_role("dialog")
        dlg.wait_for(state="visible", timeout=20000)

        # Your known-working IDs (but guarded)
        _safe_fill(page.locator("#AddressFirstName-26"), str(customer.get("First Name", "")))
        _safe_fill(page.locator("#AddressLastName-26"), str(customer.get("Last Name", "")))
        _safe_fill(page.locator("#Street-26"), str(customer.get("Street", "")))
        _safe_fill(page.locator("#City-26"), str(customer.get("City", "")))
        _safe_fill(page.locator("#PostalCode-26"), str(customer.get("Postal Code", "")))

        # State dropdown (keep your selector but wait it properly)
        state_val = str(customer.get("State", "")).strip()
        if state_val:
            dd = page.locator("#dropdown-button-197")
            dd.wait_for(state="visible", timeout=20000)
            dd.click()

            opt = page.get_by_role("option", name=state_val)
            opt.wait_for(state="visible", timeout=20000)
            opt.click()

        # Save address inside dialog
        save_addr = dlg.get_by_role("button", name="Add New Address")
        expect(save_addr).to_be_enabled(timeout=20000)
        save_addr.click()

        # Wait for dialog to close (replaces the 4s sleep)
        try:
            dlg.wait_for(state="hidden", timeout=20000)
        except PlaywrightTimeoutError:
            # If it doesn't fully hide, at least ensure we're out of the modal state
            pass

    # 5) Save customer
    save_btn = page.get_by_role("button", name="Save New Customer")
    save_btn.wait_for(state="visible", timeout=20000)
    expect(save_btn).to_be_enabled(timeout=20000)
    save_btn.click()

    # Wait for save to finish:
    # - often the button disables briefly OR page navigates back to list/detail
    # We'll wait for MyCustomers ready again as a stable end signal.
    ensure_mycustomers_ready(page)
