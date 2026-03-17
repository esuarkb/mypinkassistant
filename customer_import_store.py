import json
from typing import Dict, Any, List

from db import is_postgres


PH = "%s" if is_postgres() else "?"
NOW_SQL = "NOW()" if is_postgres() else "datetime('now')"


def _row_id(row) -> int | None:
    if not row:
        return None
    try:
        if isinstance(row, dict):
            v = row.get("id")
            return int(v) if v is not None else None
    except Exception:
        pass
    try:
        return int(row[0])
    except Exception:
        return None


def import_customers_from_rows(cur, consultant_id: int, rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Import parsed customer rows into local DB.

    Match rule:
      1) phone + exact first/last name
      2) email + exact first/last name
      3) otherwise insert new

    Source-of-truth rule:
      - all imported customers are marked active
      - previously known customers not seen in this import are marked removed

    Works with both SQLite and Postgres.
    Returns summary counts.
    """
    inserted = 0
    updated = 0
    skipped = 0
    removed = 0

    seen_ids: set[int] = set()

    for r in rows:
        first_name = (r.get("first_name") or "").strip()
        last_name = (r.get("last_name") or "").strip()
        email = (r.get("email") or "").strip().lower() or None
        phone = (r.get("phone") or "").strip() or None
        street = (r.get("street") or "").strip() or None
        city = (r.get("city") or "").strip() or None
        state = (r.get("state") or "").strip() or None
        postal_code = (r.get("postal_code") or "").strip() or None
        birthday = (r.get("birthday") or "").strip() or None
        is_order_ready = 1 if r.get("is_order_ready") else 0
        missing_order_fields = json.dumps(r.get("missing_order_fields") or [])

        if not first_name and not last_name:
            skipped += 1
            continue

        existing_id = None

        # 1) Match by phone + exact name
        if phone:
            cur.execute(
                f"""
                SELECT id
                FROM customers
                WHERE consultant_id = {PH}
                  AND phone = {PH}
                  AND LOWER(first_name) = LOWER({PH})
                  AND LOWER(last_name) = LOWER({PH})
                LIMIT 1
                """,
                (consultant_id, phone, first_name, last_name),
            )
            existing_id = _row_id(cur.fetchone())

        # 2) Match by email + exact name
        if existing_id is None and email:
            cur.execute(
                f"""
                SELECT id
                FROM customers
                WHERE consultant_id = {PH}
                  AND LOWER(email) = LOWER({PH})
                  AND LOWER(first_name) = LOWER({PH})
                  AND LOWER(last_name) = LOWER({PH})
                LIMIT 1
                """,
                (consultant_id, email, first_name, last_name),
            )
            existing_id = _row_id(cur.fetchone())

        # 3) Fallback: exact full-name match
        if existing_id is None:
            cur.execute(
                f"""
                SELECT id
                FROM customers
                WHERE consultant_id = {PH}
                  AND LOWER(first_name) = LOWER({PH})
                  AND LOWER(last_name) = LOWER({PH})
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (consultant_id, first_name, last_name),
            )
            row = cur.fetchone()

            if row:
                existing_id = int(row[0])

        # 4) Update existing exact match
        if existing_id is not None:
            cur.execute(
                f"""
                UPDATE customers
                SET email = {PH},
                    phone = {PH},
                    street = {PH},
                    city = {PH},
                    state = {PH},
                    postal_code = {PH},
                    birthday = {PH},
                    is_order_ready = {PH},
                    missing_order_fields = {PH},
                    source_status = 'active',
                    updated_at = {NOW_SQL}
                WHERE id = {PH}
                  AND consultant_id = {PH}
                """,
                (
                    email,
                    phone,
                    street,
                    city,
                    state,
                    postal_code,
                    birthday,
                    is_order_ready,
                    missing_order_fields,
                    existing_id,
                    consultant_id,
                ),
            )
            updated += 1
            seen_ids.add(existing_id)
            continue

        # 5) Insert new
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO customers (
                    consultant_id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    street,
                    city,
                    state,
                    postal_code,
                    birthday,
                    notes,
                    is_order_ready,
                    missing_order_fields,
                    source_status,
                    created_at,
                    updated_at
                )
                VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, 'active', {NOW_SQL}, {NOW_SQL})
                RETURNING id
                """,
                (
                    consultant_id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    street,
                    city,
                    state,
                    postal_code,
                    birthday,
                    "",
                    is_order_ready,
                    missing_order_fields,
                ),
            )
            new_id = _row_id(cur.fetchone())
        else:
            cur.execute(
                f"""
                INSERT INTO customers (
                    consultant_id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    street,
                    city,
                    state,
                    postal_code,
                    birthday,
                    notes,
                    is_order_ready,
                    missing_order_fields,
                    source_status,
                    created_at,
                    updated_at
                )
                VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, 'active', {NOW_SQL}, {NOW_SQL})
                """,
                (
                    consultant_id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    street,
                    city,
                    state,
                    postal_code,
                    birthday,
                    "",
                    is_order_ready,
                    missing_order_fields,
                ),
            )
            try:
                new_id = int(cur.lastrowid)
            except Exception:
                new_id = None

        inserted += 1
        if new_id is not None:
            seen_ids.add(new_id)

    # 5) Mark unseen customers for this consultant as removed
    if seen_ids:
        placeholders = ", ".join([PH] * len(seen_ids))
        params = [consultant_id] + list(seen_ids)

        cur.execute(
            f"""
            UPDATE customers
            SET source_status = 'removed',
                updated_at = {NOW_SQL}
            WHERE consultant_id = {PH}
              AND id NOT IN ({placeholders})
              AND source_status <> 'removed'
            """,
            params,
        )
        removed = cur.rowcount or 0
    else:
        cur.execute(
            f"""
            UPDATE customers
            SET source_status = 'removed',
                updated_at = {NOW_SQL}
            WHERE consultant_id = {PH}
              AND source_status <> 'removed'
            """,
            (consultant_id,),
        )
        removed = cur.rowcount or 0

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "removed": removed,
        "total": len(rows),
    }