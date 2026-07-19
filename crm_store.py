# crm_store.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import csv
from pathlib import Path
from rapidfuzz import fuzz

# Catalog display name overrides keyed by SKU string
_CATALOG_CARD: dict = {}
def _load_catalog_display() -> None:
    path = Path(__file__).resolve().parent / "catalog" / "en.csv"
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sku  = (row.get("sku") or "").strip()
                card = (row.get("display_name_card") or "").strip()
                if sku and card:
                    _CATALOG_CARD[sku] = card
    except FileNotFoundError:
        pass
_load_catalog_display()


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _format_phone_pretty(phone: Optional[str]) -> str:
    if not phone:
        return "—"

    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    # US 10-digit format
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"

    # 7-digit fallback
    if len(digits) == 7:
        return f"{digits[0:3]}-{digits[3:7]}"

    # Otherwise return as-is
    return phone

def _is_sqlite_cursor(cur) -> bool:
    """
    Determine if we're using SQLite based on the connection type.
    This is safer than inspecting cursor module strings.
    """
    try:
        conn = cur.connection
        return conn.__class__.__module__.startswith("sqlite3")
    except Exception:
        return False


def find_customers_by_name(
    cur,
    consultant_id: int,
    name: str,
    limit: int = 10,
    include_removed: bool = False,
):
    """
    Smarter customer search:
      - "Bonnie" (single token): match first OR last
      - "Kirk C" (last initial): first startswith kirk, last startswith c
      - "Kirk Cam" (partial last): first + last partials
      - fuzzy fallback if no SQL matches ("jnae" -> "jane")

    By default, only active/source-of-truth customers are searched.
    Pass include_removed=True for admin/delete flows if needed.
    Returns list of dicts, best matches first.
    """
    q = (name or "").strip()
    parts = [p for p in q.replace(",", " ").split() if p]

    is_sqlite = _is_sqlite_cursor(cur)

    # Normalize tokens
    p1 = parts[0].strip() if len(parts) >= 1 else ""
    p2 = parts[1].strip() if len(parts) >= 2 else ""

    # Detect last-initial mode: "Kirk C" or "Kirk C."
    last_initial = ""
    if len(parts) == 2:
        cand = p2.replace(".", "").strip()
        if len(cand) == 1 and cand.isalpha():
            last_initial = cand.lower()

    # Build LIKE patterns
    p1_low = p1.lower()
    p2_low = p2.lower()

    first_starts = f"{p1_low}%"
    first_contains = f"%{p1_low}%"

    last_starts = f"{p2_low}%"
    last_contains = f"%{p2_low}%"

    single_starts = f"{p1_low}%"
    single_contains = f"%{p1_low}%"

    last_init_starts = f"{last_initial}%"

    active_clause = "" if include_removed else "AND COALESCE(source_status, 'active') = 'active'"

    # -------------------------
    # Primary SQL search
    # -------------------------
    if is_sqlite:
        if len(parts) == 1:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = ?
              {active_clause}
              AND (
                LOWER(first_name) LIKE ?
                OR LOWER(last_name) LIKE ?
              )
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE ? THEN 0 ELSE 1 END,
              CASE WHEN LOWER(last_name)  LIKE ? THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT ?
            """
            params = (consultant_id, single_contains, single_contains, single_starts, single_starts, limit)

        elif last_initial:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = ?
              {active_clause}
              AND LOWER(first_name) LIKE ?
              AND LOWER(last_name) LIKE ?
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE ? THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT ?
            """
            params = (consultant_id, first_contains, last_init_starts, first_starts, limit)

        else:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = ?
              {active_clause}
              AND LOWER(first_name) LIKE ?
              AND LOWER(last_name) LIKE ?
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE ? THEN 0 ELSE 1 END,
              CASE WHEN LOWER(last_name)  LIKE ? THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT ?
            """
            params = (consultant_id, first_contains, last_contains, first_starts, last_starts, limit)

    else:
        if len(parts) == 1:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = %s
              {active_clause}
              AND (
                LOWER(first_name) LIKE %s
                OR LOWER(last_name) LIKE %s
              )
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE %s THEN 0 ELSE 1 END,
              CASE WHEN LOWER(last_name)  LIKE %s THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT %s
            """
            params = (consultant_id, single_contains, single_contains, single_starts, single_starts, limit)

        elif last_initial:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = %s
              {active_clause}
              AND LOWER(first_name) LIKE %s
              AND LOWER(last_name) LIKE %s
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE %s THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT %s
            """
            params = (consultant_id, first_contains, last_init_starts, first_starts, limit)

        else:
            sql = f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = %s
              {active_clause}
              AND LOWER(first_name) LIKE %s
              AND LOWER(last_name) LIKE %s
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE %s THEN 0 ELSE 1 END,
              CASE WHEN LOWER(last_name)  LIKE %s THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT %s
            """
            params = (consultant_id, first_contains, last_contains, first_starts, last_starts, limit)

    cur.execute(sql, params)
    rows = _rows_to_dicts(cur)

    if rows:
        return rows

    # -------------------------
    # Fuzzy fallback
    # -------------------------
    if is_sqlite:
        cur.execute(
            f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = ?
              {active_clause}
            """,
            (consultant_id,),
        )
    else:
        cur.execute(
            f"""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes, source_status
            FROM customers
            WHERE consultant_id = %s
              {active_clause}
            """,
            (consultant_id,),
        )

    all_rows = _rows_to_dicts(cur)

    q_low = q.lower().strip()
    scored = []

    for r in all_rows:
        first = (r.get("first_name") or "").strip()
        last = (r.get("last_name") or "").strip()
        full = f"{first} {last}".strip()

        score_full = fuzz.WRatio(q_low, full.lower()) if full else 0
        score_first = fuzz.WRatio(q_low, first.lower()) if first else 0
        score_last = fuzz.WRatio(q_low, last.lower()) if last else 0

        # For multi-word queries (first + last name), score_full is primary.
        # score_first/score_last alone can inflate matches on partial comparisons
        # (e.g. "Jennifer Smith" scoring high against just "Jeannie").
        if " " in q_low:
            score = max(score_full, min(max(score_first, score_last), score_full + 5))
        else:
            score = max(score_full, score_first, score_last)

        if q_low and q_low in full.lower():
            score += 5

        # Last-initial pattern: "Kim Z" — boost if first_name contains p1 and
        # last_name starts with the initial, so it clears the 75 threshold
        # even when raw WRatio undershoots on short queries.
        if last_initial and last.lower().startswith(last_initial):
            if p1.lower() in first.lower():
                score = max(score, 80)

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [r for score, r in scored if score >= 75][:limit]


def get_pcp_enrolled(cur, consultant_id: int, customer_id: int) -> bool:
    try:
        from db import is_postgres
        PH = "%s" if is_postgres() else "?"
        cur.execute(f"""
            SELECT 1 FROM pcp_enrollments
            WHERE customer_id = {PH}
              AND consultant_id = {PH}
              AND quarter = (SELECT MAX(quarter) FROM pcp_enrollments WHERE consultant_id = {PH})
              AND enrolled = TRUE
            LIMIT 1
        """, (customer_id, consultant_id, consultant_id))
        return cur.fetchone() is not None
    except Exception:
        return False


def get_pcp_list(cur, consultant_id: int) -> tuple[list[dict], str]:
    """Return (customers, quarter) for the current PCP quarter."""
    from db import is_postgres
    PH = "%s" if is_postgres() else "?"
    cur.execute(f"""
        SELECT pe.pcp_name, pe.customer_id, pe.quarter,
               c.first_name, c.last_name, c.phone
        FROM pcp_enrollments pe
        LEFT JOIN customers c ON c.id = pe.customer_id
        WHERE pe.consultant_id = {PH}
          AND pe.enrolled = TRUE
          AND pe.quarter = (SELECT MAX(quarter) FROM pcp_enrollments WHERE consultant_id = {PH})
        ORDER BY pe.pcp_name
    """, (consultant_id, consultant_id))
    rows = _rows_to_dicts(cur)
    if not rows:
        return [], ""
    quarter = (rows[0].get("quarter") or "")
    customers = []
    for r in rows:
        first = (r.get("first_name") or "").strip()
        last  = (r.get("last_name") or "").strip()
        name  = f"{first} {last}".strip() if (first or last) else (r.get("pcp_name") or "")
        customers.append({
            "id":         r.get("customer_id"),
            "name":       name,
            "first_name": first or name.split()[0],
            "phone":      r.get("phone") or "",
        })
    return customers, quarter


def format_customer_card(c: Dict[str, Any], last_order: Dict[str, Any] | None = None, pcp_enrolled: bool = False) -> str:
    import re
    import calendar
    import html
    from urllib.parse import quote

    first = (c.get("first_name") or "").strip()
    last = (c.get("last_name") or "").strip()
    full_name = html.escape(f"{first} {last}".strip() or "Customer")

    email_raw = (c.get("email") or "").strip()
    if email_raw:
        email_val = f'<a href="mailto:{html.escape(email_raw)}">{html.escape(email_raw)}</a>'
    else:
        email_val = "(none)"

    phone_raw = (c.get("phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone_raw)
    phone_display = html.escape(_format_phone_pretty(phone_raw) or phone_raw)
    if phone_digits:
        phone_val = f'<a href="tel:{phone_digits}">{phone_display}</a>'
    else:
        phone_val = "(none)"

    street = (c.get("street") or "").strip()
    city = (c.get("city") or "").strip()
    state = (c.get("state") or "").strip()
    postal = (c.get("postal_code") or "").strip()

    addr_parts = [p for p in [street, city, state, postal] if p]
    if addr_parts:
        address_text = ", ".join(addr_parts)
        address_val = f'<a href="#" class="address-link" data-address="{html.escape(address_text)}" target="_blank">{html.escape(address_text)}</a>'
    else:
        address_val = "(none)"

    bday_raw = (c.get("birthday") or "").strip()
    birthday = "(none)"
    if bday_raw:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", bday_raw):
            y, mo, d = map(int, bday_raw.split("-"))
            if y == 2000:
                birthday = html.escape(f"{calendar.month_name[mo]} {d}")
            else:
                birthday = html.escape(f"{calendar.month_name[mo]} {d}, {y}")
        elif re.fullmatch(r"\d{2}-\d{2}", bday_raw):
            mo, d = map(int, bday_raw.split("-"))
            birthday = html.escape(f"{calendar.month_name[mo]} {d}")
        else:
            birthday = html.escape(bday_raw)

    pcp_badge = " · <span style='color:#d63384;font-size:0.85em'>PCP</span>" if pcp_enrolled else ""
    lines = [
        f"<strong>{full_name}</strong>{pcp_badge}",
        f"• Email: {email_val}",
        f"• Phone: {phone_val}",
        f"• Address: {address_val}",
        f"• Birthday: {birthday}",
    ]

    notes = (c.get("notes") or "").strip()
    if notes:
        lines.append(f"• Notes: {html.escape(notes)}")

    if last_order:
        import calendar as _cal
        order_date = (last_order.get("order_date") or "")
        if order_date:
            try:
                from datetime import date as _date
                d = _date.fromisoformat(str(order_date)[:10])
                date_str = f"{_cal.month_abbr[d.month]} {d.day}, {d.year}"
            except Exception:
                date_str = str(order_date)[:10]
        else:
            date_str = "unknown date"

        items = last_order.get("items") or []
        _spf_sunscreen_products = re.compile(r"\b(Mineral\s+Facial|Sun\s+Care)\s+Sunscreen\b", re.IGNORECASE)
        def _short(name, sku=None):
            if sku and str(sku) in _CATALOG_CARD:
                return _CATALOG_CARD[str(sku)]
            n = re.sub(r"Mary Kay[®\u00ae]?\s*", "", name, flags=re.IGNORECASE)
            n = re.sub(r"[®™\u00ae\u2122\u2020]", "", n)
            n = re.sub(r"\s+Broad\s+Spectrum\s+SPF\s*[\d]+[*]?", "", n, flags=re.IGNORECASE)
            n = re.sub(r"\s+SPF\s*[\d]+[*]?\s*$", "", n, flags=re.IGNORECASE)
            if not _spf_sunscreen_products.search(n):
                n = re.sub(r"\s+Sunscreen\b", "", n, flags=re.IGNORECASE)
            return n.strip(" .,") or name

        names = [_short(i["product_name"], i.get("sku")) for i in items]
        cmd = html.escape(f"last order for {first} {last}")
        if len(names) <= 3:
            item_str = ", ".join(html.escape(n) for n in names)
        else:
            shown = ", ".join(html.escape(n) for n in names[:2])
            extra = len(names) - 2
            item_str = f'{shown} <a href="#" data-send="{cmd}" style="white-space:nowrap;">+{extra} more</a>'

        _src = last_order.get("source") or ""
        source_label = " · Online | CDS" if _src in ("myshop", "cds") else ""
        lines.append(f"• Last order: {date_str}{source_label} · {item_str}" if item_str else f"• Last order: {date_str}{source_label}")

    return "\n".join(lines)


def format_consultant_card(m: Dict[str, Any]) -> str:
    import re
    import html

    first = (m.get("first_name") or "").strip()
    last  = (m.get("last_name")  or "").strip()
    full_name = html.escape(f"{first} {last}".strip() or "Consultant")

    num    = html.escape(m.get("consultant_number") or "")
    level  = html.escape(m.get("career_level_desc") or "")
    status = html.escape(m.get("activity_status")   or "")
    meta_parts = [p for p in [num, level, status] if p]
    meta = f" <span style='font-size:0.85em;color:#888'>· {html.escape(' · '.join(meta_parts))}</span>" if meta_parts else ""

    email_raw = (m.get("email") or "").strip()
    if email_raw:
        email_val = f'<a href="mailto:{html.escape(email_raw)}">{html.escape(email_raw)}</a>'
    else:
        email_val = "(none)"

    phone_raw = (m.get("phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone_raw)
    phone_display = html.escape(_format_phone_pretty(phone_raw) or phone_raw)
    if phone_digits:
        phone_val = f'<a href="tel:{phone_digits}">{phone_display}</a>'
    else:
        phone_val = "(none)"

    addr  = (m.get("address") or "").strip()
    city  = (m.get("city")    or "").strip()
    state = (m.get("state")   or "").strip()
    zip_  = (m.get("zip")     or "").strip()
    addr_parts = [p for p in [addr, city, state, zip_] if p]
    if addr_parts:
        address_text = ", ".join(addr_parts)
        address_val = f'<a href="#" class="address-link" data-address="{html.escape(address_text)}" target="_blank">{html.escape(address_text)}</a>'
    else:
        address_val = "(none)"

    myshop = m.get("myshop_active")
    if myshop == 1:
        myshop_val = "Yes"
    elif myshop == 0:
        myshop_val = "No"
    else:
        myshop_val = "Unknown"

    lo_date = (m.get("last_order_date") or "")[:10]
    lo_amt  = m.get("last_order_wholesale")
    if lo_date:
        try:
            from datetime import date as _date
            import calendar as _cal
            d = _date.fromisoformat(lo_date)
            lo_date_str = f"{_cal.month_abbr[d.month]} {d.day}, {d.year}"
        except Exception:
            lo_date_str = lo_date
        if lo_amt is not None:
            last_order_val = f"{lo_date_str} · ${lo_amt:,.2f} wholesale"
        else:
            last_order_val = lo_date_str
    else:
        last_order_val = "(none)"

    lines = [
        f"<strong>{full_name}</strong>{meta}",
        f"• Email: {email_val}",
        f"• Phone: {phone_val}",
        f"• Address: {address_val}",
        f"• MyShop: {myshop_val}",
        f"• Last order: {last_order_val}",
    ]
    return "\n".join(lines)


def find_unit_member_by_name(cur, consultant_id: int, name: str) -> list[Dict[str, Any]]:
    """
    Search unit_members by name. Prefers exact prefix/substring matches on first or
    last name, falls back to fuzzy only for full-name queries with a high threshold.
    """
    from rapidfuzz import process, fuzz
    _ph = "?" if _is_sqlite_cursor(cur) else "%s"
    cur.execute(
        f"SELECT * FROM unit_members WHERE consultant_id = {_ph}",
        (consultant_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return []

    name_lower = name.strip().lower()
    all_members = []
    for r in rows:
        d = dict(r) if hasattr(r, "keys") else dict(zip([c[0] for c in cur.description], r))
        all_members.append(d)

    # Tier 1: exact substring match on first_name, last_name, or full name
    tier1 = [
        d for d in all_members
        if name_lower in (d.get("first_name") or "").lower()
        or name_lower in (d.get("last_name") or "").lower()
        or name_lower in f"{d.get('first_name','')} {d.get('last_name','')}".strip().lower()
    ]
    if tier1:
        return tier1[:5]

    # Tier 2: fuzzy match on full name, but only with a tight threshold
    candidates = {
        f"{d.get('first_name','')} {d.get('last_name','')}".strip(): d
        for d in all_members
    }
    results = process.extract(name, list(candidates.keys()), scorer=fuzz.WRatio, limit=3)
    return [candidates[k] for k, score, _ in results if score >= 80]


def upsert_customer_from_pending(cur, consultant_id: int, customer: Dict[str, Any]) -> int:
    """
    For now, always INSERT a new customer row.
    We are intentionally not auto-merging/updating existing customers,
    because family members may share phone numbers or email addresses.
    Returns the new customer_id.
    """

    first = (customer.get("First Name") or "").strip()
    last = (customer.get("Last Name") or "").strip()
    email = (customer.get("Email") or "").strip() or None
    phone = (customer.get("Phone") or "").strip() or None
    street = (customer.get("Street") or customer.get("Address") or "").strip() or None
    street2 = (customer.get("Street2") or "").strip() or None
    city = (customer.get("City") or "").strip() or None
    state = (customer.get("State") or "").strip() or None
    postal = (customer.get("Postal Code") or customer.get("Zip") or "").strip() or None
    birthday = (customer.get("Birthday") or "").strip() or None
    tags = (customer.get("Tags") or "").strip() or None

    is_sqlite = _is_sqlite_cursor(cur)

    if is_sqlite:
        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, street2, city, state, postal_code, birthday, tags, created_at, updated_at)
            VALUES
              (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'), datetime('now'))
        """, (consultant_id, first, last, email, phone, street, street2, city, state, postal, birthday, tags))
        return int(cur.lastrowid)

    cur.execute("""
        INSERT INTO customers
          (consultant_id, first_name, last_name, email, phone, street, street2, city, state, postal_code, birthday, tags, created_at, updated_at)
        VALUES
          (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW(), NOW())
        RETURNING id
    """, (consultant_id, first, last, email, phone, street, street2, city, state, postal, birthday, tags))
    return int(cur.fetchone()[0])

from datetime import datetime, timezone
from typing import Optional

def get_customer_id_by_name(cur, consultant_id: int, first: str, last: str) -> Optional[int]:
    """
    Find the most recent matching customer by name (scoped to consultant_id).
    Returns customer_id or None.
    """
    is_sqlite = _is_sqlite_cursor(cur)
    first = (first or "").strip()
    last = (last or "").strip()

    if is_sqlite:
        cur.execute("""
            SELECT id
            FROM customers
            WHERE consultant_id = ?
              AND COALESCE(source_status, 'active') = 'active'
              AND LOWER(first_name) = LOWER(?)
              AND LOWER(last_name) = LOWER(?)
            ORDER BY id DESC
            LIMIT 1
        """, (consultant_id, first, last))
    else:
        cur.execute("""
            SELECT id
            FROM customers
            WHERE consultant_id = %s
              AND COALESCE(source_status, 'active') = 'active'
              AND LOWER(first_name) = LOWER(%s)
              AND LOWER(last_name) = LOWER(%s)
            ORDER BY id DESC
            LIMIT 1
        """, (consultant_id, first, last))

    row = cur.fetchone()
    return int(row[0]) if row else None


def create_order_from_confirmed(
    cur,
    consultant_id: int,
    customer_id: int,
    order_lines: list,
    source: str = "chat",
    order_date: str = None,
    discounts: list = None,
    tax_amount: float = 0.0,
    discount_type: str = None,
    discount_value: float = None,
    tax_percent: float = None,
) -> int:
    """
    Create an order + order_items in CRM tables.

    order_lines are your resolved lines with:
      - line["qty"]
      - line["chosen"] dict containing at least: sku, product_name, price
    discounts: list of {"amount": float, "line_idx": int|None, "label": str}
    tax_amount: computed tax to store on the order
    Returns order_id.
    """
    is_sqlite = _is_sqlite_cursor(cur)

    discounts = discounts or []

    # Calculate subtotal (pre-discount)
    subtotal = 0.0
    for line in order_lines:
        qty = int(line.get("qty") or 1)
        chosen = line.get("chosen") or {}
        price = chosen.get("price")
        try:
            unit_price = float(price) if price is not None else 0.0
        except Exception:
            unit_price = 0.0
        subtotal += unit_price * max(1, qty)

    total_discount = sum(d.get("amount", 0) for d in discounts)
    try:
        tax_amount = float(tax_amount or 0)
    except Exception:
        tax_amount = 0.0

    # total mirrors InTouch's GrandTotalAmount (subtotal − discount + tax) so the
    # nightly sync's reconcile is a no-op — verified live 2026-07-18: InTouch
    # returned 200.80 for the $256 − $55.20 no-tax test order. For "total sales"
    # analytics, product revenue = total − tax_amount.
    total = max(0.0, subtotal - total_discount) + tax_amount

    # Use provided order_date if valid, else fall back to now
    _use_date = None
    if order_date:
        try:
            from datetime import date as _d
            _d.fromisoformat(order_date)  # validates format
            _use_date = order_date
        except Exception:
            pass

    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert order row (discount_type/value + tax_percent added 2026-07-18:
    # what the consultant SAID and the rate applied, alongside the $ amounts)
    if is_sqlite:
        cur.execute("""
            INSERT INTO orders (consultant_id, customer_id, order_date, total, source, discount_amount, tax_amount, discount_type, discount_value, tax_percent, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
        """, (consultant_id, customer_id, _use_date or now_iso, total, source, total_discount, tax_amount, discount_type, discount_value, tax_percent))
        order_id = int(cur.lastrowid)
    else:
        if _use_date:
            cur.execute("""
                INSERT INTO orders (consultant_id, customer_id, order_date, total, source, discount_amount, tax_amount, discount_type, discount_value, tax_percent, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                RETURNING id
            """, (consultant_id, customer_id, _use_date, total, source, total_discount, tax_amount, discount_type, discount_value, tax_percent))
        else:
            cur.execute("""
                INSERT INTO orders (consultant_id, customer_id, order_date, total, source, discount_amount, tax_amount, discount_type, discount_value, tax_percent, created_at)
                VALUES (%s,%s, NOW(), %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (consultant_id, customer_id, total, source, total_discount, tax_amount, discount_type, discount_value, tax_percent))
        order_id = int(cur.fetchone()[0])

    # Build per-item discount map by line index
    per_line_discount: dict[int, float] = {}
    for d in discounts:
        idx = d.get("line_idx")
        if idx is not None:
            per_line_discount[idx] = per_line_discount.get(idx, 0) + d.get("amount", 0)

    # Insert items (one row per line, with quantity stored)
    for i, line in enumerate(order_lines):
        qty = int(line.get("qty") or 1)
        chosen = line.get("chosen") or {}

        sku = (chosen.get("sku") or "").strip()
        name = (chosen.get("product_name") or chosen.get("name") or "").strip()
        price = chosen.get("price")
        try:
            unit_price = float(price) if price is not None else 0.0
        except Exception:
            unit_price = 0.0

        item_discount = per_line_discount.get(i, 0.0)

        # Don't crash if something is weird—just skip that line.
        if not sku or not name:
            continue

        if is_sqlite:
            cur.execute("""
                INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
                VALUES (?,?,?,?,?,?, datetime('now'))
            """, (order_id, sku, name, unit_price, max(1, qty), item_discount))
        else:
            cur.execute("""
                INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
                VALUES (%s,%s,%s,%s,%s,%s, NOW())
            """, (order_id, sku, name, unit_price, max(1, qty), item_discount))

    return order_id

def get_recent_orders_for_customer(cur, customer_id: int, limit: int = 3,
                                   start_date: str | None = None,
                                   end_date: str | None = None):
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"

    date_filter = ""
    params: list = [customer_id]
    if start_date:
        date_filter += f" AND order_date >= {PH}"
        params.append(start_date)
    if end_date:
        date_filter += f" AND order_date < {PH}"
        params.append(end_date)
    params.append(limit)

    cur.execute(f"""
        SELECT id, order_date, total, source
        FROM orders
        WHERE customer_id = {PH}{date_filter}
        ORDER BY order_date DESC, id DESC
        LIMIT {PH}
    """, params)

    orders = _rows_to_dicts(cur)

    # Attach items for each order
    for o in orders:
        oid = o["id"]
        if is_sqlite:
            cur.execute("""
                SELECT sku, product_name, unit_price, quantity
                FROM order_items
                WHERE order_id = ?
                ORDER BY id ASC
            """, (oid,))
        else:
            cur.execute("""
                SELECT sku, product_name, unit_price, quantity
                FROM order_items
                WHERE order_id = %s
                ORDER BY id ASC
            """, (oid,))
        o["items"] = _rows_to_dicts(cur)

    return orders


from datetime import datetime

def format_recent_orders(customer_name: str, orders: list, period_label: str | None = None) -> str:
    if not orders:
        period_str = f" in {period_label}" if period_label else ""
        return f"I don't see any orders for {customer_name}{period_str}."

    header = f"{customer_name}'s orders in {period_label}:" if period_label else f"Recent orders for {customer_name}:"
    lines = [header]

    for o in orders:
        # Format date properly (works for sqlite string or postgres datetime)
        od = o.get("order_date")

        if isinstance(od, str):
            try:
                dt = datetime.fromisoformat(od.replace("Z", "+00:00"))
            except Exception:
                dt = None
        elif isinstance(od, datetime):
            dt = od
        else:
            dt = None

        if dt:
            od_str = f"{dt.month}/{dt.day}/{dt.year}"
        else:
            od_str = "—"

        total = o.get("total")
        total_str = f"${float(total):,.2f}" if total is not None else "—"

        _src = o.get("source") or ""
        source_label = " · Online | CDS" if _src in ("myshop", "cds") else ""

        lines.append(f"\n{od_str}{source_label} • Total: {total_str}")

        items = o.get("items") or []
        for it in items:
            qty = it.get("quantity") or 1
            name = it.get("product_name") or it.get("sku") or "Item"
            lines.append(f"- {qty} × {name}" if qty > 1 else f"- {name}")

    return "\n".join(lines)

from datetime import datetime, timedelta, timezone

def get_customer_spending(cur, consultant_id: int, customer_id: int, start_date=None, end_date=None):
    """
    Returns total spending for a customer within optional date range.
    """
    is_sqlite = _is_sqlite_cursor(cur)

    params = []
    date_filter = ""

    if start_date:
        if is_sqlite:
            date_filter += " AND order_date >= ?"
        else:
            date_filter += " AND order_date >= %s"
        params.append(start_date)

    if end_date:
        if is_sqlite:
            date_filter += " AND order_date <= ?"
        else:
            date_filter += " AND order_date <= %s"
        params.append(end_date)

    if is_sqlite:
        cur.execute(f"""
            SELECT COALESCE(SUM(total), 0)
            FROM orders
            WHERE consultant_id = ?
              AND customer_id = ?
              {date_filter}
        """, (consultant_id, customer_id, *params))
    else:
        cur.execute(f"""
            SELECT COALESCE(SUM(total), 0)
            FROM orders
            WHERE consultant_id = %s
              AND customer_id = %s
              {date_filter}
        """, (consultant_id, customer_id, *params))

    row = cur.fetchone()
    return float(row[0] or 0)

def parse_time_filter_from_text(text: str):
    """
    Dynamic time parser.
    Supports:
      - this year
      - this month
      - this quarter
      - last quarter
      - last X days / past X days
      - lifetime (default)
    Returns (start_date_iso, end_date_iso)
    """
    import re
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    t = (text or "").lower()

    # This year
    if "this year" in t:
        start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        return start.isoformat(), None

    # This month
    if "this month" in t:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        return start.isoformat(), None

    # This quarter
    if "this quarter" in t:
        q = ((now.month - 1) // 3) + 1
        start_month = (q - 1) * 3 + 1
        start = datetime(now.year, start_month, 1, tzinfo=timezone.utc)
        return start.isoformat(), None

    # Last quarter
    if "last quarter" in t:
        q = ((now.month - 1) // 3) + 1
        if q == 1:
            year = now.year - 1
            start_month = 10
        else:
            year = now.year
            start_month = (q - 2) * 3 + 1
        start = datetime(year, start_month, 1, tzinfo=timezone.utc)
        return start.isoformat(), None

    # Dynamic: last X days / past X days
    m = re.search(r"(last|past)\s+(\d+)\s+day", t)
    if m:
        days = int(m.group(2))
        start = now - timedelta(days=days)
        return start.isoformat(), None

    # Default: lifetime
    return None, None

def parse_top_n_from_text(text: str, default: int = 5, soft_cap: int = 10, hard_cap: int = 50) -> int:
    """
    Examples:
      - "top customers" -> 5
      - "top 10 customers" -> 10
      - "top 25 customers" -> 25 (allowed if explicitly asked, up to hard_cap)
    """
    import re
    t = (text or "").lower()

    # Look for explicit "top N" or "show N"
    m = re.search(r"\b(top|show)\s*[:#]?\s*(\d+)\b", t)
    if m:
        n = int(m.group(2))
        return max(1, min(hard_cap, n))

    # Or "top customers N"
    m = re.search(r"\bcustomers\s+(\d+)\b", t)
    if m:
        n = int(m.group(1))
        return max(1, min(hard_cap, n))

    # No explicit number -> default, but don't exceed soft cap
    return min(default, soft_cap)

def get_top_customers(cur, consultant_id: int, limit: int = 5, start_date=None, end_date=None):
    """
    Returns customers ranked by total spend in optional date range.
    Each row: id, first_name, last_name, phone, email, total_spent
    """
    is_sqlite = _is_sqlite_cursor(cur)

    date_filter = ""
    params = []

    if start_date:
        date_filter += " AND o.order_date >= " + ("?" if is_sqlite else "%s")
        params.append(start_date)
    if end_date:
        date_filter += " AND o.order_date <= " + ("?" if is_sqlite else "%s")
        params.append(end_date)

    if is_sqlite:
        sql = f"""
        SELECT
          c.id,
          c.first_name,
          c.last_name,
          c.phone,
          c.email,
          COALESCE(SUM(o.total), 0) AS total_spent
        FROM customers c
        JOIN orders o ON o.customer_id = c.id
        WHERE c.consultant_id = ?
          AND COALESCE(c.source_status, 'active') = 'active'
          {date_filter}
        GROUP BY c.id, c.first_name, c.last_name, c.phone, c.email
        ORDER BY total_spent DESC, c.last_name, c.first_name
        LIMIT ?
        """
        cur.execute(sql, (consultant_id, *params, limit))
    else:
        sql = f"""
        SELECT
          c.id,
          c.first_name,
          c.last_name,
          c.phone,
          c.email,
          COALESCE(SUM(o.total), 0) AS total_spent
        FROM customers c
        JOIN orders o ON o.customer_id = c.id
        WHERE c.consultant_id = %s
          AND COALESCE(c.source_status, 'active') = 'active'
          {date_filter}
        GROUP BY c.id, c.first_name, c.last_name, c.phone, c.email
        ORDER BY total_spent DESC, c.last_name, c.first_name
        LIMIT %s
        """
        cur.execute(sql, (consultant_id, *params, limit))

    return _rows_to_dicts(cur)


def _lapsed_base_query(cur, consultant_id: int, days: int, min_orders: int = 1, limit: int = 100) -> list:
    """
    Returns lapsed customers with order stats. Shared by VIP and fill queries.
    min_orders: 2 for VIP pass, 1 for fill pass.
    """
    is_sqlite = _is_sqlite_cursor(cur)
    if is_sqlite:
        cur.execute("""
            SELECT c.id, c.first_name, c.last_name, c.phone,
                   CAST(julianday('now') - julianday(MAX(o.order_date)) AS INTEGER) AS days_since,
                   COUNT(DISTINCT o.id)   AS order_count,
                   COALESCE(SUM(o.total), 0) AS total_spent,
                   MAX(o.id)             AS last_order_id
            FROM customers c
            JOIN orders o ON o.customer_id = c.id AND o.consultant_id = c.consultant_id
            WHERE c.consultant_id = ?
              AND COALESCE(c.source_status, 'active') = 'active'
            GROUP BY c.id, c.first_name, c.last_name, c.phone
            HAVING CAST(julianday('now') - julianday(MAX(o.order_date)) AS INTEGER) >= ?
               AND COUNT(DISTINCT o.id) >= ?
            ORDER BY days_since ASC, order_count DESC, total_spent DESC
            LIMIT ?
        """, (consultant_id, days, min_orders, limit))
    else:
        cur.execute("""
            SELECT c.id, c.first_name, c.last_name, c.phone,
                   EXTRACT(DAY FROM NOW() - MAX(o.order_date::date))::INT AS days_since,
                   COUNT(DISTINCT o.id)      AS order_count,
                   COALESCE(SUM(o.total), 0) AS total_spent,
                   MAX(o.id)                 AS last_order_id
            FROM customers c
            JOIN orders o ON o.customer_id = c.id AND o.consultant_id = c.consultant_id
            WHERE c.consultant_id = %s
              AND COALESCE(c.source_status, 'active') = 'active'
            GROUP BY c.id, c.first_name, c.last_name, c.phone
            HAVING EXTRACT(DAY FROM NOW() - MAX(o.order_date::date))::INT >= %s
               AND COUNT(DISTINCT o.id) >= %s
            ORDER BY days_since ASC, order_count DESC, total_spent DESC
            LIMIT %s
        """, (consultant_id, days, min_orders, limit))
    return _rows_to_dicts(cur)


def _fetch_order_items(cur, order_id: int) -> list:
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"
    cur.execute(f"""
        SELECT sku, product_name, unit_price, quantity
        FROM order_items WHERE order_id = {PH} ORDER BY id ASC
    """, (order_id,))
    return _rows_to_dicts(cur)


def get_lapsed_customers(cur, consultant_id: int, days: int, card_limit: int = 5) -> dict:
    """
    Returns {'cards': [...], 'rest': [...]} where cards is the top card_limit rows
    sorted most-recently-lapsed first (just crossed the threshold), with order_count
    and total_spent as tiebreakers. Each card row includes last_order_items.
    """
    all_lapsed = _lapsed_base_query(cur, consultant_id, days, min_orders=1, limit=200)

    cards = all_lapsed[:card_limit]
    rest  = all_lapsed[card_limit:]

    for r in cards:
        oid = r.get("last_order_id")
        r["last_order_items"] = _fetch_order_items(cur, oid) if oid else []

    return {"cards": cards, "rest": rest}


def _days_label(d: int) -> str:
    m = round(d / 30)
    return f"{m} month{'s' if m != 1 else ''} ago" if m >= 2 else f"{d} days ago"


def format_lapsed_customers(result: dict, days: int) -> str:
    cards = result.get("cards") or []
    rest  = result.get("rest") or []

    months = days // 30
    period = f"{months} month{'s' if months != 1 else ''}" if days % 30 == 0 else f"{days} days"

    if not cards and not rest:
        return f"Every customer with order history has ordered within the last {period}. You're all caught up! ✅"

    lines = [f"Customers who haven't ordered in {period}+:"]

    for r in cards:
        name = f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
        age  = f"last order {_days_label(int(r.get('days_since') or 0))}"

        items = r.get("last_order_items") or []
        if items:
            hero = max(items, key=lambda i: float(i.get("unit_price") or 0))
            hero_name = hero.get("product_name") or hero.get("sku") or "item"
            others = [i for i in items if i is not hero]
            item_line = f"Last order: {hero_name}"
            if others:
                overflow = len(others) - 1
                next_item = others[0].get("product_name") or others[0].get("sku") or ""
                if overflow > 0:
                    item_line += f', {next_item} <a href="#" data-send="last order for {name}">+{overflow} more</a>'
                else:
                    item_line += f", {next_item}"
        else:
            item_line = ""

        lines.append(f"\n<strong>{name}</strong> — {age}")
        if item_line:
            lines.append(item_line)

    if rest:
        lines.append(f'\n<a href="#" data-send="show all lapsed {days} days">+{len(rest)} more</a>')

    return "\n".join(lines)


def format_leaderboard(rows: list, title: str) -> str:
    if not rows:
        return "I don't see any orders yet for that time period."

    lines = [title]

    for i, r in enumerate(rows, start=1):
        name = f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
        spent = float(r.get("total_spent") or 0)

        lines.append(f"{i}. {name} — ${spent:,.2f}")

    if len(rows) >= 10:
        lines.append("\nWant more? Try: show 20 or top 25 customers.")

    return "\n".join(lines)

def get_customer_by_id(cur, consultant_id: int, customer_id: int):
    is_sqlite = _is_sqlite_cursor(cur)
    if is_sqlite:
        cur.execute("""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday
            FROM customers
            WHERE consultant_id = ? AND id = ?
            LIMIT 1
        """, (consultant_id, customer_id))
    else:
        cur.execute("""
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday
            FROM customers
            WHERE consultant_id = %s AND id = %s
            LIMIT 1
        """, (consultant_id, customer_id))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def count_orders_for_customer(cur, customer_id: int) -> int:
    is_sqlite = _is_sqlite_cursor(cur)
    if is_sqlite:
        cur.execute("SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,))
    else:
        cur.execute("SELECT COUNT(*) FROM orders WHERE customer_id = %s", (customer_id,))
    return int(cur.fetchone()[0] or 0)


def find_customers_by_category(cur, consultant_id: int, or_terms: list[str]) -> list[dict]:
    """
    Returns distinct customers who have ordered products matching ANY of the given terms.
    or_terms: list of lowercase fragments, ORed together against order_items.product_name.
    Used for category searches (e.g. "perfume" → ["eau de parfum", "cologne spray", ...]).
    """
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"

    if not or_terms:
        return []

    like_clauses = " OR ".join(f"LOWER(oi.product_name) LIKE {PH}" for _ in or_terms)
    like_values = [f"%{t}%" for t in or_terms]

    query = f"""
        SELECT c.id, c.first_name, c.last_name, oi.product_name, o.order_date
        FROM customers c
        JOIN orders o ON o.customer_id = c.id AND o.consultant_id = {PH}
        JOIN order_items oi ON oi.order_id = o.id
        WHERE c.consultant_id = {PH}
          AND COALESCE(c.source_status, 'active') = 'active'
          AND ({like_clauses})
        ORDER BY c.last_name, c.first_name, o.order_date DESC
    """
    cur.execute(query, [consultant_id, consultant_id] + like_values)
    rows = _rows_to_dicts(cur)

    from collections import OrderedDict
    grouped = OrderedDict()
    for row in rows:
        cid = row["id"]
        if cid not in grouped:
            grouped[cid] = {
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "products": [],
            }
        product_name = (row.get("product_name") or "").strip()
        _od = row.get("order_date")
        order_date = str(_od)[:10] if _od else ""
        if not any(p["name"] == product_name for p in grouped[cid]["products"]):
            grouped[cid]["products"].append({"name": product_name, "date": order_date})

    return list(grouped.values())


def find_customer_items_like(cur, consultant_id: int, customer_id: int,
                             terms: list[str], limit: int = 6) -> list[dict]:
    """A customer's distinct ordered products matching ANY term (LIKE), most
    recent first. Category system 2026-07-19: powers 'what shade of foundation
    does Kim wear' — filter her history to the product type instead of dumping
    everything (weed-garden F2 family, c29+c90+c104)."""
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"
    terms = [t for t in (terms or []) if t]
    if not terms:
        return []
    like = " OR ".join(f"LOWER(oi.product_name) LIKE {PH}" for _ in terms)
    cur.execute(f"""
        SELECT oi.product_name, MAX(o.order_date) AS last_date
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        WHERE o.consultant_id = {PH} AND o.customer_id = {PH}
          AND ({like})
        GROUP BY oi.product_name
        ORDER BY last_date DESC
        LIMIT {int(limit)}
    """, [consultant_id, int(customer_id)] + [f"%{t.lower()}%" for t in terms])
    return _rows_to_dicts(cur)


def find_customers_by_skus(cur, consultant_id: int, skus: set) -> list[dict]:
    """Distinct active customers who ordered any of the given SKUs (category
    system 2026-07-19: 'skincare customers' = customers whose order_items hit
    the category's SKU set). Same return shape as find_customers_by_product."""
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"
    skus = [s for s in (skus or set()) if s]
    if not skus:
        return []
    placeholders = ",".join([PH] * len(skus))
    query = f"""
        SELECT c.id, c.first_name, c.last_name, oi.product_name, o.order_date
        FROM customers c
        JOIN orders o ON o.customer_id = c.id AND o.consultant_id = {PH}
        JOIN order_items oi ON oi.order_id = o.id
        WHERE c.consultant_id = {PH}
          AND COALESCE(c.source_status, 'active') = 'active'
          AND oi.sku IN ({placeholders})
        ORDER BY c.last_name, c.first_name, o.order_date DESC
    """
    cur.execute(query, [consultant_id, consultant_id] + skus)
    rows = _rows_to_dicts(cur)
    from collections import OrderedDict
    grouped = OrderedDict()
    for row in rows:
        cid = row["id"]
        if cid not in grouped:
            grouped[cid] = {"first_name": row["first_name"],
                            "last_name": row["last_name"], "products": []}
        pn = (row.get("product_name") or "").strip()
        _od = row.get("order_date")
        od = str(_od)[:10] if _od else ""
        if pn and not any(p["name"] == pn for p in grouped[cid]["products"]):
            grouped[cid]["products"].append({"name": pn, "date": od})
    return list(grouped.values())


def find_customers_by_product(cur, consultant_id: int, terms: list[str]) -> list[dict]:
    """
    Returns distinct customers who have ordered products matching ALL given terms.
    terms: list of lowercase words, e.g. ["matte", "foundation"]
    Each term is matched with LIKE '%term%' against order_items.product_name.
    """
    is_sqlite = _is_sqlite_cursor(cur)
    PH = "?" if is_sqlite else "%s"

    if not terms:
        return []

    # Build WHERE clause: one LIKE condition per term, ANDed together
    like_clauses = " AND ".join(f"LOWER(oi.product_name) LIKE {PH}" for _ in terms)
    like_values = [f"%{t}%" for t in terms]

    query = f"""
        SELECT c.id, c.first_name, c.last_name, oi.product_name, o.order_date
        FROM customers c
        JOIN orders o ON o.customer_id = c.id AND o.consultant_id = {PH}
        JOIN order_items oi ON oi.order_id = o.id
        WHERE c.consultant_id = {PH}
          AND COALESCE(c.source_status, 'active') = 'active'
          AND {like_clauses}
        ORDER BY c.last_name, c.first_name, o.order_date DESC
    """
    cur.execute(query, [consultant_id, consultant_id] + like_values)
    rows = _rows_to_dicts(cur)

    # Group by customer, collecting distinct products with their most recent date
    from collections import OrderedDict
    grouped = OrderedDict()
    for row in rows:
        cid = row["id"]
        if cid not in grouped:
            grouped[cid] = {
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "products": [],
            }
        product_name = (row.get("product_name") or "").strip()
        _od = row.get("order_date")
        order_date = str(_od)[:10] if _od else ""
        # Only keep first occurrence of each product (already sorted date DESC = most recent first)
        if not any(p["name"] == product_name for p in grouped[cid]["products"]):
            grouped[cid]["products"].append({"name": product_name, "date": order_date})

    return list(grouped.values())


def get_customers_by_city(cur, consultant_id: int, city: str):
    from db import is_postgres
    PH = "%s" if is_postgres() else "?"
    ILIKE = "ILIKE" if is_postgres() else "LIKE"
    cur.execute(
        f"""
        SELECT first_name, last_name
        FROM customers
        WHERE consultant_id = {PH}
          AND city {ILIKE} {PH}
          AND COALESCE(source_status, 'active') = 'active'
        ORDER BY last_name, first_name
        """,
        (consultant_id, city),
    )
    rows = cur.fetchall()
    return [{"first_name": r[0], "last_name": r[1]} for r in rows]


def format_city_customers(rows: list, city: str, show_all: bool = False) -> str:
    import html as _html
    if not rows:
        return f"No customers found in {city}."
    total = len(rows)
    shown = rows if show_all else rows[:10]
    rest = [] if show_all else rows[10:]
    city_esc = _html.escape(city)
    header = f"{total} customer{'s' if total != 1 else ''} in {city_esc}:"
    lines = []
    for c in shown:
        name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
        safe = _html.escape(name, quote=True)
        lines.append(f"• <a href=\"#\" data-send=\"{safe}\">{_html.escape(name)}</a>")
    if rest:
        send = _html.escape(f"customers in {city} all", quote=True)
        lines.append(f'\n<a href="#" data-send="{send}">+{len(rest)} more</a>')
    return header + "\n" + "\n".join(lines)


_US_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}
_US_STATE_ABBRS: dict[str, str] = {v.lower(): v for v in _US_STATE_NAMES.values()}
_STATE_ABBR_TO_NAME: dict[str, str] = {v: k.title() for k, v in _US_STATE_NAMES.items()}


def normalize_state(text: str) -> tuple[str, str] | tuple[None, None]:
    """Return (abbr, display_name) if text is a US state name or abbreviation, else (None, None)."""
    t = text.strip().lower()
    if t in _US_STATE_NAMES:
        abbr = _US_STATE_NAMES[t]
        return abbr, text.strip().title()
    if t in _US_STATE_ABBRS:
        abbr = _US_STATE_ABBRS[t]
        return abbr, _STATE_ABBR_TO_NAME[abbr]
    return None, None


def parse_city_state(text: str):
    """
    Parse location text into (city, state_abbr, state_display).
    Handles: 'Nashville, TN', 'Nashville, Tennessee', 'Nashville Tennessee',
             'Alabama' (pure state), 'Guntersville' (pure city).
    Returns (city_str, abbr, display) where city_str may be '' for pure-state input.
    """
    import re as _re
    t = text.strip()

    # Pattern 1: comma separator — "Nashville, TN" / "Nashville, Tennessee"
    m = _re.match(r'^(.+?),\s*([A-Za-z][A-Za-z\s]*)$', t)
    if m:
        city_part = m.group(1).strip()
        state_part = m.group(2).strip()
        abbr, display = normalize_state(state_part)
        if abbr:
            return city_part, abbr, display

    # Pattern 2: no comma — try last 2 words then last 1 word as state
    words = t.split()
    if len(words) >= 2:
        abbr, display = normalize_state(" ".join(words[-2:]))
        if abbr:
            return " ".join(words[:-2]), abbr, display
    if len(words) >= 2:
        abbr, display = normalize_state(words[-1])
        if abbr:
            return " ".join(words[:-1]), abbr, display

    # Pure state or pure city
    abbr, display = normalize_state(t)
    if abbr:
        return "", abbr, display
    return t, None, None


def get_customers_by_city_and_state(cur, consultant_id: int, city: str, state_abbr: str):
    from db import is_postgres
    PH = "%s" if is_postgres() else "?"
    ILIKE = "ILIKE" if is_postgres() else "LIKE"
    cur.execute(
        f"""
        SELECT first_name, last_name
        FROM customers
        WHERE consultant_id = {PH}
          AND city {ILIKE} {PH}
          AND state {ILIKE} {PH}
          AND COALESCE(source_status, 'active') = 'active'
        ORDER BY last_name, first_name
        """,
        (consultant_id, city, state_abbr),
    )
    rows = cur.fetchall()
    return [{"first_name": r[0], "last_name": r[1]} for r in rows]


def get_customers_by_state(cur, consultant_id: int, state_abbr: str):
    from db import is_postgres
    PH = "%s" if is_postgres() else "?"
    ILIKE = "ILIKE" if is_postgres() else "LIKE"
    cur.execute(
        f"""
        SELECT first_name, last_name
        FROM customers
        WHERE consultant_id = {PH}
          AND state {ILIKE} {PH}
          AND COALESCE(source_status, 'active') = 'active'
        ORDER BY last_name, first_name
        """,
        (consultant_id, state_abbr),
    )
    rows = cur.fetchall()
    return [{"first_name": r[0], "last_name": r[1]} for r in rows]


def format_state_customers(rows: list, state_name: str, show_all: bool = False) -> str:
    import html as _html
    if not rows:
        return f"No customers found in {state_name}."
    total = len(rows)
    shown = rows if show_all else rows[:10]
    rest = [] if show_all else rows[10:]
    state_esc = _html.escape(state_name)
    header = f"{total} customer{'s' if total != 1 else ''} in {state_esc}:"
    lines = []
    for c in shown:
        name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
        safe = _html.escape(name, quote=True)
        lines.append(f"• <a href=\"#\" data-send=\"{safe}\">{_html.escape(name)}</a>")
    if rest:
        send = _html.escape(f"customers in {state_name} all", quote=True)
        lines.append(f'\n<a href="#" data-send="{send}">+{len(rest)} more</a>')
    return header + "\n" + "\n".join(lines)


def format_customers_by_product(customers: list[dict], search_term: str) -> str:
    import html as _html
    if not customers:
        return f"No customers found who have ordered {search_term}."
    header = f"{len(customers)} customer{'s' if len(customers) != 1 else ''} found:"
    lines = []
    for c in customers:
        name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
        safe = _html.escape(name, quote=True)
        name_link = f'<a href="#" data-send="{safe}">{_html.escape(name)}</a>'
        product_parts = []
        for p in (c.get("products") or []):
            pname = p.get("name") or ""
            pdate = p.get("date") or ""
            if pdate:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(pdate[:10], "%Y-%m-%d")
                    pdate = f"last ordered {dt.month}/{dt.day}/{str(dt.year)[2:]}"
                except Exception:
                    pass
            product_parts.append(f"{pname} ({pdate})" if pdate else pname)
        product_str = ", ".join(product_parts)
        lines.append(f"• {name_link} — {product_str}" if product_str else f"• {name_link}")
    return header + "\n" + "\n".join(lines)


def delete_customer_local(cur, consultant_id: int, customer_id: int, delete_orders: bool = True) -> int:
    """
    Deletes a customer from local CRM only (scoped to consultant_id).
    If delete_orders=True, deletes related orders + order_items first.
    Returns number of customers deleted (0 or 1).
    """
    is_sqlite = _is_sqlite_cursor(cur)

    if delete_orders:
        # Delete order_items for this customer's orders
        if is_sqlite:
            cur.execute("""
                DELETE FROM order_items
                WHERE order_id IN (SELECT id FROM orders WHERE customer_id = ? AND consultant_id = ?)
            """, (customer_id, consultant_id))
            cur.execute("DELETE FROM orders WHERE customer_id = ? AND consultant_id = ?", (customer_id, consultant_id))
        else:
            cur.execute("""
                DELETE FROM order_items
                WHERE order_id IN (SELECT id FROM orders WHERE customer_id = %s AND consultant_id = %s)
            """, (customer_id, consultant_id))
            cur.execute("DELETE FROM orders WHERE customer_id = %s AND consultant_id = %s", (customer_id, consultant_id))

    # Delete customer
    if is_sqlite:
        cur.execute("DELETE FROM customers WHERE consultant_id = ? AND id = ?", (consultant_id, customer_id))
        return int(cur.rowcount or 0)
    else:
        cur.execute("DELETE FROM customers WHERE consultant_id = %s AND id = %s", (consultant_id, customer_id))
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Birthday period lookup
# ---------------------------------------------------------------------------

def get_customers_by_birthday_period(consultant_id: int, period: str, cur) -> list[dict]:
    """
    Return customers whose birthday (month/day) falls within the requested period.

    period values: "month", "week", "next_week", "quarter", "upcoming" (30 days)

    Birthdays are stored as YYYY-MM-DD (year 2000 when none given). Only month
    and day are compared — the stored year is ignored.

    Returns list of dicts sorted by days_until ascending:
      customer_id, first_name, last_name, phone, bday_month, bday_day,
      bday_month_name, days_until, is_first_contact
    """
    import datetime, calendar as _cal

    is_sqlite = "sqlite" in type(cur).__module__.lower()
    PH = "?" if is_sqlite else "%s"

    cur.execute(
        f"SELECT id, first_name, last_name, phone, birthday FROM customers "
        f"WHERE consultant_id = {PH} AND birthday IS NOT NULL AND birthday <> '' "
        f"AND phone IS NOT NULL AND phone <> '' "
        f"AND COALESCE(source_status, 'active') = 'active'",
        (consultant_id,),
    )
    rows = cur.fetchall()

    def _g(row, key, idx):
        try:
            return row[key] if isinstance(row, dict) else row[idx]
        except Exception:
            return None

    # Use America/Chicago local date so "today" is correct for US consultants
    # regardless of what UTC date the Render server reports.
    try:
        from zoneinfo import ZoneInfo as _ZI
        today = datetime.datetime.now(_ZI("America/Chicago")).date()
    except Exception:
        today = datetime.date.today()

    # Determine the date window for each period
    if period == "today":
        def _in_window(bday_this_year):
            return bday_this_year == today
    elif period == "tomorrow":
        tomorrow = today + datetime.timedelta(days=1)
        def _in_window(bday_this_year):
            return bday_this_year == tomorrow
    elif period == "month":
        month_start = today.replace(day=1)
        last_day = _cal.monthrange(today.year, today.month)[1]
        month_end = today.replace(day=last_day)
        def _in_window(bday_this_year):
            return month_start <= bday_this_year <= month_end
    elif period == "week":
        window_end = today + datetime.timedelta(days=6)
        def _in_window(bday_this_year):
            if window_end.month >= today.month:
                return today <= bday_this_year <= window_end
            # wraps into next year — already handled by try_next_year logic below
            return today <= bday_this_year or bday_this_year <= window_end
    elif period == "next_week":
        window_start = today + datetime.timedelta(days=7)
        window_end = today + datetime.timedelta(days=13)
        def _in_window(bday_this_year):
            return window_start <= bday_this_year <= window_end
    elif period == "next_month":
        nm = today.month % 12 + 1
        def _in_window(bday_this_year):
            return bday_this_year.month == nm
    elif period.startswith("month:"):
        # Named month ("birthdays in July" → month:7) — weed-garden 2026-07-11
        _named = int(period.split(":", 1)[1])
        def _in_window(bday_this_year):
            return bday_this_year.month == _named
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        q_months = {q_month, q_month + 1, q_month + 2}
        def _in_window(bday_this_year):
            return bday_this_year.month in q_months
    else:  # "upcoming" — next 30 days
        window_end = today + datetime.timedelta(days=29)
        def _in_window(bday_this_year):
            return today <= bday_this_year <= window_end

    results = []
    for row in rows:
        raw_bday = _g(row, "birthday", 4) or ""
        if not raw_bday or len(raw_bday) < 5:
            continue
        try:
            parts = raw_bday.split("-")
            if len(parts) == 3:      # YYYY-MM-DD
                bday_month = int(parts[1])
                bday_day = int(parts[2])
            elif len(parts) == 2:    # MM-DD (no year stored)
                bday_month = int(parts[0])
                bday_day = int(parts[1])
            else:
                continue
        except Exception:
            continue

        try:
            bday_this_year = datetime.date(today.year, bday_month, bday_day)
        except ValueError:
            continue  # invalid date (e.g. Feb 29 in non-leap year)

        # For week/upcoming periods that span year boundary, also check next year
        bday_next_year = datetime.date(today.year + 1, bday_month, bday_day)

        if _in_window(bday_this_year):
            ref_date = bday_this_year
        elif period in ("week", "next_week", "upcoming", "next_month", "tomorrow") and _in_window(bday_next_year):
            ref_date = bday_next_year
        else:
            continue

        days_until = (ref_date - today).days

        customer_id = _g(row, "id", 0)
        first_name  = _g(row, "first_name", 1) or ""
        last_name   = _g(row, "last_name", 2) or ""
        phone       = _g(row, "phone", 3) or ""
        bday_month_name = _cal.month_name[bday_month]

        # is_first_contact: no completed order or birthday followup
        cur.execute(
            f"SELECT 1 FROM customer_followups WHERE customer_id = {PH} AND consultant_id = {PH} AND completed_at IS NOT NULL LIMIT 1",
            (customer_id, consultant_id),
        )
        is_first = cur.fetchone() is None
        if is_first:
            cur.execute(
                f"SELECT 1 FROM customer_birthday_followups WHERE customer_id = {PH} AND consultant_id = {PH} AND completed_at IS NOT NULL LIMIT 1",
                (customer_id, consultant_id),
            )
            is_first = cur.fetchone() is None

        # contacted_this_year: texted for this birthday year specifically
        cur.execute(
            f"SELECT 1 FROM customer_birthday_followups WHERE customer_id = {PH} AND consultant_id = {PH} AND year = {PH} AND completed_at IS NOT NULL LIMIT 1",
            (customer_id, consultant_id, today.year),
        )
        contacted_this_year = cur.fetchone() is not None

        results.append({
            "customer_id":          customer_id,
            "first_name":           first_name,
            "last_name":            last_name,
            "phone":                phone,
            "bday_month":           bday_month,
            "bday_day":             bday_day,
            "bday_month_name":      bday_month_name,
            "days_until":           days_until,
            "is_first_contact":     is_first,
            "contacted_this_year":  contacted_this_year,
        })

    results.sort(key=lambda r: r["days_until"])
    return results


def get_unit_members_by_birthday_period(consultant_id: int, period: str, cur) -> list[dict]:
    """
    Return active unit members whose birthday falls within the requested period.
    Same period values as get_customers_by_birthday_period.
    Returns same dict shape with is_consultant=True; no contacted_this_year tracking.
    """
    import datetime, calendar as _cal

    is_sqlite = "sqlite" in type(cur).__module__.lower()
    PH = "?" if is_sqlite else "%s"

    cur.execute(
        f"SELECT id, first_name, last_name, phone, birthday FROM unit_members "
        f"WHERE consultant_id = {PH} AND sync_status = 'active' "
        f"AND birthday IS NOT NULL AND birthday <> '' "
        f"AND phone IS NOT NULL AND phone <> ''",
        (consultant_id,),
    )
    rows = cur.fetchall()

    def _g(row, key, idx):
        try:
            return row[key] if isinstance(row, dict) else row[idx]
        except Exception:
            return None

    try:
        from zoneinfo import ZoneInfo as _ZI
        today = datetime.datetime.now(_ZI("America/Chicago")).date()
    except Exception:
        today = datetime.date.today()

    if period == "today":
        def _in_window(d): return d == today
    elif period == "tomorrow":
        tomorrow = today + datetime.timedelta(days=1)
        def _in_window(d): return d == tomorrow
    elif period == "month":
        month_start = today.replace(day=1)
        last_day = _cal.monthrange(today.year, today.month)[1]
        month_end = today.replace(day=last_day)
        def _in_window(d): return month_start <= d <= month_end
    elif period == "week":
        window_end = today + datetime.timedelta(days=6)
        def _in_window(d):
            if window_end.month >= today.month:
                return today <= d <= window_end
            return today <= d or d <= window_end
    elif period == "next_week":
        window_start = today + datetime.timedelta(days=7)
        window_end   = today + datetime.timedelta(days=13)
        def _in_window(d): return window_start <= d <= window_end
    elif period == "next_month":
        nm = today.month % 12 + 1
        def _in_window(d): return d.month == nm
    elif period.startswith("month:"):
        # Named month ("birthdays in July" → month:7) — weed-garden 2026-07-11
        _named = int(period.split(":", 1)[1])
        def _in_window(d): return d.month == _named
    elif period == "quarter":
        q_month  = ((today.month - 1) // 3) * 3 + 1
        q_months = {q_month, q_month + 1, q_month + 2}
        def _in_window(d): return d.month in q_months
    else:  # upcoming — next 30 days
        window_end = today + datetime.timedelta(days=29)
        def _in_window(d): return today <= d <= window_end

    results = []
    for row in rows:
        raw_bday = _g(row, "birthday", 4) or ""
        if not raw_bday or len(raw_bday) < 5:
            continue
        try:
            parts = raw_bday.split("-")
            if len(parts) == 3:
                bday_month = int(parts[1])
                bday_day   = int(parts[2])
            elif len(parts) == 2:
                bday_month = int(parts[0])
                bday_day   = int(parts[1])
            else:
                continue
        except Exception:
            continue

        try:
            bday_this_year = datetime.date(today.year, bday_month, bday_day)
        except ValueError:
            continue

        bday_next_year = datetime.date(today.year + 1, bday_month, bday_day)

        if _in_window(bday_this_year):
            ref_date = bday_this_year
        elif period in ("week", "next_week", "upcoming", "next_month", "tomorrow") and _in_window(bday_next_year):
            ref_date = bday_next_year
        else:
            continue

        results.append({
            "customer_id":         _g(row, "id", 0),
            "first_name":          _g(row, "first_name", 1) or "",
            "last_name":           _g(row, "last_name", 2) or "",
            "phone":               _g(row, "phone", 3) or "",
            "bday_month":          bday_month,
            "bday_day":            bday_day,
            "bday_month_name":     _cal.month_name[bday_month],
            "days_until":          (ref_date - today).days,
            "is_first_contact":    False,
            "contacted_this_year": False,
            "is_consultant":       True,
        })

    results.sort(key=lambda r: r["days_until"])
    return results


def get_top_sellers(cur, consultant_id: int, limit: int = 5, since=None) -> list:
    from db import is_postgres
    PH = "%s" if is_postgres() else "?"
    if since:
        cur.execute(
            f"""
            SELECT oi.product_name, SUM(oi.quantity) AS total_qty, COUNT(DISTINCT oi.order_id) AS num_orders
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.consultant_id = {PH}
              AND o.created_at >= {PH}
              AND oi.product_name IS NOT NULL
              AND oi.product_name != ''
            GROUP BY oi.product_name
            ORDER BY total_qty DESC
            LIMIT {PH}
            """,
            (consultant_id, since, limit),
        )
    else:
        cur.execute(
            f"""
            SELECT oi.product_name, SUM(oi.quantity) AS total_qty, COUNT(DISTINCT oi.order_id) AS num_orders
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.consultant_id = {PH}
              AND oi.product_name IS NOT NULL
              AND oi.product_name != ''
            GROUP BY oi.product_name
            ORDER BY total_qty DESC
            LIMIT {PH}
            """,
            (consultant_id, limit),
        )
    return [
        {"product_name": r[0], "total_qty": int(r[1] or 0), "num_orders": int(r[2] or 0)}
        for r in cur.fetchall()
    ]