# playwright_automation/orders.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


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
    open_customer_list(page)
    page.wait_for_timeout(3000)

    # Search customer, small wait for search results to populate
    page.get_by_role("searchbox", name="Note Title").fill(full_name)
    page.wait_for_timeout(500)

    # Existence check (duplicate-safe)
    try:
        page.get_by_text(full_name).first.wait_for(timeout=3000)
    except PlaywrightTimeoutError:
        raise RuntimeError(
            f"Customer not found: '{full_name}'. "
            "Make sure they have been added to MyCustomers and please try again."
        )

    # Select customer from search results (first match if duplicates), loads customer page
    page.get_by_text(full_name).first.click()
    page.wait_for_timeout(1000)

    # Click New Order Button and load order page
    page.get_by_role("button", name="Add Order").click()
    page.wait_for_timeout(3000)

    # Set order date if provided (field is pre-filled with today — only override if specified)
    if order_date:
        try:
            date_input = page.locator("input[id^='order-date']").first
            date_input.wait_for(state="visible", timeout=5000)
            date_input.fill(order_date)
            page.wait_for_timeout(300)
        except PlaywrightTimeoutError:
            pass  # date field not found — proceed with today's date

    # Select fulfillment method
    if fulfillment_method == "cds":
        page.get_by_text("Customer Delivery Service").click()
    else:
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
    # search for SKU and wait for results to populate
    page.get_by_role("searchbox", name="Note Title").fill(sku)
    # waits for the SKU to appear in search results
    page.locator(f"text={sku}").first.wait_for(timeout=12000)
    page.wait_for_timeout(500)

    # check for no-CDS chip before attempting to add (CDS orders only)
    if fulfillment_method == "cds":
        no_cds = page.locator('img[src*="noCdsChip"]')
        if no_cds.count() > 0:
            raise SkuNotCdsEligible(f"SKU {sku} is not available for CDS orders (expired or out of stock).")

    # click Add to Bag and give the UI a brief moment to update
    # waits for the Add to Bag button to be enabled for the SKU
    page.get_by_role("button", name="Add to Bag").wait_for(timeout=12000)
    # click the Add to Bag button for the SKU
    page.get_by_role("button", name="Add to Bag").click()
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
    framework event listeners (triple-click to select, then type the value).
    """
    locator.wait_for(state="visible", timeout=5000)
    locator.triple_click()
    locator.type(value, delay=50)
    page.wait_for_timeout(200)


def fill_discount_fields(page: Page, discount_amount: float = 0.0, tax_amount: float = 0.0) -> None:
    """
    Fills the discount and shipping/tax fields on the order entry screen.
    Only called when discount_amount > 0. Fields only appear after at least one item
    has been added to the bag.
    """
    if discount_amount > 0:
        try:
            _lwc_fill(page, page.locator("input[name='discount']").first, f"{discount_amount:.2f}")
        except Exception as e:
            print(f"[Orders] Could not fill discount field: {e}")

    if tax_amount > 0:
        try:
            _lwc_fill(page, page.locator("input[name='shipping']").first, f"{tax_amount:.2f}")
        except Exception as e:
            print(f"[Orders] Could not fill shipping/tax field: {e}")


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

    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)
    dialog.get_by_role("option", name=state, exact=True).click()
    page.wait_for_timeout(700)

    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    try:
        first_name_field.wait_for(state="hidden", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1000)
    print(f"[Orders] CDS address filled: {street}, {city}, {state} {postal_code}")


def finalize_order(page: Page, leave_pending: bool = False, discount_amount: float = 0.0, tax_amount: float = 0.0, cds_address: dict | None = None) -> None:
    # Fill discount/tax fields before saving (only if a discount was applied)
    if discount_amount > 0:
        fill_discount_fields(page, discount_amount=discount_amount, tax_amount=tax_amount)

    # save and review order
    page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Save and Review").click()
    print(f"[Orders] Save and Review clicked")

    if leave_pending:
        # Wait for success (order-details URL) or any InTouch error toast
        page.wait_for_function(
            "() => window.location.href.includes('order-details') || "
            "document.body.innerText.toLowerCase().includes('error')",
            timeout=20000
        )
        if "order-details" in page.url:
            return

        # An error toast appeared — read it
        intouch_error = _read_intouch_error(page)

        # CDS address error — try filling from payload if available
        if "delivery address" in intouch_error.lower():
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
            page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=15000)
            page.get_by_role("button", name="Save and Review").click()
            print(f"[Orders] Save and Review clicked (retry after address fill)")
            page.wait_for_function("() => window.location.href.includes('order-details')", timeout=20000)
            return

        raise RuntimeError(f"InTouch: {intouch_error}")

    # Process order: confirm delivery status change
    # Retry once — InTouch can be slow to render this button after Save and Review
    try:
        page.get_by_role("button", name="Change To Processed").wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        if page.locator('.slds-notify.slds-theme_error').is_visible():
            raise RuntimeError(f"InTouch: {_read_intouch_error(page)}")
        page.wait_for_timeout(3000)
        page.get_by_role("button", name="Change To Processed").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Change To Processed").click()
    print(f"[Orders] Change To Processed clicked")
    page.get_by_role("button", name="Yes, Confirm").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Yes, Confirm").click()
    try:
        ensure_orders_ready(page)
    except RuntimeError as e:
        if "Timeout" in str(e):
            raise RuntimeError("Timeout: Post-confirm — order was already placed")
        raise
    print(f"[Orders] Order complete")

def process_order_batch(page: Page, rows: list[dict]) -> None:
    """
    Processes a batch of order rows for ONE customer.
    Each row must contain: First Name, Last Name, SKU
    Optional: fulfillment_method ("inventory" or "cds"), leave_pending (bool)
    """
    if not rows:
        return

    first = rows[0]["First Name"].strip()
    last = rows[0]["Last Name"].strip()
    fulfillment_method = rows[0].get("fulfillment_method", "inventory")
    leave_pending = bool(rows[0].get("leave_pending", False))
    order_date = rows[0].get("order_date") or None
    discount_amount = float(rows[0].get("discount_amount") or 0)
    tax_amount = float(rows[0].get("tax_amount") or 0)

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
    finalize_order(page, leave_pending=leave_pending, discount_amount=discount_amount, tax_amount=tax_amount, cds_address=cds_address)

    if skipped_skus:
        raise SkuNotCdsEligible("\n".join(skipped_skus))
