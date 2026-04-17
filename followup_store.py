"""
followup_store.py — 2+2+2 follow-up logic for MyPinkAssistant.

Windows (days since order):
  2-day  : days 1–4
  2-week : days 10–18
  2-month: days 50–70
"""
from __future__ import annotations
from urllib.parse import quote
import csv
from pathlib import Path

from db import is_postgres

# Catalog display name overrides for SMS keyed by SKU string
_CATALOG_SMS: dict = {}
def _load_catalog_display() -> None:
    path = Path(__file__).resolve().parent / "catalog" / "en.csv"
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sku = (row.get("sku") or "").strip()
                sms = (row.get("display_name_sms") or "").strip()
                if sku and sms:
                    _CATALOG_SMS[sku] = sms
    except FileNotFoundError:
        pass
_load_catalog_display()

PH = "%s" if is_postgres() else "?"
NOW_SQL = "NOW()" if is_postgres() else "datetime('now')"
_SQLITE = not is_postgres()

# Days-since-order ranges for each window
WINDOWS = {
    2:  (1,  4),
    14: (10, 18),
    60: (50, 70),
}

# Strips MK boilerplate from product names to make them text-friendly
# e.g. "Mary Kay® CC Cream Sunscreen Broad Spectrum SPF 15* - Medium to Deep Natural" → "CC Cream"
def _clean_product_name(product_name: str, sku: str = None) -> str:
    import re
    if sku and str(sku) in _CATALOG_SMS:
        return _CATALOG_SMS[str(sku)]
    name = product_name
    name = re.sub(r"Mary Kay[®\u00ae]?\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[®™\u00ae\u2122\u2020]", "", name)  # ®, ™, †
    name = re.sub(r"\*+", "", name)                      # * and **
    # Remove shade/variant after " - " or " – " (space required on both sides)
    name = re.sub(r"\s+[-–]\s+.+$", "", name)
    name = re.sub(r"\s+Broad\s+Spectrum\s+SPF\s*[\d]+[*]?", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+SPF\s*[\d]+[*]?\s*$", "", name, flags=re.IGNORECASE)
    if not re.search(r"\b(Mineral\s+Facial|Sun\s+Care)\s+Sunscreen\b", name, re.IGNORECASE):
        name = re.sub(r"\s+Sunscreen\b", "", name, flags=re.IGNORECASE)
    name = name.strip(" .,")
    return name or product_name


# Category detection — returns category key
def _detect_color_type(product_lower: str) -> str:
    if "lip gloss" in product_lower:    return "lip gloss"
    if "lip liner" in product_lower:    return "lip liner"
    if "lipstick" in product_lower:     return "lipstick"
    if "lip color" in product_lower:    return "lip color"
    if "shadow" in product_lower:       return "eye shadow"
    if "eyeliner" in product_lower:     return "eyeliner"
    if "lash" in product_lower:         return "mascara"
    if "mascara" in product_lower:      return "mascara"
    if "blush" in product_lower:        return "blush"
    if "bronzer" in product_lower:      return "bronzer"
    if "cc cream" in product_lower:     return "CC Cream"
    if "bb cream" in product_lower:     return "BB Cream"
    if "foundation" in product_lower:   return "foundation"
    if "concealer" in product_lower:    return "concealer"
    return "color"


def _detect_skincare_type(product_lower: str) -> str:
    """Returns a short friendly skincare type word for use in messages."""
    if "serum" in product_lower:        return "serum"
    if "cleanser" in product_lower:     return "cleanser"
    if "toner" in product_lower:        return "toner"
    if "charcoal" in product_lower:      return "charcoal mask"
    if "mask" in product_lower:         return "mask"
    if "eye" in product_lower:          return "eye cream"
    if "microderm" in product_lower:    return "microdermabrasion treatment"
    if "moisturizer" in product_lower:  return "moisturizer"
    if "cream" in product_lower:        return "moisturizer"
    if "repair" in product_lower:       return "repair treatment"
    if "primer" in product_lower:       return "primer"
    return "skincare routine"


def _detect_fragrance_type(product_lower: str) -> str:
    if "cologne" in product_lower:  return "cologne"
    return "perfume"


def _detect_category(product_lower: str) -> str:
    # Body checked before set — "Satin Hands Pampering Set" should be body, not set
    if any(kw in product_lower for kw in ["satin hands", "satin lips", "lotion", "body wash", "body", "hand cream", "foot"]):
        return "body"
    # Fragrance
    if any(kw in product_lower for kw in ["perfume", "cologne", "eau de", "fragrance", "parfum"]):
        return "fragrance"
    # Skincare
    if any(kw in product_lower for kw in ["cleanser", "serum", "moisturizer", "repair", "mask", "toner", "eye cream", "timewise", "microderm", "volu", "skin care", "skincare", "renewal", "lifting"]):
        return "skincare"
    # Color
    if any(kw in product_lower for kw in ["lipstick", "lip gloss", "lip liner", "lip color", "shadow", "mascara", "blush", "bronzer", "foundation", "concealer", "cc cream", "bb cream", "eyeliner", "lash"]):
        return "color"
    # Sets/regimens — specific compound words only, not loose "set" or "collection"
    if any(kw in product_lower for kw in ["regimen", "system", "miracle set", "starter set", "skin care set", "bundle", "go set"]):
        return "set"
    return "fallback"


def _followup_message(product_name: str, customer_first: str, consultant_first: str, is_first_contact: bool, window_days: int, item_count: int = 1, sku: str = None) -> str:
    from followup_scripts import SCRIPTS
    import re as _re

    clean = _clean_product_name(product_name, sku=sku)
    category = _detect_category(product_name.lower())
    window = window_days if window_days in (2, 14, 60) else 2
    slot = "single" if item_count == 1 else "multi"

    template = SCRIPTS[category][slot][window]

    skincare_type   = _detect_skincare_type(product_name.lower())
    color_type      = _detect_color_type(product_name.lower())
    fragrance_type  = _detect_fragrance_type(product_name.lower())

    body = template.format(p=clean, c=customer_first, t=skincare_type, ct=color_type, ft=fragrance_type)

    if is_first_contact:
        # Strip any opening "Hey {name}, " or "Hey {name}! " and inject the intro
        for prefix in (f"Hey {customer_first}, ", f"Hey {customer_first}! "):
            if body.startswith(prefix):
                rest = body[len(prefix):]
                rest = rest[0].upper() + rest[1:] if rest else rest
                return f"Hey {customer_first}, It's {consultant_first}, your Mary Kay girl! {rest}"
        # Template has no greeting — prepend full intro
        return f"Hey {customer_first}, It's {consultant_first}, your Mary Kay girl! {body}"

    return body


def _pick_hero_item(items: list[dict]) -> dict:
    """Pick the highest-priced item from an order as the hero product."""
    if not items:
        return {}
    return max(items, key=lambda i: float(i.get("unit_price") or 0))


def get_pending_followups(cur, consultant_id: int, offset: int = 0, limit: int = 5) -> list[dict]:
    """
    Return up to `limit` pending follow-ups for a consultant, most overdue first.
    Each result dict has: followup_id, order_id, customer_id, first_name, last_name,
    phone, product_name, followup_window, days_since_order, sms_body, is_first_contact
    """
    is_sqlite = _SQLITE

    # Build date-window conditions
    # We union across all three windows so we can sort by overdue-ness
    if is_sqlite:
        window_sql = """
            SELECT
                o.id            AS order_id,
                o.customer_id,
                o.order_date,
                c.first_name,
                c.last_name,
                c.phone,
                CAST(julianday('now') - julianday(o.order_date) AS INTEGER) AS days_ago,
                CASE
                    WHEN CAST(julianday('now') - julianday(o.order_date) AS INTEGER) BETWEEN 1  AND 4  THEN 2
                    WHEN CAST(julianday('now') - julianday(o.order_date) AS INTEGER) BETWEEN 10 AND 18 THEN 14
                    WHEN CAST(julianday('now') - julianday(o.order_date) AS INTEGER) BETWEEN 50 AND 70 THEN 60
                    ELSE NULL
                END AS window_days
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.consultant_id = ?
              AND c.consultant_id = ?
              AND COALESCE(c.source_status, 'active') = 'active'
        """
    else:
        window_sql = """
            SELECT
                o.id            AS order_id,
                o.customer_id,
                o.order_date,
                c.first_name,
                c.last_name,
                c.phone,
                EXTRACT(DAY FROM NOW() - o.order_date::timestamptz)::INT AS days_ago,
                CASE
                    WHEN EXTRACT(DAY FROM NOW() - o.order_date::timestamptz)::INT BETWEEN 1  AND 4  THEN 2
                    WHEN EXTRACT(DAY FROM NOW() - o.order_date::timestamptz)::INT BETWEEN 10 AND 18 THEN 14
                    WHEN EXTRACT(DAY FROM NOW() - o.order_date::timestamptz)::INT BETWEEN 50 AND 70 THEN 60
                    ELSE NULL
                END AS window_days
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.consultant_id = %s
              AND c.consultant_id = %s
              AND COALESCE(c.source_status, 'active') = 'active'
        """

    PH2 = "?" if is_sqlite else "%s"

    full_sql = f"""
        SELECT w.order_id, w.customer_id, w.first_name, w.last_name, w.phone,
               w.days_ago, w.window_days
        FROM ({window_sql}) w
        WHERE w.window_days IS NOT NULL
          AND w.phone IS NOT NULL AND w.phone <> ''
          AND NOT EXISTS (
              SELECT 1 FROM customer_followups cf
              WHERE cf.order_id = w.order_id
                AND cf.followup_window = w.window_days
                AND cf.completed_at IS NOT NULL
          )
        ORDER BY w.days_ago DESC
        LIMIT {PH2} OFFSET {PH2}
    """

    cur.execute(full_sql, (consultant_id, consultant_id, limit, offset))

    rows = cur.fetchall()
    if not rows:
        return []

    def _g(row, key, idx):
        try:
            if isinstance(row, dict):
                return row.get(key)
            return row[idx]
        except Exception:
            return None

    results = []
    for row in rows:
        order_id    = _g(row, "order_id",    0)
        customer_id = _g(row, "customer_id", 1)
        first_name  = _g(row, "first_name",  2) or ""
        last_name   = _g(row, "last_name",   3) or ""
        phone       = _g(row, "phone",       4) or ""
        days_ago    = _g(row, "days_ago",    5) or 0
        window_days = _g(row, "window_days", 6)

        # Fetch order items for this order
        if is_sqlite:
            cur.execute("SELECT sku, product_name, unit_price, quantity FROM order_items WHERE order_id = ?", (order_id,))
        else:
            cur.execute("SELECT sku, product_name, unit_price, quantity FROM order_items WHERE order_id = %s", (order_id,))
        item_rows = cur.fetchall()
        items = []
        for ir in item_rows:
            if isinstance(ir, dict):
                items.append(ir)
            else:
                items.append({"sku": ir[0], "product_name": ir[1], "unit_price": ir[2], "quantity": ir[3]})

        hero = _pick_hero_item(items)
        product_name = hero.get("product_name") or "your recent products"
        hero_sku = hero.get("sku") or None

        # Check if this is first contact (no completed followup for this customer)
        if is_sqlite:
            cur.execute(
                "SELECT 1 FROM customer_followups WHERE customer_id = ? AND consultant_id = ? AND completed_at IS NOT NULL LIMIT 1",
                (customer_id, consultant_id),
            )
        else:
            cur.execute(
                "SELECT 1 FROM customer_followups WHERE customer_id = %s AND consultant_id = %s AND completed_at IS NOT NULL LIMIT 1",
                (customer_id, consultant_id),
            )
        is_first_contact = cur.fetchone() is None

        results.append({
            "order_id":         order_id,
            "customer_id":      customer_id,
            "first_name":       first_name,
            "last_name":        last_name,
            "phone":            phone,
            "days_ago":         days_ago,
            "window_days":      window_days,
            "product_name":     product_name,
            "hero_sku":         hero_sku,
            "item_count":       len(items),
            "is_first_contact": is_first_contact,
        })

    return results


def complete_followup(cur, consultant_id: int, order_id: int, followup_window: int) -> bool:
    """Mark a follow-up as completed. Upserts the row. Returns True on success."""
    if is_postgres():
        cur.execute(
            f"""
            INSERT INTO customer_followups (consultant_id, customer_id, order_id, followup_window, completed_at)
            SELECT %s, o.customer_id, %s, %s, NOW()
            FROM orders o WHERE o.id = %s AND o.consultant_id = %s
            ON CONFLICT (order_id, followup_window)
            DO UPDATE SET completed_at = NOW()
            """,
            (consultant_id, order_id, followup_window, order_id, consultant_id),
        )
    else:
        cur.execute(
            """
            SELECT customer_id FROM orders WHERE id = ? AND consultant_id = ?
            """,
            (order_id, consultant_id),
        )
        row = cur.fetchone()
        if not row:
            return False
        customer_id = row[0] if not isinstance(row, dict) else row["customer_id"]
        cur.execute(
            """
            INSERT INTO customer_followups (consultant_id, customer_id, order_id, followup_window, completed_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(order_id, followup_window) DO UPDATE SET completed_at = datetime('now')
            """,
            (consultant_id, customer_id, order_id, followup_window),
        )
    return True


def get_pending_birthday_followups(cur, consultant_id: int) -> list[dict]:
    """Return customers with a birthday this month that haven't been texted yet this year."""
    PH = "?" if _SQLITE else "%s"
    if _SQLITE:
        cur.execute(
            """
            SELECT c.id, c.first_name, c.last_name, c.phone,
                   CAST(CASE
                     WHEN c.birthday LIKE '____-__-__'
                       THEN strftime('%m', c.birthday)
                     ELSE substr(c.birthday, 1, instr(c.birthday, '-') - 1)
                   END AS INTEGER) AS bday_month,
                   CAST(CASE
                     WHEN c.birthday LIKE '____-__-__'
                       THEN strftime('%d', c.birthday)
                     ELSE substr(c.birthday, instr(c.birthday, '-') + 1)
                   END AS INTEGER) AS bday_day
            FROM customers c
            WHERE c.consultant_id = ?
              AND c.birthday IS NOT NULL AND c.birthday <> ''
              AND CAST(CASE
                    WHEN c.birthday LIKE '____-__-__'
                      THEN strftime('%m', c.birthday)
                    ELSE substr(c.birthday, 1, instr(c.birthday, '-') - 1)
                  END AS INTEGER) = CAST(strftime('%m', 'now') AS INTEGER)
              AND c.phone IS NOT NULL AND c.phone <> ''
              AND COALESCE(c.source_status, 'active') = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM customer_birthday_followups bf
                  WHERE bf.customer_id = c.id
                    AND bf.consultant_id = ?
                    AND bf.year = CAST(strftime('%Y', 'now') AS INTEGER)
                    AND bf.completed_at IS NOT NULL
              )
            ORDER BY bday_day ASC
            """,
            (consultant_id, consultant_id),
        )
    else:
        cur.execute(
            """
            SELECT c.id, c.first_name, c.last_name, c.phone,
                   CASE
                     WHEN c.birthday ~ '^\\d{4}-\\d{2}-\\d{2}$'
                       THEN EXTRACT(MONTH FROM c.birthday::date)::INT
                     ELSE SPLIT_PART(c.birthday, '-', 1)::INT
                   END AS bday_month,
                   CASE
                     WHEN c.birthday ~ '^\\d{4}-\\d{2}-\\d{2}$'
                       THEN EXTRACT(DAY FROM c.birthday::date)::INT
                     ELSE SPLIT_PART(c.birthday, '-', 2)::INT
                   END AS bday_day
            FROM customers c
            WHERE c.consultant_id = %s
              AND c.birthday IS NOT NULL AND c.birthday <> ''
              AND (
                CASE
                  WHEN c.birthday ~ '^\\d{4}-\\d{2}-\\d{2}$'
                    THEN EXTRACT(MONTH FROM c.birthday::date)::INT
                  ELSE SPLIT_PART(c.birthday, '-', 1)::INT
                END
              ) = EXTRACT(MONTH FROM NOW())::INT
              AND c.phone IS NOT NULL AND c.phone <> ''
              AND COALESCE(c.source_status, 'active') = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM customer_birthday_followups bf
                  WHERE bf.customer_id = c.id
                    AND bf.consultant_id = %s
                    AND bf.year = EXTRACT(YEAR FROM NOW())::INT
                    AND bf.completed_at IS NOT NULL
              )
            ORDER BY bday_day ASC
            """,
            (consultant_id, consultant_id),
        )

    rows = cur.fetchall()
    results = []
    for row in rows:
        def _g(key, idx):
            try:
                return row[key] if isinstance(row, dict) else row[idx]
            except Exception:
                return None

        customer_id = _g("id", 0)
        first_name  = _g("first_name", 1) or ""
        last_name   = _g("last_name", 2) or ""
        phone       = _g("phone", 3) or ""
        bday_month  = _g("bday_month", 4)
        bday_day    = _g("bday_day", 5)

        import calendar as _cal
        bday_month_name = _cal.month_name[bday_month] if bday_month else ""

        # first contact check
        if _SQLITE:
            cur.execute(
                "SELECT 1 FROM customer_followups WHERE customer_id = ? AND consultant_id = ? AND completed_at IS NOT NULL LIMIT 1",
                (customer_id, consultant_id),
            )
        else:
            cur.execute(
                "SELECT 1 FROM customer_followups WHERE customer_id = %s AND consultant_id = %s AND completed_at IS NOT NULL LIMIT 1",
                (customer_id, consultant_id),
            )
        is_first_contact = cur.fetchone() is None

        # also check birthday followups for first contact
        if is_first_contact:
            if _SQLITE:
                cur.execute(
                    "SELECT 1 FROM customer_birthday_followups WHERE customer_id = ? AND consultant_id = ? AND completed_at IS NOT NULL LIMIT 1",
                    (customer_id, consultant_id),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM customer_birthday_followups WHERE customer_id = %s AND consultant_id = %s AND completed_at IS NOT NULL LIMIT 1",
                    (customer_id, consultant_id),
                )
            is_first_contact = cur.fetchone() is None

        results.append({
            "card_type":        "birthday",
            "customer_id":      customer_id,
            "first_name":       first_name,
            "last_name":        last_name,
            "phone":            phone,
            "bday_day":         bday_day,
            "bday_month_name":  bday_month_name,
            "is_first_contact": is_first_contact,
        })

    return results


def complete_birthday_followup(cur, consultant_id: int, customer_id: int) -> bool:
    """Mark a birthday followup done for the current year."""
    if is_postgres():
        cur.execute(
            """
            INSERT INTO customer_birthday_followups (consultant_id, customer_id, year, completed_at)
            VALUES (%s, %s, EXTRACT(YEAR FROM NOW())::INT, NOW())
            ON CONFLICT (customer_id, consultant_id, year)
            DO UPDATE SET completed_at = NOW()
            """,
            (consultant_id, customer_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO customer_birthday_followups (consultant_id, customer_id, year, completed_at)
            VALUES (?, ?, CAST(strftime('%Y', 'now') AS INTEGER), datetime('now'))
            ON CONFLICT(customer_id, consultant_id, year) DO UPDATE SET completed_at = datetime('now')
            """,
            (consultant_id, customer_id),
        )
    return True


def _birthday_message(customer_first: str, consultant_first: str, is_first_contact: bool) -> str:
    msg = f"Hey {customer_first}! Wishing you a wonderful birthday today! I hope your day is as beautiful as you are! 🎂"
    if is_first_contact:
        return f"Hey {customer_first}, It's {consultant_first}, your Mary Kay girl! Wishing you a wonderful birthday today! I hope your day is as beautiful as you are! 🎂"
    return msg


def _window_label(window_days: int) -> str:
    if window_days == 2:
        return "2-day follow-up"
    if window_days == 14:
        return "2-week follow-up"
    if window_days == 60:
        return "2-month follow-up"
    return "follow-up"


def render_followup_cards(followups: list[dict], consultant_first: str) -> str:
    if not followups:
        return "You're all caught up on follow-ups! 🎉"

    import html as _html
    parts = ['<div class="followup-list">']
    for f in followups:
        first     = f["first_name"]
        last      = f["last_name"]
        phone     = f["phone"]
        is_first  = f["is_first_contact"]
        clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")

        if f.get("card_type") == "birthday":
            customer_id      = f["customer_id"]
            bday_day         = f["bday_day"]
            bday_month_name  = f["bday_month_name"]
            sms_text    = _birthday_message(first, consultant_first, is_first)
            sms_uri     = f"sms:{clean_phone}&body={quote(sms_text)}"
            msg_attr    = _html.escape(sms_text, quote=True)
            parts.append(
                f'<div class="followup-card" data-card-type="birthday" data-customer-id="{customer_id}" data-phone="{clean_phone}" data-msg="{msg_attr}" data-sms="{sms_uri}">'
                f'<button class="followup-circle" data-card-type="birthday" data-customer-id="{customer_id}" aria-label="Send birthday text">○</button>'
                f'<div class="followup-info">'
                f'<span class="followup-name">{first} {last}</span>'
                f'<span class="followup-meta">🎂 Birthday &bull; {bday_month_name} {bday_day}</span>'
                f'</div>'
                f'</div>'
            )
        else:
            order_id   = f["order_id"]
            window     = f["window_days"]
            product    = f["product_name"]
            hero_sku   = f.get("hero_sku")
            item_count = f["item_count"]
            days_ago   = f["days_ago"]

            label         = _window_label(window)
            sms_text      = _followup_message(product, first, consultant_first, is_first, window, item_count=item_count, sku=hero_sku)
            sms_uri       = f"sms:{clean_phone}&body={quote(sms_text)}"
            clean_product = _clean_product_name(product, sku=hero_sku)
            extra         = f" +{item_count - 1} more" if item_count > 1 else ""
            product_meta  = f"{clean_product}{extra}"
            msg_attr      = _html.escape(sms_text, quote=True)
            parts.append(
                f'<div class="followup-card" data-card-type="order" data-order="{order_id}" data-window="{window}" data-phone="{clean_phone}" data-msg="{msg_attr}" data-sms="{sms_uri}">'
                f'<button class="followup-circle" data-card-type="order" data-order-id="{order_id}" data-window-id="{window}" aria-label="Send text">○</button>'
                f'<div class="followup-info">'
                f'<span class="followup-name">{first} {last}</span>'
                f'<span class="followup-meta">{label} &bull; ordered {days_ago}d ago &bull; {product_meta}</span>'
                f'</div>'
                f'</div>'
            )

    parts.append('</div>')
    return "\n".join(parts)
