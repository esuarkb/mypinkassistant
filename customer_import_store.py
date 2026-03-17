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

    Works with both SQLite and Postgres.
    Returns summary counts.
    """
    inserted = 0
    updated = 0
    skipped = 0

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

        # 3) Update existing exact match
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
            continue

        # 4) Insert new
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
                created_at,
                updated_at
            )
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {NOW_SQL}, {NOW_SQL})
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
        inserted += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": len(rows),
    }