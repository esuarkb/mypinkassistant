from __future__ import annotations

from typing import Optional

from db import connect, is_postgres

PH = "%s" if is_postgres() else "?"


def upsert_inventory_quantity(
    cur,
    *,
    consultant_id: int,
    sku: str,
    qty_delta: int = 0,
    set_qty: Optional[int] = None,
    low_stock_threshold: Optional[int] = None,
) -> None:
    """
    Insert or update one inventory row for a consultant + SKU.

    Rules:
    - If row does not exist, create it.
    - If set_qty is provided, qty_on_hand becomes set_qty.
    - Otherwise qty_on_hand changes by qty_delta.
    - low_stock_threshold is only updated if explicitly provided.
    - qty_on_hand will never go below 0.
    """
    sku = (sku or "").strip()
    if not sku:
        raise ValueError("SKU is required")

    if set_qty is not None and set_qty < 0:
        raise ValueError("set_qty cannot be negative")

    if low_stock_threshold is not None and low_stock_threshold < 0:
        raise ValueError("low_stock_threshold cannot be negative")

    cur.execute(
        f"""
        SELECT id, qty_on_hand, low_stock_threshold
        FROM inventory
        WHERE consultant_id = {PH} AND sku = {PH}
        LIMIT 1
        """,
        (int(consultant_id), sku),
    )
    row = cur.fetchone()

    if isinstance(row, dict):
        inv_id = row.get("id")
        current_qty = int(row.get("qty_on_hand") or 0)
        current_threshold = row.get("low_stock_threshold")
    elif row:
        inv_id = row[0]
        current_qty = int(row[1] or 0)
        current_threshold = row[2]
    else:
        inv_id = None
        current_qty = 0
        current_threshold = None

    if set_qty is not None:
        new_qty = int(set_qty)
    else:
        new_qty = current_qty + int(qty_delta)

    if new_qty < 0:
        new_qty = 0

    new_threshold = current_threshold
    if low_stock_threshold is not None:
        new_threshold = int(low_stock_threshold)

    if inv_id is None:
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO inventory (
                    consultant_id,
                    sku,
                    qty_on_hand,
                    low_stock_threshold,
                    created_at,
                    updated_at
                )
                VALUES ({PH}, {PH}, {PH}, {PH}, NOW(), NOW())
                """,
                (
                    int(consultant_id),
                    sku,
                    int(new_qty),
                    new_threshold,
                ),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO inventory (
                    consultant_id,
                    sku,
                    qty_on_hand,
                    low_stock_threshold,
                    created_at,
                    updated_at
                )
                VALUES ({PH}, {PH}, {PH}, {PH}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    int(consultant_id),
                    sku,
                    int(new_qty),
                    new_threshold,
                ),
            )
        return

    if is_postgres():
        cur.execute(
            f"""
            UPDATE inventory
            SET qty_on_hand = {PH},
                low_stock_threshold = {PH},
                updated_at = NOW()
            WHERE id = {PH}
            """,
            (
                int(new_qty),
                new_threshold,
                int(inv_id),
            ),
        )
    else:
        cur.execute(
            f"""
            UPDATE inventory
            SET qty_on_hand = {PH},
                low_stock_threshold = {PH},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {PH}
            """,
            (
                int(new_qty),
                new_threshold,
                int(inv_id),
            ),
        )
        
def get_inventory_item(cur, *, consultant_id: int, sku: str) -> Optional[dict]:
    cur.execute(
        f"""
        SELECT sku, qty_on_hand, low_stock_threshold
        FROM inventory
        WHERE consultant_id = {PH} AND sku = {PH}
        LIMIT 1
        """,
        (int(consultant_id), sku),
    )
    row = cur.fetchone()

    if not row:
        return None

    if isinstance(row, dict):
        return row

    return {
        "sku": row[0],
        "qty_on_hand": row[1],
        "low_stock_threshold": row[2],
    }


def list_low_stock(cur, *, consultant_id: int) -> list[dict]:
    """
    Returns inventory rows where qty_on_hand < low_stock_threshold.
    Only includes items where a threshold has been set.
    """
    cur.execute(
        f"""
        SELECT sku, qty_on_hand, low_stock_threshold
        FROM inventory
        WHERE consultant_id = {PH}
          AND low_stock_threshold IS NOT NULL
          AND qty_on_hand < low_stock_threshold
        ORDER BY (low_stock_threshold - qty_on_hand) DESC
        """,
        (int(consultant_id),),
    )
    rows = cur.fetchall() or []

    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append({
                "sku": r[0],
                "qty_on_hand": r[1],
                "low_stock_threshold": r[2],
            })

    return out


def has_any_thresholds(cur, *, consultant_id: int) -> bool:
    """Returns True if the consultant has set at least one low_stock_threshold."""
    cur.execute(
        f"""
        SELECT 1 FROM inventory
        WHERE consultant_id = {PH}
          AND low_stock_threshold IS NOT NULL
        LIMIT 1
        """,
        (int(consultant_id),),
    )
    return cur.fetchone() is not None


def list_inventory(cur, *, consultant_id: int) -> list[dict]:
    cur.execute(
        f"""
        SELECT sku, qty_on_hand, low_stock_threshold
        FROM inventory
        WHERE consultant_id = {PH}
        ORDER BY sku
        """,
        (int(consultant_id),),
    )
    rows = cur.fetchall() or []

    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append({
                "sku": r[0],
                "qty_on_hand": r[1],
                "low_stock_threshold": r[2],
            })

    return out