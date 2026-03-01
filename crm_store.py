# crm_store.py
from __future__ import annotations
from typing import Any, Dict, List, Optional


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


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


def find_customers_by_name(cur, consultant_id: int, name: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = (name or "").strip()
    parts = [p for p in q.replace(",", " ").split() if p]
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else first

    like_last = f"%{last.lower()}%"
    like_first = f"%{first.lower()}%"

    if _is_sqlite_cursor(cur):
        sql = """
        SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
        FROM customers
        WHERE consultant_id = ?
          AND (LOWER(last_name) LIKE ? OR LOWER(first_name) LIKE ?)
        ORDER BY last_name, first_name
        LIMIT ?
        """
        params = (consultant_id, like_last, like_first, limit)
    else:
        sql = """
        SELECT id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, notes
        FROM customers
        WHERE consultant_id = %s
          AND (LOWER(last_name) LIKE %s OR LOWER(first_name) LIKE %s)
        ORDER BY last_name, first_name
        LIMIT %s
        """
        params = (consultant_id, like_last, like_first, limit)

    cur.execute(sql, params)
    return _rows_to_dicts(cur)


def format_customer_card(c: Dict[str, Any]) -> str:
    full_name = f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip()
    addr_parts = [c.get("street"), c.get("city"), c.get("state"), c.get("postal_code")]
    addr = ", ".join([str(p).strip() for p in addr_parts if p and str(p).strip()])

    lines = [
        f"**{full_name or 'Customer'}**",
        f"- Email: {c.get('email') or '—'}",
        f"- Phone: {c.get('phone') or '—'}",
        f"- Address: {addr or '—'}",
        f"- Birthday: {c.get('birthday') or '—'}",
    ]
    if c.get("notes"):
        lines.append(f"- Notes: {c.get('notes')}")
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
    street = (customer.get("Address") or "").strip() or None
    city = (customer.get("City") or "").strip() or None
    state = (customer.get("State") or "").strip() or None
    postal = (customer.get("Zip") or customer.get("Postal Code") or "").strip() or None
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


def format_recent_orders(customer_name: str, orders: list) -> str:
    if not orders:
        return f"I don’t see any saved orders for **{customer_name}** yet."

    lines = [f"**Recent orders for {customer_name}:**"]
    for o in orders:
        # order_date can be ISO string (sqlite) or datetime (pg). Convert to string safely.
        od = o.get("order_date")
        od_str = str(od)[:10] if od else "—"  # YYYY-MM-DD

        total = o.get("total")
        total_str = f"${float(total):.2f}" if total is not None else "—"

        lines.append(f"\n**Order #{o['id']}** • {od_str} • Total: {total_str}")

        items = o.get("items") or []
        for it in items:
            qty = it.get("quantity") or 1
            name = it.get("product_name") or it.get("sku") or "Item"
            lines.append(f"- {qty} × {name}")

    return "\n".join(lines)