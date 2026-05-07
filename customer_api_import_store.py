# customer_api_import_store.py
"""
Processes raw customer data from the InTouch customer-list API and upserts
into the local DB.

Matching strategy (in order):
  1. intouch_account_id — checks primary column AND the intouch_account_ids
     JSON array (most reliable, built up from previous syncs)
  2. email + exact first/last name  (high confidence)
  3. exact first/last name only     (low confidence — does NOT update intouch_account_ids)

Active-wins rule:
  Active InTouch records are processed before archived ones (sorted active-first).
  If an archived record maps to an MPA customer already confirmed active in this
  sync, only the secondary intouch_account_id is stored — status, contact info,
  and primary account ID are not overwritten.

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


def _find_by_any_intouch_id(cur, consultant_id: int, intouch_account_id: str) -> int | None:
    """Check the primary intouch_account_id column, then the intouch_account_ids JSON array."""
    PH = _ph(cur)
    cur.execute(
        f"SELECT id FROM customers WHERE consultant_id = {PH} AND intouch_account_id = {PH} LIMIT 1",
        (consultant_id, intouch_account_id),
    )
    row = cur.fetchone()
    if row:
        return _row_int(row)
    # Check secondary IDs array accumulated from previous syncs.
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


def _add_intouch_id(cur, customer_id: int, new_id: str, consultant_id: int) -> None:
    """Append new_id to the customer's intouch_account_ids JSON array if not already present."""
    PH = _ph(cur)
    cur.execute(
        f"SELECT intouch_account_id, intouch_account_ids FROM customers WHERE id = {PH} AND consultant_id = {PH}",
        (customer_id, consultant_id),
    )
    row = cur.fetchone()
    if not row:
        return
    primary = row["intouch_account_id"] if isinstance(row, dict) else row[0]
    ids_json = row["intouch_account_ids"] if isinstance(row, dict) else row[1]
    if new_id == primary:
        return
    try:
        ids = json.loads(ids_json or "[]")
    except Exception:
        ids = []
    if new_id in ids:
        return
    ids.append(new_id)
    cur.execute(
        f"UPDATE customers SET intouch_account_ids = {PH} WHERE id = {PH} AND consultant_id = {PH}",
        (json.dumps(ids), customer_id, consultant_id),
    )


def import_customers_from_api(cur, consultant_id: int, raw_customers: list[dict]) -> dict:
    """
    Upserts customer data from the InTouch customer-list API into the DB.
    Returns a summary dict with counts.
    """
    # Process active records before archived so the active-wins logic can detect
    # archived duplicates that map to customers already confirmed active this sync.
    raw_customers = sorted(raw_customers, key=lambda c: c.get("archived", False))

    inserted = 0
    updated = 0
    skipped = 0
    removed = 0
    seen_ids: set[int] = set()
    active_mpa_ids: set[int] = set()  # MPA IDs confirmed active in this sync pass

    print(f"[CustomerApiImport] processing {len(raw_customers)} records for consultant {consultant_id}")

    for c in raw_customers:
        first = (c.get("firstName") or "").strip()
        last = (c.get("lastName") or "").strip()
        if not first and not last:
            skipped += 1
            continue

        archived = bool(c.get("archived"))
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
        source_status = "removed" if archived else "active"

        PH = _ph(cur)
        NOW = _now(cur)

        # Locate existing MPA customer. Track confidence to guard intouch_account_ids updates.
        existing_id = None
        confidence = "none"

        if intouch_account_id:
            existing_id = _find_by_any_intouch_id(cur, consultant_id, intouch_account_id)
            if existing_id is not None:
                confidence = "high"
        if existing_id is None and email:
            existing_id = _find_by_email_name(cur, consultant_id, email, first, last)
            if existing_id is not None:
                confidence = "high"
        if existing_id is None:
            existing_id = _find_by_name(cur, consultant_id, first, last)
            if existing_id is not None:
                confidence = "name_only"

        if existing_id is not None:
            # Active-wins: if this archived InTouch record maps to a customer already confirmed
            # active this sync, only record the secondary account ID — never downgrade status.
            if archived and existing_id in active_mpa_ids:
                if confidence == "high" and intouch_account_id:
                    _add_intouch_id(cur, existing_id, intouch_account_id, consultant_id)
                # Active record already owns seen_ids — no further action needed.
                continue

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
            if not archived:
                active_mpa_ids.add(existing_id)
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
                    new_id = int(cur.lastrowid)
                    seen_ids.add(new_id)
                    if not archived:
                        active_mpa_ids.add(new_id)
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
                    new_id = int(row[0] if not isinstance(row, dict) else row["id"])
                    seen_ids.add(new_id)
                    if not archived:
                        active_mpa_ids.add(new_id)
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
