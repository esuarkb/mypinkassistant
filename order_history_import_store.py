# order_history_import_store.py
"""
Processes raw order data from the InTouch getOrdersExistingTags API and
inserts it into the local DB.

Matching strategy:
  - Customer: exact first+last name match against customers table;
    creates a minimal record if not found.
  - Product: normalize name (strip ®, ™, †) → exact catalog match;
    fuzzy fallback (token_set_ratio >= 80) if needed.
  - Unit price: catalog price if matched, else 0 (API doesn't expose per-item prices).
  - Quantity: always 1 (API doesn't expose per-item quantity).
  - Deduplication: skips orders where intouch_order_id already exists in DB.
  - Skips archived orders.
"""
import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process


_CATALOG_PATH = Path(__file__).parent / "catalog" / "en.csv"
_catalog_cache: list[dict] | None = None


def _load_catalog() -> list[dict]:
    global _catalog_cache
    if _catalog_cache is None:
        with open(_CATALOG_PATH, newline="", encoding="utf-8") as f:
            _catalog_cache = list(csv.DictReader(f))
    return _catalog_cache


def _normalize_name(name: str) -> str:
    """Same rules as update_catalog.py — strip ®, ™, †."""
    return re.sub(r"[®™®™†]", "", name).strip().lower()


def _match_product(prod_name: str, catalog: list[dict]) -> dict | None:
    """
    Returns catalog row dict on match, or None.
    Tries exact normalized match first, then fuzzy (token_set_ratio >= 80).
    """
    if not prod_name:
        return None
    target = _normalize_name(prod_name)
    # Exact
    for row in catalog:
        if _normalize_name(row["product_name"]) == target:
            return row
    # Fuzzy
    names = [_normalize_name(r["product_name"]) for r in catalog]
    results = process.extract(target, names, scorer=fuzz.token_set_ratio, limit=2)
    if results and results[0][1] >= 80:
        best_score, best_idx = results[0][1], results[0][2]
        if len(results) < 2 or (best_score - results[1][1]) >= 10:
            return catalog[best_idx]
    return None


def _is_sqlite(cur) -> bool:
    return "sqlite" in type(cur).__module__.lower()


def _find_customer(
    cur, consultant_id: int, first: str, last: str,
    intouch_account_id: str | None = None,
) -> int | None:
    """
    Returns customer_id if found (including removed customers), or None.
    Tries intouch_account_id match first, falls back to exact name match.
    MyCustomers is the source of truth — no new records are created here.
    """
    PH = "?" if _is_sqlite(cur) else "%s"
    if intouch_account_id:
        cur.execute(
            f"SELECT id FROM customers WHERE consultant_id = {PH} AND intouch_account_id = {PH} LIMIT 1",
            (consultant_id, intouch_account_id),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] if not isinstance(row, dict) else row["id"])
    cur.execute(
        f"""SELECT id FROM customers
            WHERE consultant_id = {PH}
              AND LOWER(first_name) = LOWER({PH})
              AND LOWER(last_name) = LOWER({PH})
            ORDER BY id DESC LIMIT 1""",
        (consultant_id, first, last),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _order_already_imported(cur, consultant_id: int, intouch_order_id: str) -> bool:
    PH = "?" if _is_sqlite(cur) else "%s"
    cur.execute(
        f"SELECT 1 FROM orders WHERE consultant_id = {PH} AND intouch_order_id = {PH} LIMIT 1",
        (consultant_id, intouch_order_id),
    )
    return cur.fetchone() is not None


def _insert_order(cur, consultant_id: int, customer_id: int, order_date: str,
                  total: float, intouch_order_id: str, source: str = "intouch_import") -> int:
    is_sq = _is_sqlite(cur)
    PH = "?" if is_sq else "%s"
    if is_sq:
        cur.execute(
            f"""INSERT INTO orders
               (consultant_id, customer_id, order_date, total, source, intouch_order_id,
                discount_amount, tax_amount, created_at)
               VALUES ({PH},{PH},{PH},{PH},{PH},{PH}, 0, 0, datetime('now'))""",
            (consultant_id, customer_id, order_date, total, source, intouch_order_id),
        )
        return int(cur.lastrowid)
    else:
        cur.execute(
            f"""INSERT INTO orders
               (consultant_id, customer_id, order_date, total, source, intouch_order_id,
                discount_amount, tax_amount, created_at)
               VALUES ({PH},{PH},{PH},{PH},{PH},{PH}, 0, 0, NOW())
               RETURNING id""",
            (consultant_id, customer_id, order_date, total, source, intouch_order_id),
        )
        return int(cur.fetchone()[0])


def _insert_item(cur, order_id: int, sku: str, name: str, unit_price: float) -> None:
    is_sq = _is_sqlite(cur)
    if is_sq:
        cur.execute(
            """INSERT INTO order_items
               (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
               VALUES (?,?,?,?, 1, 0, datetime('now'))""",
            (order_id, sku, name, unit_price),
        )
    else:
        cur.execute(
            """INSERT INTO order_items
               (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
               VALUES (%s,%s,%s,%s, 1, 0, NOW())""",
            (order_id, sku, name, unit_price),
        )


def import_order_history(cur, consultant_id: int, raw_orders: list[dict]) -> dict:
    """
    Processes raw API orders and inserts into DB.
    Returns a summary dict with counts.
    """
    catalog = _load_catalog()

    inserted = 0
    skipped_archived = 0
    skipped_duplicate = 0
    skipped_no_items = 0
    skipped_no_name = 0
    skipped_no_match = 0
    skipped_no_id = 0
    unmatched_products: list[str] = []

    print(f"[ImportOrderHistory] processing {len(raw_orders)} raw orders for consultant {consultant_id}")

    for order in raw_orders:
        # Skip archived
        if order.get("IsArchived_cb__c"):
            skipped_archived += 1
            continue

        intouch_order_id = order.get("Id", "")
        if not intouch_order_id:
            skipped_no_id += 1
            continue

        # Skip already imported
        if _order_already_imported(cur, consultant_id, intouch_order_id):
            skipped_duplicate += 1
            continue

        # Customer
        acct = order.get("CustomerAccount_lr__r") or {}
        first = (acct.get("FirstName") or "").strip()
        last = (acct.get("LastName") or "").strip()
        if not first and not last:
            skipped_no_name += 1
            continue
        intouch_account_id = (acct.get("Id") or "").strip() or None
        customer_id = _find_customer(cur, consultant_id, first, last, intouch_account_id)
        if customer_id is None:
            skipped_no_match += 1
            continue

        # Order date — use consultant-entered date (OrderedDate_f__c), fall back to OrderedDate
        raw_date = order.get("OrderedDate_f__c") or order.get("OrderedDate") or ""
        order_date = raw_date[:10] if raw_date else datetime.now(timezone.utc).date().isoformat()

        total = float(order.get("GrandTotalAmount") or 0)

        fulfillment = (order.get("FulfillmentMethod_p__c") or "").strip()
        order_source = (order.get("OrderSource_p__c") or "").strip()
        if order_source == "Online" and fulfillment == "CDS":
            source = "myshop"
        elif fulfillment == "CDS":
            source = "cds"
        else:
            source = "intouch_import"

        # Items
        items = order.get("OrderItemSummaries") or []
        if not items:
            skipped_no_items += 1
            continue

        order_id = _insert_order(cur, consultant_id, customer_id, order_date, total, intouch_order_id, source)

        for item in items:
            prod = item.get("Product2") or {}
            prod_name = (prod.get("Name") or "").strip()
            if not prod_name:
                continue

            catalog_row = _match_product(prod_name, catalog)
            if catalog_row:
                sku = catalog_row["sku"]
                name = catalog_row["product_name"]
                try:
                    unit_price = float(catalog_row["price"] or 0)
                except Exception:
                    unit_price = 0.0
            else:
                sku = ""
                name = prod_name
                unit_price = 0.0
                unmatched_products.append(prod_name)

            _insert_item(cur, order_id, sku, name, unit_price)

        inserted += 1

    print(f"[ImportOrderHistory] done: inserted={inserted} archived={skipped_archived} "
          f"dupes={skipped_duplicate} no_items={skipped_no_items} "
          f"no_id={skipped_no_id} no_name={skipped_no_name} no_match={skipped_no_match}")

    return {
        "inserted": inserted,
        "skipped_archived": skipped_archived,
        "skipped_duplicate": skipped_duplicate,
        "skipped_no_items": skipped_no_items,
        "unmatched_products": list(set(unmatched_products)),
    }
