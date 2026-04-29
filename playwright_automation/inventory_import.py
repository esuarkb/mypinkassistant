# playwright_automation/inventory_import.py
#
# Scrapes the consultant's Cosmetic orders from the InTouch order history
# and adds the ordered quantities to their personal inventory.
#
# Designed to run nightly via the IMPORT_INVENTORY_ORDERS job type.
# Tracks imported order numbers so nothing is ever double-imported.

from __future__ import annotations

import re
from typing import List, Dict

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

ORDER_SITE_BASE = "https://order.marykayintouch.com"

# orderType param that corresponds to "Cosmetic only" in the UI filter.
# This is the exact value the browser sends when all types except Cosmetic
# are deselected (determined by inspecting the Network tab).
ORDER_TYPE_COSMETIC = (
    "1%2C4%2C5%2C10%2C13%2C14%2C15%2C18%2C19%2C20"
    "%2C22%2C23%2C24%2C25%2C26%2C28%2C29%2C30%2C31%2C32"
)


def _order_history_url(date_range: str = "days90") -> str:
    return (
        f"{ORDER_SITE_BASE}/orders?lang=en_US"
        f"&placedFor=yourself"
        f"&orderDate={date_range}"
        f"&orderType={ORDER_TYPE_COSMETIC}"
    )


def login_order_site(page: Page, username: str, password: str) -> None:
    """
    Navigate to the InTouch order site and log in if needed.
    The order site uses the same consultant number + password as MyCustomers.
    """
    page.goto(_order_history_url(), wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # If redirected to a login page, fill credentials
    try:
        num_field = page.get_by_role("textbox", name="Consultant Number")
        num_field.wait_for(state="visible", timeout=4000)
        num_field.fill(username)
        page.get_by_role("textbox", name="Password").fill(password)
        page.wait_for_timeout(200)
        page.get_by_text("Log In").click()
        page.wait_for_timeout(3000)
    except PlaywrightTimeoutError:
        # No login form — already authenticated (cookies shared with MyCustomers session)
        pass


def fetch_cosmetic_order_links(
    page: Page, date_range: str = "days90"
) -> List[Dict[str, str]]:
    """
    Navigate to the Cosmetic-filtered order history and return a list of dicts:
      {
        "order_no":          "06638356",
        "href":              "/orderdetails?...",
        "order_type":        "Cosmetic",          # from list row
        "consumer_order_id": "",                  # UUID if shipped to customer, else ""
      }

    order_type and consumer_order_id are read directly from the list row so
    the caller can skip customer (CDS / online shop) orders without visiting
    the detail page.
    """
    url = _order_history_url(date_range)
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector("a", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    return page.evaluate("""
        () => {
            // Build a header-name → column-index map from the visible header row.
            const headers = [];
            document.querySelectorAll('.order-list-header .order-list-col').forEach(col => {
                headers.push(col.textContent.trim().replace(/\\.$/, ''));
            });

            const results = [];
            document.querySelectorAll('.order-list-item').forEach(row => {
                // Find the 8-digit order link
                let orderNo = null, href = null;
                row.querySelectorAll('a').forEach(a => {
                    const t = (a.textContent || '').trim();
                    if (/^\\d{8}$/.test(t) && (a.getAttribute('href') || '').includes('orderdetails')) {
                        orderNo = t;
                        href = a.getAttribute('href');
                    }
                });
                if (!orderNo) return;

                // Read column values in DOM order
                const colVals = [];
                row.querySelectorAll('.order-list-col').forEach(col => {
                    colVals.push(col.textContent.trim());
                });

                // Map header label → value
                const data = {};
                headers.forEach((h, i) => { if (h) data[h] = (colVals[i] || '').trim(); });

                results.push({
                    order_no: orderNo,
                    href: href,
                    order_type: data['Order Type'] || '',
                    consumer_order_id: data['Consumer Order'] || '',
                });
            });

            return results;
        }
    """)


def _read_detail_labels(page: Page) -> Dict[str, str]:
    """
    Read all label→value pairs from the order detail overview section.
    Uses JS to walk nextElementSibling from each title to its paired value,
    which is robust to flat DOM layouts where titles and values are siblings.
    Returns a dict like {"Order Type": "Cosmetic", "Order Source": "Online", ...}
    """
    try:
        return page.evaluate("""
            () => {
                const result = {};
                document.querySelectorAll('.details-col-title').forEach(title => {
                    const key = title.textContent.trim().replace(/:$/, '');
                    if (!key) return;
                    let sib = title.nextElementSibling;
                    while (sib) {
                        if (sib.classList.contains('details-col-value')) {
                            result[key] = sib.textContent.trim();
                            break;
                        }
                        sib = sib.nextElementSibling;
                    }
                });
                return result;
            }
        """)
    except Exception:
        return {}


def scrape_order_detail(page: Page, href: str) -> Dict:
    """
    Navigate to an order detail page and return:
      - order_type:   "Cosmetic" / "No Charge" / etc.
      - order_source: "Online" / "CDS" / "Phone" / etc.
      - items:        list of {"sku": "...", "qty": int}
    """
    if href.startswith("/"):
        href = ORDER_SITE_BASE + href

    page.goto(href, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    labels = _read_detail_labels(page)
    order_type = labels.get("Order Type", "").strip()
    order_source = labels.get("Order Source", "").strip()

    print(f"[Inventory] detail labels: {labels}")

    # Collect line items — each has data-sku and data-quantity attributes.
    # InTouch renders each item twice: once in the visible product list and once
    # in a hidden reorder panel. The hidden duplicates have empty inner_text().
    # We skip them to avoid doubling every quantity.
    items = []
    for el in page.locator("div.order-product-line-item").all():
        try:
            sku = (el.get_attribute("data-sku") or "").strip()
            qty_str = (el.get_attribute("data-quantity") or "0").strip()
            if sku and el.inner_text().strip():
                items.append({"sku": sku, "qty": max(0, int(qty_str or 0))})
        except Exception:
            continue

    return {"order_type": order_type, "order_source": order_source, "items": items}


def import_inventory_orders(
    page: Page,
    consultant_id: int,
    username: str,
    password: str,
    date_range: str = "days90",
    seed_only: bool = False,
) -> Dict:
    """
    Main entry point called by the worker.

    Normal mode (seed_only=False):
      1. Logs into the InTouch order site.
      2. Fetches the Cosmetic-filtered order list.
      3. For each order not yet imported:
         a. Scrapes the detail page for SKUs + quantities.
         b. Skips if Order Type != Cosmetic or Order Source == CDS.
         c. Adds quantities to the consultant's inventory.
         d. Records the order number as imported.
      4. Returns a summary dict.

    Seed mode (seed_only=True, run once at signup):
      Finds the most recent eligible Cosmetic order and marks it as imported
      WITHOUT adding any SKUs. This sets the watermark so nightly imports
      only pick up orders placed after the consultant joined.
    """
    # Deferred imports to avoid circular dependency in module-level imports
    from db import connect, is_postgres
    from inventory_store import upsert_inventory_quantity
    from inventory_import_store import is_order_imported, mark_order_imported

    login_order_site(page, username, password)

    order_links = fetch_cosmetic_order_links(page, date_range)

    imported_orders = []
    skipped_orders = []
    sku_totals: Dict[str, int] = {}

    # ── Seed mode: mark ALL orders in the window as seen, no SKUs imported ──
    if seed_only:
        for link in order_links:
            order_no = link["order_no"]
            if is_order_imported(consultant_id, order_no):
                print(f"[Inventory][seed] {order_no} already marked — skipping")
                continue
            mark_order_imported(
                consultant_id, order_no,
                order_type=link.get("order_type", ""),
                consumer_order_id=link.get("consumer_order_id", ""),
            )
            print(f"[Inventory][seed] watermark: {order_no}")
        return {"imported": [], "skipped": [], "sku_totals": {}, "seed_only": True}

    # ── Normal nightly import ──
    for link in order_links:
        order_no = link["order_no"]
        list_order_type = link.get("order_type", "")
        consumer_order_id = link.get("consumer_order_id", "")

        if is_order_imported(consultant_id, order_no):
            skipped_orders.append(order_no)
            continue

        # If the list row shows a Consumer Order UUID, this order shipped to a
        # customer — skip without visiting the detail page.
        if consumer_order_id:
            print(f"[Inventory] skipping {order_no} — customer order (consumer_id={consumer_order_id[:8]}...)")
            skipped_orders.append(order_no)
            mark_order_imported(
                consultant_id, order_no,
                order_type=list_order_type,
                consumer_order_id=consumer_order_id,
            )
            continue

        detail = scrape_order_detail(page, link["href"])

        # Belt-and-suspenders: verify type and source from the detail page too
        order_type = detail["order_type"].lower()
        order_source = detail["order_source"].lower()

        print(f"[Inventory] order={order_no} list_type={list_order_type!r} detail_type={detail['order_type']!r} source={detail['order_source']!r}")

        if order_type != "cosmetic":
            print(f"[Inventory] skipping {order_no} — not Cosmetic ({detail['order_type']!r})")
            skipped_orders.append(order_no)
            mark_order_imported(
                consultant_id, order_no,
                order_type=detail["order_type"],
                consumer_order_id=consumer_order_id,
            )
            continue

        if order_source == "cds":
            print(f"[Inventory] skipping {order_no} — CDS order (ships to customer, not inventory)")
            skipped_orders.append(order_no)
            mark_order_imported(
                consultant_id, order_no,
                order_type=detail["order_type"],
                consumer_order_id=consumer_order_id,
            )
            continue

        for item in detail["items"]:
            sku = item["sku"]
            qty = item["qty"]
            sku_totals[sku] = sku_totals.get(sku, 0) + qty

        imported_orders.append(order_no)
        mark_order_imported(
            consultant_id, order_no,
            order_type=detail["order_type"],
            consumer_order_id=consumer_order_id,
        )

    # Apply inventory additions for all new orders in one transaction
    if sku_totals:
        conn = connect()
        try:
            cur = conn.cursor()
            for sku, qty in sku_totals.items():
                upsert_inventory_quantity(
                    cur,
                    consultant_id=consultant_id,
                    sku=sku,
                    qty_delta=qty,
                )
            conn.commit()
        finally:
            conn.close()

    return {
        "imported": imported_orders,
        "skipped": skipped_orders,
        "sku_totals": sku_totals,
    }
