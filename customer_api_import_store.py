# customer_api_import_store.py
"""
Processes raw customer data from the InTouch customer-list API and upserts
into the local DB.

Matching strategy (in order):
  1. intouch_account_id (Salesforce Account ID) — most reliable
  2. email + exact first/last name
  3. exact first/last name only

Source status:
  - archived=True in InTouch  →  source_status='removed'
  - archived=False             →  source_status='active'

Phone comes from personMobilePhone (omitted from response when empty).
COALESCE preserves an existing phone if the API returns none for a customer.
Tags are stored as a JSON array string; existing tags are preserved if the
API returns no tags for that customer.
"""
import json


def _is_sqlite(cur) -> bool:
    return "sqlite" in type(cur).__module__.lower()


def _ph(cur) -> str:
    return "?" if _is_sqlite(cur) else "%s"


def _now(cur) -> str:
    return "datetime('now')" if _is_sqlite(cur) else "NOW()"


def _row_int(row) -> int | None:
    if not row:
        return None
    try:
        return int(row["id"] if isinstance(row, dict) else row[0])
    except Exception:
        return None


def _find_by_intouch_id(cur, consultant_id: int, intouch_account_id: str) -> int | None:
    PH = _ph(cur)
    cur.execute(
        f"SELECT id FROM customers WHERE consultant_id = {PH} AND intouch_account_id = {PH} LIMIT 1",
        (consultant_id, intouch_account_id),
    )
    return _row_int(cur.fetchone())


def _find_by_email_name(cur, consultant_id: int, email: str, first: str, last: str) -> int | None:
    PH = _ph(cur)
    cur.execute(
        f"""SELECT id FROM customers
            WHERE consultant_id = {PH}
              AND LOWER(email) = LOWER({PH})
              AND LOWER(first_name) = LOWER({PH})
              AND LOWER(last_name) = LOWER({PH})
            ORDER BY id DESC LIMIT 1""",
        (consultant_id, email, first, last),
    )
    return _row_int(cur.fetchone())


def _find_by_name(cur, consultant_id: int, first: str, last: str) -> int | None:
    PH = _ph(cur)
    cur.execute(
        f"""SELECT id FROM customers
            WHERE consultant_id = {PH}
              AND LOWER(first_name) = LOWER({PH})
              AND LOWER(last_name) = LOWER({PH})
            ORDER BY id DESC LIMIT 1""",
        (consultant_id, first, last),
    )
    return _row_int(cur.fetchone())


def import_customers_from_api(cur, consultant_id: int, raw_customers: list[dict]) -> dict:
    """
    Upserts customer data from the InTouch customer-list API into the DB.
    Returns a summary dict with counts.
    """
    inserted = 0
    updated = 0
    skipped = 0
    removed = 0
    seen_ids: set[int] = set()

    print(f"[CustomerApiImport] processing {len(raw_customers)} records for consultant {consultant_id}")

    for c in raw_customers:
        first = (c.get("firstName") or "").strip()
        last = (c.get("lastName") or "").strip()
        if not first and not last:
            skipped += 1
            continue

        intouch_account_id = (c.get("id") or "").strip() or None
        email = (c.get("personEmail") or "").strip().lower() or None
        phone = (c.get("personMobilePhone") or "").strip() or None
        street = (c.get("personMailingStreet") or "").strip() or None
        street2 = (c.get("personMailingStreet2") or "").strip() or None
        city = (c.get("personMailingCity") or "").strip() or None
        state = (c.get("personMailingState") or "").strip() or None
        postal_code = (c.get("personMailingPostalCode") or "").strip() or None
        birthday = (c.get("birthday") or "").strip() or None
        tags_raw = c.get("tags")
        tags = json.dumps(tags_raw) if isinstance(tags_raw, list) else None
        source_status = "removed" if c.get("archived") else "active"

        PH = _ph(cur)
        NOW = _now(cur)

        existing_id = None
        if intouch_account_id:
            existing_id = _find_by_intouch_id(cur, consultant_id, intouch_account_id)
        if existing_id is None and email:
            existing_id = _find_by_email_name(cur, consultant_id, email, first, last)
        if existing_id is None:
            existing_id = _find_by_name(cur, consultant_id, first, last)

        if existing_id is not None:
            cur.execute(
                f"""UPDATE customers
                    SET first_name          = {PH},
                        last_name           = {PH},
                        email               = COALESCE({PH}, email),
                        phone               = COALESCE({PH}, phone),
                        street              = COALESCE({PH}, street),
                        street2             = COALESCE({PH}, street2),
                        city                = COALESCE({PH}, city),
                        state               = COALESCE({PH}, state),
                        postal_code         = COALESCE({PH}, postal_code),
                        birthday            = COALESCE({PH}, birthday),
                        tags                = COALESCE({PH}, tags),
                        intouch_account_id  = COALESCE({PH}, intouch_account_id),
                        source_status       = {PH},
                        updated_at          = {NOW}
                    WHERE id = {PH} AND consultant_id = {PH}""",
                (
                    first, last, email, phone, street, street2, city, state,
                    postal_code, birthday, tags, intouch_account_id,
                    source_status, existing_id, consultant_id,
                ),
            )
            updated += 1
            seen_ids.add(existing_id)
        else:
            if _is_sqlite(cur):
                cur.execute(
                    f"""INSERT INTO customers
                        (consultant_id, first_name, last_name, email, phone, street, street2,
                         city, state, postal_code, birthday, notes, tags,
                         intouch_account_id, is_order_ready, missing_order_fields,
                         source_status, created_at, updated_at)
                        VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},
                                '',{PH},{PH}, 1, '[]', {PH}, {NOW}, {NOW})""",
                    (consultant_id, first, last, email, phone, street, street2,
                     city, state, postal_code, birthday, tags,
                     intouch_account_id, source_status),
                )
                try:
                    seen_ids.add(int(cur.lastrowid))
                except Exception:
                    pass
            else:
                cur.execute(
                    f"""INSERT INTO customers
                        (consultant_id, first_name, last_name, email, phone, street, street2,
                         city, state, postal_code, birthday, notes, tags,
                         intouch_account_id, is_order_ready, missing_order_fields,
                         source_status, created_at, updated_at)
                        VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},
                                '',{PH},{PH}, 1, '[]', {PH}, {NOW}, {NOW})
                        RETURNING id""",
                    (consultant_id, first, last, email, phone, street, street2,
                     city, state, postal_code, birthday, tags,
                     intouch_account_id, source_status),
                )
                row = cur.fetchone()
                try:
                    seen_ids.add(int(row[0] if not isinstance(row, dict) else row["id"]))
                except Exception:
                    pass
            inserted += 1

    # Mark customers not seen in this import as removed.
    # Guard: only run if the API returned data — an empty response means
    # something went wrong (outage, site change) and we must not touch existing records.
    if raw_customers and seen_ids:
        PH = _ph(cur)
        NOW = _now(cur)
        placeholders = ", ".join([PH] * len(seen_ids))
        cur.execute(
            f"""UPDATE customers
                SET source_status = 'removed', updated_at = {NOW}
                WHERE consultant_id = {PH}
                  AND id NOT IN ({placeholders})
                  AND source_status <> 'removed'""",
            [consultant_id] + list(seen_ids),
        )
        removed = cur.rowcount or 0

    print(
        f"[CustomerApiImport] done: inserted={inserted} updated={updated} "
        f"skipped={skipped} removed={removed}"
    )
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "removed": removed, "total": len(raw_customers)}
