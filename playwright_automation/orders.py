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
        raise RuntimeError("Orders not ready: 'New Order' button not found.")


def open_customer_list(page: Page) -> None:
    """
    Navigates to the customer list used for order placement.
    """
    page.goto(CUSTOMER_LIST_URL)
    ensure_orders_ready(page)


# -------------------------
# Order helpers
# -------------------------
def open_customer_and_start_order(page: Page, first: str, last: str, fulfillment_method: str = "inventory") -> None:
    """
    Opens a customer and starts a new order.
    fulfillment_method: "inventory" (default) or "cds"
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

def add_sku_to_bag(page: Page, sku: str) -> None:
    # search for SKU and wait for results to populate
    page.get_by_role("searchbox", name="Note Title").fill(sku)
    # waits for the SKU to appear in search results
    page.locator(f"text={sku}").first.wait_for(timeout=8000)

    # click Add to Bag and give the UI a brief moment to update
    # waits for the Add to Bag button to be enabled for the SKU
    page.get_by_role("button", name="Add to Bag").wait_for(timeout=8000)
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

    open_customer_and_start_order(page, first, last, fulfillment_method)

    for row in rows:
        sku = row["SKU"].strip()
        add_sku_to_bag(page, sku)

    finalize_order(page, leave_pending=leave_pending)
