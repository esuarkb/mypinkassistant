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

def finalize_order(page: Page, leave_pending: bool = False) -> None:
    # save and review order
    page.get_by_role("button", name="Save and Review").click()

    if leave_pending:
        # Leave order in pending state — do not change delivery status
        page.wait_for_timeout(1500)
        return

    # Process order: confirm delivery status change
    page.get_by_role("button", name="Change Delivery Status Icon").click()
    page.get_by_role("button", name="Yes, Confirm").click()
    ensure_orders_ready(page)

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

    open_customer_and_start_order(page, first, last, fulfillment_method, order_date=order_date)

    skipped_skus = []
    for row in rows:
        sku = row["SKU"].strip()
        try:
            add_sku_to_bag(page, sku, fulfillment_method=fulfillment_method)
        except SkuNotCdsEligible as e:
            skipped_skus.append(str(e))

    finalize_order(page, leave_pending=leave_pending)

    if skipped_skus:
        raise SkuNotCdsEligible("\n".join(skipped_skus))
