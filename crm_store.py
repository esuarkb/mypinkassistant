# crm_store.py
from __future__ import annotations
from typing import Any, Dict, List, Optional


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


def find_customers_by_name(cur, consultant_id: int, name: str, limit: int = 10):
    """
    Smarter customer search:
      - "Bonnie" (single token): match first OR last
      - "Kirk C" (last initial): first startswith kirk, last startswith c
      - "Kirk Cam" (partial last): first + last partials
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

    # Helper patterns
    first_starts = f"{p1_low}%"
    first_contains = f"%{p1_low}%"

    last_starts = f"{p2_low}%"
    last_contains = f"%{p2_low}%"

    # Single token: use it for both first/last
    single_starts = f"{p1_low}%"
    single_contains = f"%{p1_low}%"

    # Last initial patterns
    last_init_starts = f"{last_initial}%"

    # SQL differs for sqlite vs postgres placeholders
    if is_sqlite:
        # ORDER BY: starts-with matches first, then contains matches
        if len(parts) == 1:
            sql = """
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
            FROM customers
            WHERE consultant_id = ?
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
            # "Kirk C" -> first starts/contains kirk + last startswith c
            sql = """
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
            FROM customers
            WHERE consultant_id = ?
              AND LOWER(first_name) LIKE ?
              AND LOWER(last_name) LIKE ?
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE ? THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT ?
            """
            params = (consultant_id, first_contains, last_init_starts, first_starts, limit)

        else:
            # "Kirk Cam" or "Kirk Cameron" -> first+last partials
            sql = """
            SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
            FROM customers
            WHERE consultant_id = ?
              AND LOWER(first_name) LIKE ?
              AND LOWER(last_name) LIKE ?
            ORDER BY
              CASE WHEN LOWER(first_name) LIKE ? THEN 0 ELSE 1 END,
              CASE WHEN LOWER(last_name)  LIKE ? THEN 0 ELSE 1 END,
              last_name, first_name
            LIMIT ?
            """
            params = (consultant_id, first_contains, last_contains, first_starts, last_starts, limit)

        cur.execute(sql, params)
        return _rows_to_dicts(cur)

    # Postgres version (%s placeholders)
    if len(parts) == 1:
        sql = """
        SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
        FROM customers
        WHERE consultant_id = %s
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
        sql = """
        SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
        FROM customers
        WHERE consultant_id = %s
          AND LOWER(first_name) LIKE %s
          AND LOWER(last_name) LIKE %s
        ORDER BY
          CASE WHEN LOWER(first_name) LIKE %s THEN 0 ELSE 1 END,
          last_name, first_name
        LIMIT %s
        """
        params = (consultant_id, first_contains, last_init_starts, first_starts, limit)

    else:
        sql = """
        SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
        FROM customers
        WHERE consultant_id = %s
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
    return _rows_to_dicts(cur)


def format_customer_card(c: Dict[str, Any]) -> str:
    from datetime import datetime

    first = (c.get("first_name") or "").strip()
    last = (c.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip() or "Customer"

    email = (c.get("email") or "").strip() or "(none)"
    phone = (c.get("phone") or "").strip() or "(none)"

    street = (c.get("street") or "").strip()
    city = (c.get("city") or "").strip()
    state = (c.get("state") or "").strip()
    postal = (c.get("postal_code") or "").strip()

    addr_parts = [p for p in [street, city, state, postal] if p]
    address = ", ".join(addr_parts) if addr_parts else "(none)"

    # Birthday formatting: "YYYY-MM-DD" -> "December 12, 2012"
    bday_raw = (c.get("birthday") or "").strip()
    birthday = "(none)"
    if bday_raw:
        try:
            # handles "2012-12-12" and ISO strings
            dt = datetime.fromisoformat(bday_raw.replace("Z", "+00:00"))
            birthday = dt.strftime("%B %-d, %Y")  # mac/linux
        except Exception:
            try:
                dt = datetime.strptime(bday_raw[:10], "%Y-%m-%d")
                birthday = dt.strftime("%B %-d, %Y")
            except Exception:
                birthday = bday_raw  # fallback as-is

    lines = [
        f"{full_name}",
        f"• Email: {email}",
        f"• Phone: {_format_phone_pretty(c.get('phone'))}", 
        f"• Address: {address}",
        f"• Birthday: {birthday}",
    ]

    notes = (c.get("notes") or "").strip()
    if notes:
        lines.append(f"• Notes: {notes}")

    return "\n".join(lines)

def upsert_customer_from_pending(cur, consultant_id: int, customer: Dict[str, Any]) -> int:
    """
    Save the confirmed customer into the CRM table.
    - "Upsert" means: update if we think they already exist, otherwise insert.
    - Returns the customer_id in the CRM table.
    """

    # Your pending customer dict uses keys like "First Name", "Last Name", etc.
    first = (customer.get("First Name") or "").strip()
    last = (customer.get("Last Name") or "").strip()
    email = (customer.get("Email") or "").strip() or None
    phone = (customer.get("Phone") or "").strip() or None
    street = (customer.get("Street") or customer.get("Address") or "").strip() or None
    city = (customer.get("City") or "").strip() or None
    state = (customer.get("State") or "").strip() or None
    postal = (customer.get("Postal Code") or customer.get("Zip") or "").strip() or None
    birthday = (customer.get("Birthday") or "").strip() or None

    # How we decide "same customer":
    # Prefer phone, else email, else first+last match.
    is_sqlite = _is_sqlite_cursor(cur)

    if phone:
        where_sql = "consultant_id = ? AND phone = ?" if is_sqlite else "consultant_id = %s AND phone = %s"
        where_params = (consultant_id, phone)
    elif email:
        where_sql = "consultant_id = ? AND LOWER(email) = LOWER(?)" if is_sqlite else "consultant_id = %s AND LOWER(email) = LOWER(%s)"
        where_params = (consultant_id, email)
    else:
        where_sql = "consultant_id = ? AND LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)" if is_sqlite else "consultant_id = %s AND LOWER(first_name)=LOWER(%s) AND LOWER(last_name)=LOWER(%s)"
        where_params = (consultant_id, first, last)

    # 1) Try to find existing
    find_sql = f"SELECT id FROM customers WHERE {where_sql} LIMIT 1"
    cur.execute(find_sql, where_params)
    row = cur.fetchone()

    # 2) Update or Insert
    if row:
        customer_id = int(row[0])

        if is_sqlite:
            cur.execute("""
                UPDATE customers
                SET first_name=?, last_name=?, email=?, phone=?, street=?, city=?, state=?, postal_code=?, birthday=?,
                    updated_at=datetime('now')
                WHERE id=? AND consultant_id=?
            """, (first, last, email, phone, street, city, state, postal, birthday, customer_id, consultant_id))
        else:
            cur.execute("""
                UPDATE customers
                SET first_name=%s, last_name=%s, email=%s, phone=%s, street=%s, city=%s, state=%s, postal_code=%s, birthday=%s,
                    updated_at=NOW()
                WHERE id=%s AND consultant_id=%s
            """, (first, last, email, phone, street, city, state, postal, birthday, customer_id, consultant_id))

        return customer_id

    # Insert new
    if is_sqlite:
        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, created_at, updated_at)
            VALUES
              (?,?,?,?,?,?,?,?,?,?, datetime('now'), datetime('now'))
        """, (consultant_id, first, last, email, phone, street, city, state, postal, birthday))
        return int(cur.lastrowid)

    cur.execute("""
        INSERT INTO customers
          (consultant_id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, created_at, updated_at)
        VALUES
          (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW(), NOW())
        RETURNING id
    """, (consultant_id, first, last, email, phone, street, city, state, postal, birthday))
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
              AND LOWER(first_name) = LOWER(%s)
              AND LOWER(last_name) = LOWER(%s)
            ORDER BY id DESC
            LIMIT 1
        """, (consultant_id, first, last))

    row = cur.fetchone()
    return int(row[0]) if row else None


def create_order_from_confirmed(cur, consultant_id: int, customer_id: int, order_lines: list, source: str = "chat") -> int:
    """
    Create an order + order_items in CRM tables.

    order_lines are your resolved lines with:
      - line["qty"]
      - line["chosen"] dict containing at least: sku, product_name, price
    Returns order_id.
    """
    is_sqlite = _is_sqlite_cursor(cur)

    # Calculate total (best effort). If a price is missing, treat as 0.
    total = 0.0
    for line in order_lines:
        qty = int(line.get("qty") or 1)
        chosen = line.get("chosen") or {}
        price = chosen.get("price")
        try:
            unit_price = float(price) if price is not None else 0.0
        except Exception:
            unit_price = 0.0
        total += unit_price * max(1, qty)

    # Order date = confirmation time (Option A)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert order row
    if is_sqlite:
        cur.execute("""
            INSERT INTO orders (consultant_id, customer_id, order_date, total, source, created_at)
            VALUES (?,?,?,?,?, datetime('now'))
        """, (consultant_id, customer_id, now_iso, total, source))
        order_id = int(cur.lastrowid)
    else:
        cur.execute("""
            INSERT INTO orders (consultant_id, customer_id, order_date, total, source, created_at)
            VALUES (%s,%s, NOW(), %s, %s, NOW())
            RETURNING id
        """, (consultant_id, customer_id, total, source))
        order_id = int(cur.fetchone()[0])

    # Insert items (one row per line, with quantity stored)
    for line in order_lines:
        qty = int(line.get("qty") or 1)
        chosen = line.get("chosen") or {}

        sku = (chosen.get("sku") or "").strip()
        name = (chosen.get("product_name") or chosen.get("name") or "").strip()
        price = chosen.get("price")
        try:
            unit_price = float(price) if price is not None else 0.0
        except Exception:
            unit_price = 0.0

        # Don’t crash if something is weird—just skip that line.
        if not sku or not name:
            continue

        if is_sqlite:
            cur.execute("""
                INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, created_at)
                VALUES (?,?,?,?,?, datetime('now'))
            """, (order_id, sku, name, unit_price, max(1, qty)))
        else:
            cur.execute("""
                INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, created_at)
                VALUES (%s,%s,%s,%s,%s, NOW())
            """, (order_id, sku, name, unit_price, max(1, qty)))

    return order_id

def get_recent_orders_for_customer(cur, customer_id: int, limit: int = 3):
    is_sqlite = _is_sqlite_cursor(cur)

    if is_sqlite:
        cur.execute("""
            SELECT id, order_date, total, source
            FROM orders
            WHERE customer_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (customer_id, limit))
    else:
        cur.execute("""
            SELECT id, order_date, total, source
            FROM orders
            WHERE customer_id = %s
            ORDER BY id DESC
            LIMIT %s
        """, (customer_id, limit))

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

def format_recent_orders(customer_name: str, orders: list) -> str:
    if not orders:
        return f"I don’t see any saved orders for {customer_name} yet."

    lines = [f"Recent orders for {customer_name}:"]

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

        # Removed order number — cleaner
        lines.append(f"\n{od_str} • Total: {total_str}")

        items = o.get("items") or []
        for it in items:
            qty = it.get("quantity") or 1
            name = it.get("product_name") or it.get("sku") or "Item"
            lines.append(f"- {qty} × {name}")

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
          {date_filter}
        GROUP BY c.id, c.first_name, c.last_name, c.phone, c.email
        ORDER BY total_spent DESC, c.last_name, c.first_name
        LIMIT %s
        """
        cur.execute(sql, (consultant_id, *params, limit))

    return _rows_to_dicts(cur)


def format_leaderboard(rows: list, title: str) -> str:
    if not rows:
        return "I don’t see any orders yet for that time period."

    lines = [title]

    for i, r in enumerate(rows, start=1):
        name = f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
        spent = float(r.get("total_spent") or 0)

        lines.append(f"{i}. {name} — ${spent:,.2f}")

    if len(rows) >= 10:
        lines.append("\nWant more? Try: show 20 or top 25 customers.")

    return "\n".join(lines)