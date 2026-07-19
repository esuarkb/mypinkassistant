# playwright_automation/orders.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from playwright_automation.step_log import step


CUSTOMER_LIST_URL = "https://apps.marykayintouch.com/customer-list"


# -------------------------
# Readiness check
# -------------------------
def ensure_orders_ready(page: Page, timeout_ms: int = 20000) -> None:
    """
    Confirms Orders page is usable by waiting for New Order button.
    """
    try:
        page.get_by_role("button", name="New Order").wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("Timeout: Orders page not ready — 'New Order' button not found.")


def open_customer_list(page: Page) -> None:
    """
    Navigates to the customer list used for order placement.
    """
    page.goto(CUSTOMER_LIST_URL)
    ensure_orders_ready(page)


# -------------------------
# Order helpers
# -------------------------
def open_customer_and_start_order(page: Page, first: str, last: str, fulfillment_method: str = "inventory", order_date: str = None) -> None:
    """
    Opens a customer and starts a new order.
    fulfillment_method: "inventory" (default) or "cds"
    order_date: optional YYYY-MM-DD string to set on the order form
    Safely handles duplicate customer names by selecting the first match.
    """
    full_name = f"{first} {last}"

    #go to customer list and wait for load
    step("orders", 1, 17, "open_customer_list", "navigating to customer list, waiting for 'New Order' button")
    open_customer_list(page)
    page.wait_for_timeout(3000)

    # Search customer, small wait for search results to populate
    step("orders", 2, 17, "search_customer", f"searching for '{full_name}'")
    page.get_by_role("searchbox", name="Note Title").fill(full_name)
    page.wait_for_timeout(500)

    # Existence check (duplicate-safe)
    step("orders", 3, 17, "verify_customer_exists", f"waiting for '{full_name}' in results")
    try:
        page.get_by_text(full_name).first.wait_for(timeout=3000)
    except PlaywrightTimeoutError:
        raise RuntimeError(
            f"Customer not found: '{full_name}'. "
            "Make sure they have been added to MyCustomers and please try again."
        )

    # Select customer from search results (first match if duplicates), loads customer page
    step("orders", 4, 17, "select_customer", f"clicking '{full_name}'")
    page.get_by_text(full_name).first.click()
    page.wait_for_timeout(1000)

    # Click New Order Button and load order page
    step("orders", 5, 17, "click_add_order", "clicking 'Add Order'")
    page.get_by_role("button", name="Add Order").click()
    page.wait_for_timeout(3000)

    # Set order date if provided (field is pre-filled with today — only override if specified)
    if order_date:
        step("orders", 6, 17, "set_order_date", f"setting order date {order_date}")
        try:
            date_input = page.locator("input[id^='order-date']").first
            date_input.wait_for(state="visible", timeout=5000)
            date_input.fill(order_date)
            page.wait_for_timeout(300)
        except PlaywrightTimeoutError:
            pass  # date field not found — proceed with today's date

    # Select fulfillment method
    if fulfillment_method == "cds":
        step("orders", 7, 17, "select_fulfillment_method", "clicking 'Customer Delivery Service'")
        page.get_by_text("Customer Delivery Service").click()
    else:
        step("orders", 7, 17, "select_fulfillment_method", "clicking 'My Inventory'")
        page.get_by_text("My Inventory").click()
    page.wait_for_timeout(1200)


#def add_sku_to_bag(page: Page, sku: str) -> None:
    
#    #search for SKU, small wait for search results to populate
#    page.get_by_role("searchbox", name="Note Title").fill(sku)
#    page.wait_for_timeout(1200)

    #click add to Bag
#    page.get_by_role("button", name="Add to Bag").click()
#    page.wait_for_timeout(300)

class SkuNotCdsEligible(Exception):
    pass

def add_sku_to_bag(page: Page, sku: str, fulfillment_method: str = "inventory") -> None:
    # search for SKU and wait for results to populate. InTouch's LWC search box
    # can drop the first fill() if its JS listener isn't attached yet (query never
    # runs — job 9657, 2026-07-18), so on timeout we clear and re-type once before
    # giving up. Mirrors the proven retry in inspect_cds_chip.py. Attempt 1 waits
    # 6s (normal items appear in ~1s), attempt 2 re-types and waits the full 12s;
    # the final timeout propagates un-wrapped so worker.py's retry gate and
    # predecessor-SKU regex still see the same locator("text=...") error text.
    step("orders", 8, 17, "search_sku", f"searching for SKU {sku}")
    _search_box = page.get_by_role("searchbox", name="Note Title")
    # waits for the SKU to appear in search results
    step("orders", 9, 17, "wait_sku_result", f"waiting for SKU {sku} in results")
    for _attempt in (1, 2):
        _search_box.fill("")
        page.wait_for_timeout(300)
        _search_box.fill(sku)
        try:
            page.locator(f"text={sku}").first.wait_for(timeout=6000 if _attempt == 1 else 12000)
            break
        except PlaywrightTimeoutError:
            if _attempt == 2:
                raise
            print(f"[orders] SKU {sku} not in results after attempt {_attempt} — re-typing search")
    page.wait_for_timeout(500)

    # check for no-CDS chip before attempting to add (CDS orders only). MK changed
    # the chip from <img src=...noCdsChip> to a styled '.cds-chip' badge (2026-07-15,
    # which silently broke the old selector and failed Wendy's whole order). This is
    # the fast, specific signal; the disabled-button check below is the real,
    # markup-independent backstop.
    if fulfillment_method == "cds":
        step("orders", 10, 17, "check_cds_eligibility", f"checking no-CDS chip for SKU {sku}")
        no_cds = page.locator('.cds-chip, img[alt*="CDS" i]')
        if no_cds.count() > 0:
            raise SkuNotCdsEligible(f"SKU {sku} is not currently available for CDS orders (expired or out of stock).")

    # Add to Bag. A DISABLED 'Add to Bag' button = the item can't be added (no-CDS,
    # out of stock, discontinued) regardless of chip markup — the robust signal
    # (Brian's insight 2026-07-15). Poll briefly for it to enable (normal items
    # enable in ~1s); if it stays disabled, skip this item rather than blocking on
    # .click()'s 30s actionability timeout, which failed the entire order.
    step("orders", 11, 17, "add_to_bag", f"clicking 'Add to Bag' for SKU {sku}")
    _add_btn = page.get_by_role("button", name="Add to Bag").first
    _add_btn.wait_for(timeout=12000)
    _enabled = False
    for _ in range(10):  # up to ~5s
        if not _add_btn.is_disabled():
            _enabled = True
            break
        page.wait_for_timeout(500)
    if not _enabled:
        raise SkuNotCdsEligible(
            f"SKU {sku} could not be added — 'Add to Bag' stayed disabled "
            "(not currently available for CDS, or out of stock)."
        )
    _add_btn.click()
    # small wait to ensure the item is added to the bag before proceeding
    page.wait_for_timeout(300)

# def finalize_order(page: Page) -> None:
    #save and review order, then confirm delivery status change
#    page.get_by_role("button", name="Save and Review").click()
#    page.wait_for_timeout(3000)

#    page.get_by_role("button", name="Change Delivery Status Icon").click()
#    page.wait_for_timeout(1000)

#    page.get_by_role("button", name="Yes, Confirm").click()
#    ensure_orders_ready(page)

def _lwc_fill(page: Page, locator, value: str) -> None:
    """
    Fill a Lightning Web Component number input in a way that triggers
    framework event listeners (click to focus + select-all, then real
    keystrokes). NOTE: Locator has no triple_click() in our Playwright —
    the original version of this helper had never actually run; caught by
    test_discount_fill.py 2026-07-18. press_sequentially sends true key
    events, which LWC inputs need (fill() alone can skip their listeners).
    """
    locator.wait_for(state="visible", timeout=5000)
    locator.click(click_count=3)  # triple-click selects any existing value
    locator.press_sequentially(value, delay=50)
    page.wait_for_timeout(200)


def fill_discount_fields(page: Page, discount_amount: float = 0.0, tax_percent: float = 0.0) -> list[str]:
    """
    Fills the Discount ($) and Sales Tax (%) fields on the order entry screen.
    Field map verified live 2026-07-18 (inspect_discount_fields.py):
      input[name='discount']   — $ amount (the $/% dropdown DEFAULTS to $; chat
                                 converts % discounts to $ so we never touch it)
      input[name='taxPercent'] — PERCENT rate (fixed % prefix, MK computes the $)
      input[name='shipping'] / input[name='otherCharges'] — NOT used (V1 skips)
    Fields render only after at least one item is in the bag.

    Returns a list of human labels that FAILED to fill ("discount", "sales tax")
    so the worker can surface them in status_msg — a silently dropped discount
    is the 2026-07-13 bug class this feature exists to kill. Failures do NOT
    abort the order: it still saves at the un-modified price.
    """
    failed: list[str] = []
    if discount_amount > 0 or tax_percent > 0:
        step("orders", 12, 17, "fill_discount_tax",
             f"filling discount ${discount_amount:.2f}" + (f" / tax {tax_percent:g}%" if tax_percent > 0 else ""))

    if discount_amount > 0:
        try:
            _lwc_fill(page, page.locator("input[name='discount']").first, f"{discount_amount:.2f}")
        except Exception as e:
            print(f"[Orders] Could not fill discount field: {e}")
            failed.append("discount")

    if tax_percent > 0:
        try:
            _lwc_fill(page, page.locator("input[name='taxPercent']").first, f"{tax_percent:g}")
        except Exception as e:
            print(f"[Orders] Could not fill sales tax field: {e}")
            failed.append("sales tax")

    return failed


def _read_intouch_error(page: Page) -> str:
    try:
        text = page.locator('.slds-notify.slds-theme_error').first.inner_text()
        lines = [l.strip() for l in text.split('\n')
                 if l.strip() and l.strip().lower() not in ('error', 'close')]
        return ' '.join(lines)
    except Exception:
        return "Unknown InTouch error"


def fill_cds_address(page: Page, street: str, city: str, state: str, postal_code: str, first_name: str = "", last_name: str = "") -> None:
    from mk_chat_core import normalize_state
    state = normalize_state(state)
    page.wait_for_timeout(1500)
    step("orders.cds_address", 1, 5, "open_address_dialog", "clicking 'Add New Address' (up to 4 attempts)")
    add_address_btn = page.get_by_role("button", name="Add New Address").first
    first_name_field = page.locator('[id^="AddressFirstName-"]')
    for _ in range(4):
        add_address_btn.scroll_into_view_if_needed()
        add_address_btn.click()
        page.wait_for_timeout(700)
        try:
            first_name_field.wait_for(state="visible", timeout=1000)
            break
        except PlaywrightTimeoutError:
            pass
    else:
        raise RuntimeError("CDS address dialog failed to open after 4 attempts.")

    step("orders.cds_address", 2, 5, "fill_address_fields", "filling name/street/city/postal fields")
    first_name_field.fill(first_name)
    page.wait_for_timeout(100)
    page.locator('[id^="AddressLastName-"]').fill(last_name)
    page.wait_for_timeout(100)
    page.locator('[id^="Street-"]').fill(street)
    page.wait_for_timeout(100)
    page.locator('[id^="City-"]').fill(city)
    page.wait_for_timeout(100)
    page.locator('[id^="PostalCode-"]').fill(postal_code)
    page.wait_for_timeout(100)

    step("orders.cds_address", 3, 5, "select_state", f"selecting state '{state}' from dropdown")
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)
    dialog.get_by_role("option", name=state, exact=True).click()
    page.wait_for_timeout(700)

    step("orders.cds_address", 4, 5, "submit_address_dialog", "clicking dialog 'Add New Address'")
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    step("orders.cds_address", 5, 5, "wait_dialog_closed", "waiting for address dialog to close")
    try:
        first_name_field.wait_for(state="hidden", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1000)
    print(f"[Orders] CDS address filled: {street}, {city}, {state} {postal_code}")


def finalize_order(page: Page, leave_pending: bool = False, discount_amount: float = 0.0, tax_percent: float = 0.0, cds_address: dict | None = None) -> list[str]:
    """Returns fill_discount_fields' failed-field labels ([] = all good) so the
    worker can flag un-applied discount/tax in the consultant's status_msg."""
    # Fill discount/tax fields before saving (chat sends $ discount + % tax rate)
    fill_failures: list[str] = []
    if discount_amount > 0 or tax_percent > 0:
        fill_failures = fill_discount_fields(page, discount_amount=discount_amount, tax_percent=tax_percent)

    # save and review order
    step("orders", 13, 17, "click_save_and_review", "clicking 'Save and Review'")
    page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Save and Review").click()
    print(f"[Orders] Save and Review clicked")

    if leave_pending:
        # Wait for success (order-details URL) or any InTouch error toast
        step("orders", 14, 17, "wait_order_outcome", "waiting for order-details URL or InTouch error toast")
        page.wait_for_function(
            "() => window.location.href.includes('order-details') || "
            "document.body.innerText.toLowerCase().includes('error')",
            timeout=20000
        )
        if "order-details" in page.url:
            return fill_failures

        # An error toast appeared — read it
        intouch_error = _read_intouch_error(page)

        # CDS address error — try filling from payload if available
        if "address" in intouch_error.lower():
            if not cds_address or not cds_address.get("street"):
                raise RuntimeError(f"InTouch: {intouch_error}")
            print(f"[Orders] CDS address error — filling address and retrying")
            fill_cds_address(
                page,
                street=cds_address["street"],
                city=cds_address.get("city", ""),
                state=cds_address.get("state", ""),
                postal_code=cds_address.get("postal_code", ""),
                first_name=cds_address.get("first_name", ""),
                last_name=cds_address.get("last_name", ""),
            )
            # Wait for any dialog/modal to fully disappear before clicking Save and Review
            try:
                page.locator('[role="dialog"]').wait_for(state="hidden", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(500)
            step("orders", 13, 17, "click_save_and_review", "clicking 'Save and Review' (retry after CDS address fill)")
            page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=15000)
            page.get_by_role("button", name="Save and Review").click()
            print(f"[Orders] Save and Review clicked (retry after address fill)")
            step("orders", 14, 17, "wait_order_outcome", "waiting for order-details URL (retry after CDS address fill)")
            page.wait_for_function("() => window.location.href.includes('order-details')", timeout=20000)
            return fill_failures

        raise RuntimeError(f"InTouch: {intouch_error}")

    # Process order: confirm delivery status change
    # Retry once — InTouch can be slow to render this button after Save and Review
    step("orders", 15, 17, "change_to_processed", "waiting for + clicking 'Change To Processed'")
    try:
        page.get_by_role("button", name="Change To Processed").wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        if page.locator('.slds-notify.slds-theme_error').is_visible():
            raise RuntimeError(f"InTouch: {_read_intouch_error(page)}")
        page.wait_for_timeout(3000)
        page.get_by_role("button", name="Change To Processed").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Change To Processed").click()
    print(f"[Orders] Change To Processed clicked")
    step("orders", 16, 17, "yes_confirm", "waiting for + clicking 'Yes, Confirm'")
    page.get_by_role("button", name="Yes, Confirm").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Yes, Confirm").click()
    step("orders", 17, 17, "post_confirm_ready", "waiting for orders page ready after confirm")
    try:
        ensure_orders_ready(page)
    except RuntimeError as e:
        if "Timeout" in str(e):
            raise RuntimeError("Timeout: Post-confirm — order was already placed")
        raise
    print(f"[Orders] Order complete")
    return fill_failures

def process_order_batch(page: Page, rows: list[dict]) -> list[str]:
    """
    Processes a batch of order rows for ONE customer.
    Each row must contain: First Name, Last Name, SKU
    Optional: fulfillment_method ("inventory" or "cds"), leave_pending (bool);
    rows[0] may carry order-level discount_amount ($) and tax_percent (%).
    Returns finalize_order's failed-fill labels ([] = discount/tax all applied).
    """
    if not rows:
        return []

    first = rows[0]["First Name"].strip()
    last = rows[0]["Last Name"].strip()
    fulfillment_method = rows[0].get("fulfillment_method", "inventory")
    leave_pending = bool(rows[0].get("leave_pending", False))
    order_date = rows[0].get("order_date") or None
    discount_amount = float(rows[0].get("discount_amount") or 0)
    tax_percent = float(rows[0].get("tax_percent") or 0)

    print(f"[Orders] Starting batch: {first} {last} — {len(rows)} SKU(s)")
    open_customer_and_start_order(page, first, last, fulfillment_method, order_date=order_date)
    print(f"[Orders] Order page open: {first} {last}")

    skipped_skus = []
    for row in rows:
        sku = row["SKU"].strip()
        try:
            add_sku_to_bag(page, sku, fulfillment_method=fulfillment_method)
            print(f"[Orders] SKU added: {sku}")
        except SkuNotCdsEligible as e:
            skipped_skus.append(str(e))

    cds_address = None
    if fulfillment_method == "cds" and rows[0].get("street"):
        cds_address = {
            "first_name": rows[0].get("First Name", ""),
            "last_name": rows[0].get("Last Name", ""),
            "street": rows[0].get("street", ""),
            "city": rows[0].get("city", ""),
            "state": rows[0].get("state", ""),
            "postal_code": rows[0].get("postal_code", ""),
        }
    fill_failures = finalize_order(page, leave_pending=leave_pending, discount_amount=discount_amount, tax_percent=tax_percent, cds_address=cds_address)

    if skipped_skus:
        raise SkuNotCdsEligible("\n".join(skipped_skus))
    return fill_failures or []
