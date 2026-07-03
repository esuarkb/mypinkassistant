"""Cross-customer/aggregate questions answered via text-to-SQL over the
CRM tables (customers, orders, order_items).
"""
import datetime
import json
import re

from openai import OpenAI

from .config import MODEL
from .types import ChatReply
from .ui_text import UI_EN


_CRM_SCHEMA = {
    "customers": (
        "Customer records for this consultant. "
        "Columns: id, consultant_id, first_name, last_name, email, phone, "
        "street, city, state (2-letter code, e.g. 'AL', 'TN'), postal_code, "
        "birthday (TEXT, YYYY-MM-DD), notes, tags (comma-separated text), "
        "source_status (TEXT: 'active' or 'removed' — removed means no longer in MyCustomers), "
        "created_at (ISO timestamp)."
    ),
    "orders": (
        "Orders placed by customers. "
        "Columns: id, consultant_id, customer_id (FK to customers.id), "
        "order_date (TEXT stored as ISO timestamp e.g. '2025-05-15 10:23:00'), "
        "total (REAL, retail price), "
        "source (text: 'myshop' or 'cds' for online orders, NULL for consultant-entered). "
        "Join to customers via: customers.id = orders.customer_id. "
        "ALWAYS filter both tables: c.consultant_id = {consultant_id} AND o.consultant_id = {consultant_id}. "
        "order_date is TEXT — use SUBSTR for date filtering: "
        "SUBSTR(o.order_date, 1, 7) = 'YYYY-MM' for a specific month, "
        "SUBSTR(o.order_date, 1, 4) = 'YYYY' for a specific year."
    ),
    "order_items": (
        "Line items within each order. "
        "Columns: id, order_id (FK to orders.id), sku, product_name (TEXT, full product name), "
        "unit_price (REAL), quantity (INTEGER). "
        "Join to orders via: orders.id = order_items.order_id. "
        "Use LOWER(oi.product_name) LIKE LOWER('%keyword%') for product name searches."
    ),
}

_CRM_SQL_SYSTEM = """\
You generate SQL SELECT queries for a Mary Kay consultant's customer and order data.
Use standard SQL compatible with both SQLite and PostgreSQL.

{schema}

Today's date: {today}
Current month (YYYY-MM): {this_month}
Last month (YYYY-MM): {last_month}
Current year: {this_year}

Rules:
- Return ONLY a raw SQL SELECT statement — no markdown, no explanation, no semicolon at the end
- ALWAYS include consultant_id = {consultant_id} on every table queried
- When joining, always qualify consultant_id with a table alias (e.g. c.consultant_id = {consultant_id})
- Do not use LIMIT unless the user asks for a specific number
- Always SELECT first_name, last_name from customers when returning individual customers
- Use table aliases: customers AS c, orders AS o, order_items AS oi
- order_date is a timestamp column — use date range comparisons for filtering (works on both SQLite and PostgreSQL). Always use >= start AND < exclusive_end:
  - This month:  o.order_date >= '{this_month}-01' AND o.order_date < '{next_month}-01'
  - Last month:  o.order_date >= '{last_month}-01' AND o.order_date < '{this_month}-01'
  - This year:   o.order_date >= '{this_year}-01-01' AND o.order_date < '{next_year}-01-01'
  - Specific month (e.g. May 2025): o.order_date >= '2025-05-01' AND o.order_date < '2025-06-01'
  - Specific year (e.g. 2025): o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'
  - Do NOT use SUBSTR, EXTRACT, or DATE_PART on order_date
- For aggregate queries (COUNT, SUM), use clear aliases: order_count, total_sales, customer_count
- When counting or listing customers, always filter c.source_status = 'active' unless the user explicitly asks about removed or former customers
- For product name searches, use a separate LIKE condition for each meaningful search term rather than one combined phrase — e.g., to find 'ivory 2 pressed powder' use LOWER(oi.product_name) LIKE '%ivory 2%' AND LOWER(oi.product_name) LIKE '%pressed powder%' rather than LIKE '%ivory 2 pressed powder%'. This correctly handles products where the shade or color code appears at the end of the name (e.g. 'Mineral Pressed Powder - Ivory 2').
- For product name searches, always use singular forms: 'set' not 'sets', 'kit' not 'kits', 'cream' not 'creams'. Plural user input should be singularized before matching.
- When the user asks who ordered a product, return distinct customers (use DISTINCT or GROUP BY)
- When counting or summing, return a single row with a descriptive column alias
- To count how many times a customer has ordered, count rows in the orders table (each order = one row). Do NOT join order_items to determine order frequency — that counts line items, not orders.
- When grouping customers, always include c.id in the GROUP BY clause (e.g. GROUP BY c.id, c.first_name, c.last_name) to correctly handle customers with the same name.
- Keep queries simple and readable"""


def _handle_data_query(msg: str, consultant_id: int, ui: dict = None) -> "ChatReply":
    if ui is None:
        ui = UI_EN

    from db import tx, is_postgres
    import re as _re

    _ph = "%s" if is_postgres() else "?"

    _today = datetime.date.today()
    _today_str = _today.isoformat()
    _this_month = _today_str[:7]
    _first_of_month = _today.replace(day=1)
    _last_month_date = _first_of_month - datetime.timedelta(days=1)
    _last_month = _last_month_date.strftime("%Y-%m")
    _this_year = str(_today.year)
    _next_year = str(_today.year + 1)
    _next_month_date = (_first_of_month.replace(month=_first_of_month.month % 12 + 1)
                        if _first_of_month.month < 12
                        else _first_of_month.replace(year=_first_of_month.year + 1, month=1))
    _next_month = _next_month_date.strftime("%Y-%m")

    schema_lines = []
    for tbl, desc in _CRM_SCHEMA.items():
        schema_lines.append(f"Table: {tbl}\n  {desc.format(consultant_id=consultant_id)}")
    schema_text = "\n\n".join(schema_lines)

    system = _CRM_SQL_SYSTEM.format(
        schema=schema_text,
        consultant_id=consultant_id,
        today=_today_str,
        this_month=_this_month,
        last_month=_last_month,
        this_year=_this_year,
        next_year=_next_year,
        next_month=_next_month,
    )

    # Normalize plural product category words so LIKE clauses use singular forms
    _product_plural_map = [
        (r'\bsets\b', 'set'), (r'\bkits\b', 'kit'), (r'\bcreams\b', 'cream'),
        (r'\bfoundations\b', 'foundation'), (r'\bprimers\b', 'primer'),
        (r'\bserums\b', 'serum'), (r'\bmoisturizers\b', 'moisturizer'),
        (r'\bcleansers\b', 'cleanser'), (r'\bconcealers\b', 'concealer'),
        (r'\bpowders\b', 'powder'), (r'\bhighlighters\b', 'highlighter'),
        (r'\bshadows\b', 'shadow'), (r'\beyeliners\b', 'eyeliner'),
        (r'\bmascaras\b', 'mascara'), (r'\bbrushes\b', 'brush'),
        (r'\bmasks\b', 'mask'), (r'\bwipes\b', 'wipe'),
        (r'\blotions\b', 'lotion'), (r'\bscrubs\b', 'scrub'),
        (r'\btoners\b', 'toner'), (r'\bbalms\b', 'balm'),
        (r'\bsticks\b', 'stick'), (r'\bpencils\b', 'pencil'),
        (r'\bgels\b', 'gel'), (r'\blipsticks\b', 'lipstick'),
        (r'\bbronzers\b', 'bronzer'), (r'\blotions\b', 'lotion'),
    ]
    _msg_for_query = msg
    for _pat, _repl in _product_plural_map:
        _msg_for_query = _re.sub(_pat, _repl, _msg_for_query, flags=_re.IGNORECASE)

    client = OpenAI()
    try:
        resp = client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Question: {_msg_for_query}"},
            ],
            timeout=30,
        )
        sql = ""
        try:
            for out in (resp.output or []):
                for c in (getattr(out, "content", None) or []):
                    t = getattr(c, "text", None)
                    if t:
                        sql += t
            sql = sql.strip().rstrip(";").strip()
        except Exception:
            sql = ""
    except Exception as e:
        print(f"[DataQuery] LLM error: {e}")
        return ChatReply(ui["data_query_rephrase"])

    if not sql:
        return ChatReply(ui["data_query_rephrase"])

    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        print(f"[DataQuery] Rejected non-SELECT: {sql[:100]}")
        return ChatReply(ui["data_query_rephrase"])

    forbidden = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE")
    if any(kw in sql_upper for kw in forbidden):
        print(f"[DataQuery] Rejected destructive SQL: {sql[:100]}")
        return ChatReply(ui["data_query_rephrase"])

    if str(consultant_id) not in sql:
        print(f"[DataQuery] Missing consultant_id, injecting: {sql[:100]}")
        sql = f"SELECT * FROM ({sql}) AS q WHERE consultant_id = {consultant_id}"

    sql = _re.sub(r"CURRENT_DATE", f"'{_today_str}'", sql, flags=_re.IGNORECASE)
    sql = _re.sub(r"date\s*\(\s*'now'\s*\)", f"'{_today_str}'", sql, flags=_re.IGNORECASE)

    print(f"[DataQuery] Executing: {sql[:400]}")

    try:
        with tx() as (conn, cur):
            cur.execute(sql)
            raw_rows = cur.fetchall()
            if raw_rows and not hasattr(raw_rows[0], "keys") and cur.description:
                col_names = [d[0] for d in cur.description]
                rows = [dict(zip(col_names, r)) for r in raw_rows]
            else:
                rows = [dict(r) if hasattr(r, "keys") else r for r in raw_rows] if raw_rows else []
    except Exception as e:
        print(f"[DataQuery] DB error: {e}")
        return ChatReply(ui["data_query_error"])

    return ChatReply(_format_data_query_results(rows, msg, ui=ui))


def _format_data_query_results(rows: list, original_msg: str, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    if not rows:
        return ui["data_query_no_results"]

    if hasattr(rows[0], "keys"):
        dicts = [dict(r) for r in rows]
    elif hasattr(rows[0], "_fields"):
        dicts = [r._asdict() for r in rows]
    else:
        dicts = rows

    if not dicts:
        return ui["data_query_no_results"]

    cols = list(dicts[0].keys())
    import html as _html

    _SUPPRESS = {"consultant_id", "created_at", "updated_at", "customer_id", "order_id",
                 "street", "street2", "email", "phone", "postal_code", "notes", "tags",
                 "birthday", "id", "intouch_account_ids"}
    _MONEY_COLS = {"total", "total_spent", "total_sales", "unit_price", "revenue", "amount", "subtotal"}
    _SHOW_DETAIL = 20

    def _fmt_val(col: str, val) -> str:
        if val is None:
            return ""
        col_l = col.lower()
        if col_l in _MONEY_COLS or "total" in col_l or "spent" in col_l or "revenue" in col_l or "price" in col_l:
            try:
                return f"${float(val):,.2f}"
            except Exception:
                pass
        if "date" in col_l:
            return str(val)[:10]
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        return str(val)

    def _name(d: dict) -> str:
        fn = (d.get("first_name") or "").strip()
        ln = (d.get("last_name") or "").strip()
        return f"{fn} {ln}".strip() or "Unknown"

    def _name_link(d: dict) -> str:
        n = _name(d)
        safe = _html.escape(n)
        return f'<a href="#" data-send="{safe}">{safe}</a>'

    # Pure aggregate: single row, no name/id columns, only numeric summary cols
    _AGG_HINTS = {"count", "total", "order_count", "customer_count", "total_spent", "total_sales",
                  "revenue", "sum", "avg", "average", "num_orders"}
    is_single_agg = (
        len(dicts) == 1
        and not any(c in cols for c in ("first_name", "last_name", "id", "customer_id"))
        and any(
            c.lower() in _AGG_HINTS or c.lower().startswith("count") or c.lower().startswith("total")
            or c.lower().startswith("sum") or c.lower().startswith("num_")
            for c in cols
        )
    )
    if is_single_agg:
        parts = []
        for k, v in dicts[0].items():
            if v is None:
                continue
            label = k.replace("_", " ").title()
            parts.append(f"{label}: {_fmt_val(k, v)}")
        return "\n".join(parts) if parts else str(dicts[0])

    has_name = "first_name" in cols and "last_name" in cols
    value_cols = [c for c in cols if c not in _SUPPRESS and c not in ("first_name", "last_name")]

    # Names only
    if has_name and not value_cols:
        links = [_name_link(d) for d in dicts]
        n = len(links)
        header = f"{n} customer{'s' if n != 1 else ''}:"
        shown = links[:_SHOW_DETAIL]
        rest = links[_SHOW_DETAIL:]
        body = "\n".join(f"• {lnk}" for lnk in shown)
        if rest:
            rest_body = "\n".join(f"• {lnk}" for lnk in rest)
            body += (
                f"\n<details><summary style='cursor:pointer;color:var(--pink);font-weight:600'>"
                f"+ {len(rest)} more</summary>\n{rest_body}\n</details>"
            )
        return f"{header}\n{body}"

    # Names + value columns
    if has_name and len(value_cols) <= 5:
        n = len(dicts)
        header = f"{n} customer{'s' if n != 1 else ''}:"
        lines = [header]
        shown_dicts = dicts[:_SHOW_DETAIL]
        rest_dicts = dicts[_SHOW_DETAIL:]
        for d in shown_dicts:
            detail_parts = [_fmt_val(c, d.get(c)) for c in value_cols if d.get(c) is not None]
            detail = " — " + ", ".join(p for p in detail_parts if p) if detail_parts else ""
            lines.append(f"• {_name_link(d)}{detail}")
        if rest_dicts:
            rest_lines = []
            for d in rest_dicts:
                detail_parts = [_fmt_val(c, d.get(c)) for c in value_cols if d.get(c) is not None]
                detail = " — " + ", ".join(p for p in detail_parts if p) if detail_parts else ""
                rest_lines.append(f"• {_name_link(d)}{detail}")
            lines.append(
                f"<details><summary style='cursor:pointer;color:var(--pink);font-weight:600'>"
                f"+ {len(rest_dicts)} more</summary>\n" + "\n".join(rest_lines) + "\n</details>"
            )
        return "\n".join(lines)

    # Fallback: tabular rows (e.g. orders-per-month breakdown)
    result_lines = []
    for d in dicts[:50]:
        parts = []
        for k, v in d.items():
            if k in _SUPPRESS or v is None:
                continue
            label = k.replace("_", " ").title()
            parts.append(f"{label}: {_fmt_val(k, v)}")
        if parts:
            result_lines.append("• " + " · ".join(parts))
    return "\n".join(result_lines) if result_lines else ui["data_query_no_results"]
