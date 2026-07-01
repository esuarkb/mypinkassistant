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
  - Unmatched customers: stored in guest_orders (not consultant-accessible).
"""
import csv
import json
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
    Tries intouch_account_id match first (primary column then secondary array),
    falls back to exact name match.
    MyCustomers is the source of truth — no new records are created here.
    """
    PH = "?" if _is_sqlite(cur) else "%s"
    if intouch_account_id:
        # Primary column
        cur.execute(
            f"SELECT id FROM customers WHERE consultant_id = {PH} AND intouch_account_id = {PH} LIMIT 1",
            (consultant_id, intouch_account_id),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] if not isinstance(row, dict) else row["id"])
        # Secondary array — catches duplicate InTouch records merged under one MPA customer
        if _is_sqlite(cur):
            cur.execute(
                f"""SELECT c.id FROM customers c, json_each(c.intouch_account_ids) je
                    WHERE c.consultant_id = {PH} AND je.value = {PH} LIMIT 1""",
                (consultant_id, intouch_account_id),
            )
        else:
            cur.execute(
                f"""SELECT id FROM customers
                    WHERE consultant_id = {PH}
                      AND COALESCE(intouch_account_ids, '[]')::jsonb @> jsonb_build_array({PH}::text)
                    LIMIT 1""",
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


def _guest_order_already_stored(cur, consultant_id: int, intouch_order_id: str) -> bool:
    PH = "?" if _is_sqlite(cur) else "%s"
    cur.execute(
        f"SELECT 1 FROM guest_orders WHERE consultant_id = {PH} AND intouch_order_id = {PH} LIMIT 1",
        (consultant_id, intouch_order_id),
    )
    return cur.fetchone() is not None


def _insert_guest_order(cur, consultant_id: int, intouch_order_id: str,
                        intouch_account_id: str | None, first: str, last: str,
                        order_date: str, total: float, source: str, fulfillment: str,
                        items: list, billing_addr: dict | None, mailing_addr: dict | None) -> None:
    is_sq = _is_sqlite(cur)
    PH = "?" if is_sq else "%s"
    now_expr = "datetime('now')" if is_sq else "NOW()"
    cur.execute(
        f"""INSERT INTO guest_orders
            (consultant_id, intouch_order_id, intouch_account_id, first_name, last_name,
             order_date, total, source, fulfillment,
             items_json, billing_address_json, mailing_address_json, created_at)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{now_expr})
            ON CONFLICT (consultant_id, intouch_order_id) DO NOTHING""",
        (consultant_id, intouch_order_id, intouch_account_id, first, last,
         order_date, total, source, fulfillment,
         json.dumps(items), json.dumps(billing_addr), json.dumps(mailing_addr)),
    )


def _order_already_imported(cur, consultant_id: int, intouch_order_id: str) -> int | None:
    """Returns internal order_id if already imported, else None."""
    PH = "?" if _is_sqlite(cur) else "%s"
    cur.execute(
        f"SELECT id FROM orders WHERE consultant_id = {PH} AND intouch_order_id = {PH} LIMIT 1",
        (consultant_id, intouch_order_id),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


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


def _insert_item_with_qty(cur, order_id: int, sku: str, name: str, unit_price: float, quantity: int) -> None:
    is_sq = _is_sqlite(cur)
    if is_sq:
        cur.execute(
            """INSERT INTO order_items
               (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
               VALUES (?,?,?,?,?, 0, datetime('now'))""",
            (order_id, sku, name, unit_price, quantity),
        )
    else:
        cur.execute(
            """INSERT INTO order_items
               (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
               VALUES (%s,%s,%s,%s,%s, 0, NOW())""",
            (order_id, sku, name, unit_price, quantity),
        )


def import_order_history(cur, consultant_id: int, raw_orders: list[dict]) -> dict:
    """
    Processes raw API orders and inserts into DB.
    Returns a summary dict with counts.
    """
    catalog = _load_catalog()

    # Remove chat-placed orders before re-importing from MyCustomers (source of truth).
    # Chat orders have no intouch_order_id, so the duplicate check can't catch them —
    # they'd accumulate a second record every sync. Deleting them first lets the import
    # re-insert them with their real intouch_order_id.
    PH = "?" if _is_sqlite(cur) else "%s"
    cur.execute(
        f"DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id = {PH} AND source = 'chat')",
        (consultant_id,),
    )
    cur.execute(
        f"DELETE FROM orders WHERE consultant_id = {PH} AND source = 'chat'",
        (consultant_id,),
    )

    inserted = 0
    skipped_archived = 0
    skipped_duplicate = 0
    skipped_no_items = 0
    skipped_no_name = 0
    skipped_no_match = 0
    skipped_no_id = 0
    recent_duplicates = 0
    items_updated = 0
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

        # Already imported — check if within 7 days and items changed
        existing_order_id = _order_already_imported(cur, consultant_id, intouch_order_id)
        if existing_order_id is not None:
            skipped_duplicate += 1
            raw_date = (order.get("OrderedDate_f__c") or order.get("OrderedDate") or "")[:10]
            if raw_date:
                from datetime import date as _date, timedelta
                try:
                    if _date.fromisoformat(raw_date) >= _date.today() - timedelta(days=7):
                        recent_duplicates += 1
                        # Surgical item sync: compare incoming items to DB items
                        incoming_items = order.get("OrderItemSummaries") or []
                        incoming_names = sorted(
                            (_match_product((item.get("Product2") or {}).get("Name", ""), catalog) or {}).get("product_name")
                            or (item.get("Product2") or {}).get("Name", "").strip()
                            for item in incoming_items
                            if (item.get("Product2") or {}).get("Name", "").strip()
                        )
                        PH = "?" if _is_sqlite(cur) else "%s"
                        cur.execute(
                            f"SELECT product_name FROM order_items WHERE order_id = {PH} ORDER BY product_name",
                            (existing_order_id,),
                        )
                        existing_names = sorted(r[0] for r in cur.fetchall())
                        if incoming_names != existing_names:
                            cur.execute(f"DELETE FROM order_items WHERE order_id = {PH}", (existing_order_id,))
                            new_total = float(order.get("GrandTotalAmount") or 0)
                            cur.execute(f"UPDATE orders SET total = {PH} WHERE id = {PH}", (new_total, existing_order_id))
                            for item in incoming_items:
                                prod = item.get("Product2") or {}
                                prod_name = (prod.get("Name") or "").strip()
                                if not prod_name:
                                    continue
                                catalog_row = _match_product(prod_name, catalog)
                                if catalog_row:
                                    sku = catalog_row["sku"]
                                    name = catalog_row["product_name"]
                                    unit_price = float(catalog_row.get("price") or 0)
                                else:
                                    sku = ""
                                    name = prod_name
                                    unit_price = 0.0
                                _insert_item(cur, existing_order_id, sku, name, unit_price)
                            items_updated += 1
                            print(f"[ImportOrderHistory] surgical update: {raw_date} order_id={existing_order_id} "
                                  f"was={existing_names} now={incoming_names}")
                except Exception as _e:
                    print(f"[ImportOrderHistory] surgical update error for {intouch_order_id}: {_e}")
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

        # Order date — use consultant-entered date (OrderedDate_f__c), fall back to OrderedDate
        raw_date = order.get("OrderedDate_f__c") or order.get("OrderedDate") or ""
        order_date = raw_date[:10] if raw_date else datetime.now(timezone.utc).date().isoformat()

        total = float(order.get("GrandTotalAmount") or 0)

        if customer_id is None:
            skipped_no_match += 1
            if not _guest_order_already_stored(cur, consultant_id, intouch_order_id):
                _insert_guest_order(
                    cur, consultant_id, intouch_order_id, intouch_account_id,
                    first, last, order_date, total,
                    (order.get("OrderSource_p__c") or "").strip(),
                    (order.get("FulfillmentMethod_p__c") or "").strip(),
                    order.get("OrderItemSummaries") or [],
                    acct.get("PersonMailingAddress"),
                    order.get("BillingAddress"),
                )
            continue

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
          f"dupes={skipped_duplicate} recent_dupes={recent_duplicates} items_updated={items_updated} "
          f"no_items={skipped_no_items} no_id={skipped_no_id} no_name={skipped_no_name} no_match={skipped_no_match}")

    # Merge local_only items (discontinued SKUs sold from personal inventory) into
    # their matching intouch_import order by consultant + customer + date.
    try:
        cur.execute(
            f"SELECT id, customer_id, DATE(order_date) FROM orders WHERE consultant_id = {PH} AND source = 'local_only'",
            (consultant_id,),
        )
        _local_orders = cur.fetchall()
        _merged = 0
        for _lo_id, _lo_cust_id, _lo_date in _local_orders:
            cur.execute(
                f"""SELECT id FROM orders
                    WHERE consultant_id = {PH}
                      AND customer_id = {PH}
                      AND DATE(order_date) = {PH}
                      AND source = 'intouch_import'
                    LIMIT 1""",
                (consultant_id, _lo_cust_id, _lo_date),
            )
            _match = cur.fetchone()
            if _match:
                _target_id = int(_match[0])
                cur.execute(
                    f"UPDATE order_items SET order_id = {PH} WHERE order_id = {PH}",
                    (_target_id, _lo_id),
                )
                cur.execute(f"DELETE FROM orders WHERE id = {PH}", (_lo_id,))
                _merged += 1
                print(f"[ImportOrderHistory] merged local_only order {_lo_id} → intouch_import order {_target_id}")
        if _merged:
            print(f"[ImportOrderHistory] merged {_merged} local_only order(s) into intouch_import")
    except Exception as _merge_err:
        print(f"[ImportOrderHistory] local_only merge error (non-fatal): {_merge_err}")

    return {
        "inserted": inserted,
        "skipped_archived": skipped_archived,
        "skipped_duplicate": skipped_duplicate,
        "skipped_no_items": skipped_no_items,
        "unmatched_products": list(set(unmatched_products)),
    }


def update_order_item_quantities(
    cur, consultant_id: int, order_details_map: dict[str, list[dict]],
    catalog: list[dict] | None = None,
) -> dict:
    """
    For each order in order_details_map: delete existing order_items,
    re-insert with real quantities from the InTouch detail API.
    Updates order total from productAmount sum.
    Works for SQLite and Postgres (uses PH placeholder).
    """
    if catalog is None:
        catalog = _load_catalog()

    PH = "?" if _is_sqlite(cur) else "%s"
    updated = 0
    skipped_no_order = 0

    for intouch_order_id, product_details in order_details_map.items():
        if not product_details:
            continue

        cur.execute(
            f"SELECT id FROM orders WHERE consultant_id = {PH} AND intouch_order_id = {PH} LIMIT 1",
            (consultant_id, intouch_order_id),
        )
        row = cur.fetchone()
        if not row:
            skipped_no_order += 1
            continue

        order_id = int(row[0] if not isinstance(row, dict) else row["id"])

        cur.execute(f"DELETE FROM order_items WHERE order_id = {PH}", (order_id,))

        new_total = 0.0
        for item in product_details:
            prod_name = (item.get("productName") or "").strip()
            if not prod_name:
                continue

            try:
                qty = max(1, int(item.get("productQuantity") or 1))
            except Exception:
                qty = 1

            try:
                unit_price = float(item.get("productUnitPrice") or 0)
            except Exception:
                unit_price = 0.0

            try:
                product_amount = float(item.get("productAmount") or 0)
            except Exception:
                product_amount = unit_price * qty

            new_total += product_amount

            catalog_row = _match_product(prod_name, catalog)
            if catalog_row:
                sku = catalog_row["sku"]
                name = catalog_row["product_name"]
                if unit_price == 0.0:
                    try:
                        unit_price = float(catalog_row.get("price") or 0)
                    except Exception:
                        pass
            else:
                sku = (item.get("productSKU") or "").strip()
                name = prod_name

            _insert_item_with_qty(cur, order_id, sku, name, unit_price, qty)

        if new_total > 0:
            cur.execute(
                f"UPDATE orders SET total = {PH} WHERE id = {PH}",
                (new_total, order_id),
            )

        updated += 1

    print(f"[OrderDetailSync] quantity update: updated={updated} skipped_no_order={skipped_no_order}")
    return {"updated": updated, "skipped_no_order": skipped_no_order}
