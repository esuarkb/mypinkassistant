# playwright_automation/new_customer.py

import re
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
    return bool((customer.get("Street") or "").strip())


# def open_mycustomers(page: Page) -> None:
#    # If login.py already lands here, you can stop calling this.
#    page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")
#    ensure_mycustomers_ready(page)


def _safe_fill(locator, value: str, timeout_ms: int = 15000) -> None:
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.fill(value or "")
    # blur/commit (many LWC forms update on blur)
    try:
        locator.press("Tab")
    except Exception:
        pass


def _get_modal_content(page: Page):
    """
    Returns a stable locator scoped to the open modal content.
    Mary Kay uses SLDS modals; this tends to be reliable.
    """
    modal = page.locator(".slds-modal__content").first
    modal.wait_for(state="visible", timeout=30000)
    # click inside to ensure focus is in the modal
    try:
        modal.click(timeout=2000)
    except Exception:
        pass
    return modal


def _field_by_label(modal, label_text: str):
    """
    Find an input inside the modal by label text.
    Tries a few common patterns to be resilient.
    """
    # Prefer a real <label> match if present
    label = modal.locator("label", has_text=label_text).first
    if label.count() > 0:
        # Try "for" attribute -> input id
        try:
            for_id = label.get_attribute("for")
        except Exception:
            for_id = None
        if for_id:
            inp = modal.locator(f"#{for_id}").first
            if inp.count() > 0:
                return inp

        # Otherwise, climb to a container and find textbox
        container = label.locator("xpath=ancestor::*[self::div or self::span][1]")
        tb = container.get_by_role("textbox").first
        if tb.count() > 0:
            return tb

    # Fallback: find element containing the label text, then first textbox near it
    container = modal.locator("div", has=modal.get_by_text(label_text, exact=False)).first
    tb = container.get_by_role("textbox").first
    if tb.count() > 0:
        return tb

    # Last resort: any textbox in modal (not great, but prevents total failure)
    return modal.get_by_role("textbox").first


def _open_state_picker(modal):
    """
    State field might be:
    - combobox (role=combobox)
    - or a button that opens options
    We'll try both.
    """
    # try combobox first
    cb = modal.get_by_role("combobox").first
    if cb.count() > 0:
        cb.wait_for(state="visible", timeout=15000)
        return cb

    # else try a button near "State"
    # look for a container with text "State", then a button inside it
    state_container = modal.locator("div", has=modal.get_by_text("State", exact=False)).first
    btn = state_container.get_by_role("button").first
    if btn.count() > 0:
        btn.wait_for(state="visible", timeout=15000)
        return btn

    # fallback: any button that looks like a dropdown
    btn2 = modal.get_by_role("button", name=re.compile(r"(select|choose)", re.I)).first
    btn2.wait_for(state="visible", timeout=15000)
    return btn2


def _select_state(modal, state_val: str) -> None:
    state_val = (state_val or "").strip()
    if not state_val:
        return

    picker = _open_state_picker(modal)

    # If it's a combobox, fill/search then pick option
    try:
        if picker.get_attribute("role") == "combobox":
            picker.click()
            try:
                picker.fill(state_val)
            except Exception:
                pass
        else:
            picker.click()
    except Exception:
        picker.click()

    # Options might render outside modal; don't scope too tightly here
    opt = modal.page.get_by_role("option", name=state_val).first
    opt.wait_for(state="visible", timeout=20000)
    opt.click()


def _save_address_in_modal(modal) -> None:
    """
    The button text might vary; match common variants.
    Must be within modal (not the page).
    """
    btn = modal.get_by_role("button", name=re.compile(r"(add|save).*(address)", re.I)).first
    btn.wait_for(state="visible", timeout=20000)
    expect(btn).to_be_enabled(timeout=20000)
    btn.click()

    # Wait for modal content to disappear
    try:
        modal.wait_for(state="hidden", timeout=30000)
    except PlaywrightTimeoutError:
        # sometimes modal doesn't fully hide; at least proceed
        pass


def _add_address_via_modal(page: Page, customer: dict) -> None:
    """
    Clicks Add New Address, fills fields by label, selects state, saves.
    """
    add_addr_btn = page.get_by_role("button", name="Add New Address")
    add_addr_btn.wait_for(state="visible", timeout=20000)
    expect(add_addr_btn).to_be_enabled(timeout=20000)
    add_addr_btn.click()

    modal = _get_modal_content(page)

    _safe_fill(_field_by_label(modal, "First Name"), str(customer.get("First Name", "")))
    _safe_fill(_field_by_label(modal, "Last Name"), str(customer.get("Last Name", "")))
    _safe_fill(_field_by_label(modal, "Street"), str(customer.get("Street", "")))
    _safe_fill(_field_by_label(modal, "City"), str(customer.get("City", "")))
    _safe_fill(_field_by_label(modal, "Postal"), str(customer.get("Postal Code", "")))

    _select_state(modal, str(customer.get("State", "")))

    _save_address_in_modal(modal)


def create_customer_basic(page: Page, customer: dict) -> None:
    """
    Creates ONE customer (name/email/phone/birthday) and clicks Save New Customer.
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

    # Optional address flow
    if has_address(customer):
        _add_address_via_modal(page, customer)

    # Save customer
    save_btn = page.get_by_role("button", name="Save New Customer")
    save_btn.wait_for(state="visible", timeout=20000)
    expect(save_btn).to_be_enabled(timeout=20000)
    save_btn.click()

    # Stable end signal
    ensure_mycustomers_ready(page)