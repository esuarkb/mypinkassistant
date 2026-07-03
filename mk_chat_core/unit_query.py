"""Director feature: team/unit questions answered via text-to-SQL over the
synced report tables (unit_members, great_start, star_tracking, ...).
"""
import json
import re

from openai import OpenAI

from .config import MODEL, model_kwargs
from .types import ChatReply
from .ui_text import UI_EN


_UNIT_SCHEMA = {
    "unit_members": (
        "All unit members synced from InTouch. "
        "Columns: consultant_id, intouch_contact_id, consultant_number, "
        "first_name, last_name, email, phone, address, city, state, zip, "
        "career_level_code, career_level_desc (e.g. 'Conslt', 'Sr Conslt', 'Star Tm Bldr', 'DIQ', 'DIR'), "
        "activity_status — codes are always stored without spaces (A1, A2, A3=active; "
        "T1-T7=terminating, T6/T7=last month; I1, I2, I3=inactive; N1, N2, N3=new). "
        "If the user gives a full code with a number (e.g. 'T3', 'i3', 'I 3', 'a2'), ALWAYS use exact match: activity_status = 'T3'. "
        "Only use LIKE 'T%' when the user says just the letter with no number (e.g. 'show T status', 'who is terminating'). "
        "language (English or Spanish), myshop_active (1=yes, 0=no or never created), "
        "birthday, start_date, "
        "last_order_date (date of their most recent InTouch order — to find who has ordered this month use: "
        "last_order_date >= DATE_TRUNC('month', CURRENT_DATE); to find who has NOT ordered this month: "
        "last_order_date < DATE_TRUNC('month', CURRENT_DATE) OR last_order_date IS NULL; "
        "always include last_order_date and last_order_wholesale in SELECT when answering order-activity questions), "
        "last_order_wholesale (wholesale $ amount of their most recent order), "
        "last_order_retail (retail $ amount of their most recent order), "
        "unit_number, segments (semicolon-separated contest/program tags), "
        "is_personal_recruit (1=personally recruited by this consultant, 0=in unit via downline), "
        "recruiter_info (text containing the recruiter's name in format 'First Name: X, Last Name: Y, Email: ...' — "
        "to find members recruited by a specific person use: "
        "recruiter_info LIKE '%First Name: Jamila%' AND recruiter_info LIKE '%Last Name: Saqqa%'), "
        "sync_status ('active' = currently on team in InTouch; 'removed' = no longer appears in InTouch, terminated). "
        "ALWAYS filter WHERE sync_status = 'active' unless the user specifically asks about former or terminated consultants. "
        "synced_at"
    ),
    "unit_great_start": (
        "Great Start bundle tracking for new consultants (current month). "
        "Columns: consultant_id, consultant_number, total_bundles, needed_next_bundle ($ still needed for next bundle — NULL means window expired), "
        "promotion_end_date (when the Great Start window closes), total_production, rsks_bundles, rsks_production_left, "
        "production_month_key, synced_at. "
        "Join to unit_members via consultant_number. "
        "IMPORTANT: always filter WHERE promotion_end_date >= CURRENT_DATE to exclude consultants whose window has already closed, "
        "unless the user specifically asks about expired or past consultants. "
        "Always include promotion_end_date in the SELECT when querying this table so the window end date is visible. "
        "When the query is about who is close to or working toward a bundle, ORDER BY needed_next_bundle ASC (lowest need first)."
    ),
    "unit_star_tracking": (
        "Star Consultant contest tracking for current quarter. "
        "Columns: consultant_id, consultant_number, contest_amount ($ produced this quarter), "
        "level_name (NULL=no level yet, 'Ruby'=achieved Ruby, 'Diamond', 'Emerald', 'Pearl' — levels in ascending order), "
        "needed_ruby, needed_diamond, needed_emerald, needed_pearl "
        "($ still needed for that level — 0 means already achieved, > 0 means still working toward it). "
        "Join to unit_members via consultant_number. "
        "IMPORTANT: level_name is stored as SQL NULL (not the string 'None') — always use IS NULL / IS NOT NULL. "
        "To find consultants still working toward Ruby: needed_ruby > 0. "
        "To find their NEXT level: if level_name = 'Ruby' → show needed_diamond; "
        "if level_name = 'Diamond' → show needed_emerald; if level_name = 'Emerald' → show needed_pearl; "
        "if level_name IS NULL → show needed_ruby. "
        "Only include consultants who have placed at least one order this quarter: contest_amount > 0. "
        "When the query is about who is close to or working toward a level, always ORDER BY the relevant needed amount ASC (lowest need first). "
        "Do not select contest_begin_date, contest_end_date, total_star_quarters, or level_achieved in results."
    ),
    "unit_rise_radiate": (
        "Rise + Radiate IBC Selling Challenge (Jan 1 – June 30, 2026). "
        "A consultant earns one month toward the challenge each month she orders $600+ in wholesale Section 1 products. "
        "Months do not need to be consecutive. Reward tiers: 4 months = Seminar recognition, "
        "5 months = Rise+Radiate sash, 6 months = quilted crossbody bag + onstage Seminar recognition. "
        "Columns: consultant_id, consultant_number, contest_goal (always 600.0 — the per-month target), "
        "amount_needed ($ still needed to hit $600 in the CURRENT month — 0 means she already qualified this month, "
        "600 means she has not placed any qualifying orders yet this month), "
        "challenge_count (number of months achieved so far — NULL or 0 means not yet earned any month), "
        "month0_production through month5_production (wholesale $ per month, month0=current month, month1=last month, etc.), "
        "display_month0 through display_month5 (YYYY-MM-DD first of each month). "
        "Join to unit_members via consultant_number. "
        "Prize tiers: 4 months = Seminar standing recognition (first prize), 5 months = sash, 6 months = bag + onstage recognition. "
        "June 2026 is the FINAL month of the contest, so the maximum a consultant can reach is their current count + 1. "
        "For 'who has earned' or 'who has a shot at' rise and radiate: use challenge_count >= 3 "
        "(3 months can still reach 4 with June; below 3 is mathematically impossible to earn a prize). "
        "For 'who has already earned a prize': use challenge_count >= 4. "
        "For 'who earned the sash': challenge_count >= 5. "
        "For 'who earned all 6 months': challenge_count = 6. "
        "NEVER show consultants with challenge_count < 3 on earned/on-track queries — they cannot earn a prize. "
        "To find who is close to qualifying THIS month: amount_needed > 0 AND amount_needed < 600, ORDER BY amount_needed ASC. "
        "Do not select display_month columns unless the user specifically asks about monthly breakdown."
    ),
    "unit_registrations": (
        "Event registration status for each unit member. Currently tracks 2026 Seminar (Aug 8-16, 2026). "
        "Columns: consultant_id, consultant_number, event_key, event_name, event_begin_date, "
        "registered_count (1=registered, 0=not registered), "
        "wait_list_count (1=on waitlist), "
        "guest_registered_count, guest_wait_list_count, "
        "registered_status (text description, often NULL). "
        "Join to unit_members via consultant_number. "
        "To find who is registered: registered_count > 0. "
        "To find who is NOT registered: registered_count = 0 AND wait_list_count = 0. "
        "Always include event_name in SELECT so it's clear which event is shown."
    ),
}

_UNIT_SQL_SYSTEM = """You generate SQL SELECT queries for a Mary Kay consultant's team data. Use standard SQL compatible with both SQLite and PostgreSQL — use CURRENT_DATE (not date('now')) for today's date. Never hardcode a date string like '2026-06-01' — always use CURRENT_DATE for today and CURRENT_DATE - INTERVAL 'N days' (or months/years) for relative dates.

{schema}

Rules:
- Return ONLY a raw SQL SELECT statement — no markdown, no explanation, no semicolon at the end
- ALWAYS include WHERE consultant_id = {consultant_id} (or join condition that enforces this)
- Do not use LIMIT unless the user asks for a specific number — always return all matching rows
- For names, SELECT first_name, last_name from unit_members (not just last name)
- For yes/no fields: myshop_active = 1 means yes, 0 means no (includes never created)
- Activity status: A1/A2/A3 = active, T6/T7 = last month before termination, I = inactive, N = new
- When joining tables, always join unit_great_start or unit_star_tracking to unit_members on consultant_number with the same consultant_id filter on both tables
- Default to the full unit (all rows) unless the user explicitly says "personal" or "my personal team" — in that case add AND is_personal_recruit = 1
- When the user asks about a specific person's team or recruits (e.g. "who is on Heidi's team", "who did Sandra recruit", "show Mary's consultants"), filter by recruiter_info: WHERE recruiter_info LIKE '%First Name: Heidi%'. Use only the first name if no last name is given, or add AND recruiter_info LIKE '%Last Name: Smith%' if a last name is provided. Do NOT return all rows for these queries.
- Do not SELECT a column that is already fixed by an equality filter in WHERE (e.g. if filtering WHERE activity_status = 'I3', do not also SELECT activity_status — the user already knows)
- When filtering by first_name or last_name, always use LOWER() on both sides: LOWER(first_name) = LOWER('samyra') — names in the DB are title-cased but user input may not be
- Always include first_name and last_name in the SELECT when querying unit_members, even for single-person queries
- Never use COUNT(*). For ALL "how many" questions, return the full list (SELECT first_name, last_name, consultant_number, career_level_desc, activity_status with the appropriate WHERE filter). The formatter shows the count in the header automatically.
- In JOIN queries, always qualify consultant_id with the table alias (e.g., um.consultant_id = 1) to avoid ambiguity — do NOT use a table alias prefix when querying a single table with no JOIN
- When querying unit_star_tracking, always include level_name in the SELECT — show the consultant's current star level even when the question is about progress toward the next level
- "On target for Great Start" / "doing Great Start" / "in Great Start" means currently in the promotion window: promotion_end_date on or after today. Do NOT require total_bundles > 0 — new consultants still working toward their first bundle count.
- Keep queries simple and readable"""

_UNIT_SQL_USER = "Question: {msg}"


def _handle_unit_query(msg: str, consultant_id: int, ui: dict = None) -> "ChatReply":
    if ui is None:
        ui = UI_EN
    """
    Text-to-SQL handler for unit/team questions. Checks if the consultant has team
    data, builds a schema description, asks an LLM to generate a SELECT query,
    validates it, executes it, and formats the result.

    Also handles consultant card requests of the form "team member [name]" which
    are generated by clicking a name in the chat output.
    """
    from db import connect, is_postgres, tx
    _ph = "%s" if is_postgres() else "?"

    # Consultant card shortcut: "team member [name]" sent by clicking a chat link
    import re as _re
    _card_match = _re.match(r"^team member\s+(.+)$", msg.strip(), _re.IGNORECASE)
    if _card_match:
        _name = _card_match.group(1).strip()
        from crm_store import find_unit_member_by_name, format_consultant_card
        from db import tx
        with tx() as (conn, cur):
            matches = find_unit_member_by_name(cur, consultant_id, _name)
        if not matches:
            return ChatReply(ui["unit_member_not_found"].format(name=_name))
        if len(matches) == 1:
            return ChatReply(format_consultant_card(matches[0]))
        # Multiple close matches — show them all as cards
        cards = "\n\n".join(format_consultant_card(m) for m in matches[:3])
        return ChatReply(cards)

    # Check which tables have data for this consultant
    with tx() as (conn, cur):
        tables_with_data = []
        for tbl in _UNIT_SCHEMA:
            cur.execute(f"SELECT 1 FROM {tbl} WHERE consultant_id = {_ph} LIMIT 1", (consultant_id,))
            if cur.fetchone():
                tables_with_data.append(tbl)

    if not tables_with_data:
        return ChatReply(ui["unit_no_data"])

    # Build schema description from tables that actually have data
    schema_lines = []
    for tbl in tables_with_data:
        schema_lines.append(f"Table: {tbl}\n  {_UNIT_SCHEMA[tbl]}")
    schema_text = "\n\n".join(schema_lines)

    system = _UNIT_SQL_SYSTEM.format(schema=schema_text, consultant_id=consultant_id)
    user = _UNIT_SQL_USER.format(msg=msg)

    client = OpenAI()
    try:
        resp = client.responses.create(
            **model_kwargs(effort="low"),
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
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
        print(f"[UnitQuery] LLM error: {e}")
        return ChatReply(ui["unit_query_rephrase"])

    if not sql:
        return ChatReply(ui["unit_query_unclear"])


    # Safety: SELECT-only, and must reference the consultant_id
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        print(f"[UnitQuery] Rejected non-SELECT: {sql[:100]}")
        return ChatReply(ui["unit_read_only"])

    forbidden = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE")
    if any(kw in sql_upper for kw in forbidden):
        print(f"[UnitQuery] Rejected destructive SQL: {sql[:100]}")
        return ChatReply(ui["unit_unsafe_query"])

    # Verify consultant_id is scoped in the query
    if str(consultant_id) not in sql:
        print(f"[UnitQuery] Missing consultant_id in SQL, injecting: {sql[:100]}")
        sql = f"SELECT * FROM ({sql}) AS q WHERE consultant_id = {consultant_id}"

    # Ensure first_name and last_name appear in the SELECT clause.
    # Use regex word boundary so we find FROM regardless of surrounding whitespace.
    import re as _re
    _from_match = _re.search(r'\bFROM\b', sql, _re.IGNORECASE)
    _select_clause = sql[:_from_match.start()].upper() if _from_match else ""
    if "unit_members" in sql.lower() and "FIRST_NAME" not in _select_clause:
        sql = _re.sub(r'(?i)^SELECT\s+', 'SELECT first_name, last_name, ', sql)
        print(f"[UnitQuery] Injected name columns into SELECT")

    # Only inject identity columns for pure unit_members queries — skip when joining
    # star/bundle tables (those have their own consultant_number + ambiguity issues)
    _no_other_unit_tables = ("unit_star_tracking" not in sql.lower()
                              and "unit_great_start" not in sql.lower()
                              and "unit_rise_radiate" not in sql.lower()
                              and "unit_registrations" not in sql.lower())
    if "unit_members" in sql.lower() and _no_other_unit_tables:
        _id_inject = []
        if "consultant_number" not in _select_clause.lower():
            _id_inject.append("consultant_number")
        if "career_level_desc" not in _select_clause.lower():
            _id_inject.append("career_level_desc")
        if "activity_status" not in _select_clause.lower():
            _id_inject.append("activity_status")
        if _id_inject:
            sql = _re.sub(r'(?i)\bFROM\b', f', {", ".join(_id_inject)} FROM', sql, count=1)
            print(f"[UnitQuery] Injected {_id_inject} into SELECT")

    if "unit_great_start" in sql.lower() and "promotion_end_date" not in _select_clause.lower():
        sql = _re.sub(r'(?i)\bFROM\b', ', promotion_end_date FROM', sql, count=1)
        print(f"[UnitQuery] Injected promotion_end_date into SELECT")

    if "unit_star_tracking" in sql.lower():
        _inject = []
        if not _re.search(r'\bcontest_amount\b', _select_clause, _re.IGNORECASE):
            _inject.append("contest_amount")
        if not _re.search(r'\blevel_name\b', _select_clause, _re.IGNORECASE):
            _inject.append("level_name")
        if _inject:
            sql = _re.sub(r'(?i)\bFROM\b', f', {", ".join(_inject)} FROM', sql, count=1)
            print(f"[UnitQuery] Injected {_inject} into SELECT")

    # Replace any date-today reference with a plain ISO string literal — works in both
    # Resolve date expressions to plain ISO text strings so they compare correctly with
    # TEXT-typed date columns (last_order_date, etc.) in both SQLite and Postgres.
    from datetime import date as _date, timedelta as _timedelta
    _today = _date.today()

    def _eval_date_interval(m):
        base = _date.fromisoformat(m.group(1))
        op, n, unit = m.group(2), int(m.group(3)), m.group(4).lower().rstrip("s")
        if unit in ("day", "week"):
            days = n * (7 if unit == "week" else 1)
            result = base - _timedelta(days=days) if op == "-" else base + _timedelta(days=days)
        elif unit == "month":
            month = base.month + (-n if op == "-" else n)
            year = base.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            result = base.replace(year=year, month=month)
        elif unit == "year":
            result = base.replace(year=base.year + (-n if op == "-" else n))
        else:
            result = base
        return f"'{result.isoformat()}'"

    _today_iso = _today.isoformat()
    _first_of_month = _today.replace(day=1).isoformat()
    # DATE_TRUNC('month', CURRENT_DATE) → first day of current month
    sql = _re.sub(r"DATE_TRUNC\s*\(\s*'month'\s*,\s*CURRENT_DATE\s*\)", f"'{_first_of_month}'", sql, flags=_re.IGNORECASE)
    # Replace CURRENT_DATE / date('now') with today's ISO string
    sql = _re.sub(r"CURRENT_DATE", f"'{_today_iso}'", sql, flags=_re.IGNORECASE)
    sql = _re.sub(r"date\s*\(\s*'now'\s*\)", f"'{_today_iso}'", sql, flags=_re.IGNORECASE)
    # Evaluate any remaining 'YYYY-MM-DD' ± INTERVAL 'N unit' in Python → plain text date
    sql = _re.sub(
        r"(?:DATE\s*)?'(\d{4}-\d{2}-\d{2})'\s*([+-])\s*INTERVAL\s*'(\d+)\s+(\w+)'",
        _eval_date_interval, sql, flags=_re.IGNORECASE
    )
    # DATE_TRUNC after date substitution
    sql = _re.sub(r"DATE_TRUNC\s*\(\s*'month'\s*,\s*'\d{4}-\d{2}-\d{2}'\s*\)", f"'{_first_of_month}'", sql, flags=_re.IGNORECASE)

    print(f"[UnitQuery] Executing: {sql[:400]}")

    try:
        with tx() as (conn, cur):
            cur.execute(sql)
            raw_rows = cur.fetchall()
            # Normalize to dicts — psycopg2 returns plain tuples, SQLite returns Row objects
            if raw_rows and not hasattr(raw_rows[0], "keys") and cur.description:
                col_names = [d[0] for d in cur.description]
                rows = [dict(zip(col_names, r)) for r in raw_rows]
            else:
                rows = raw_rows
            # If rows have consultant_number but no first_name, stitch in names from unit_members
            if rows:
                sample = dict(rows[0]) if hasattr(rows[0], "keys") else {}
                if "consultant_number" in sample and "first_name" not in sample:
                    cn_list = [
                        (dict(r) if hasattr(r, "keys") else dict(zip([d[0] for d in cur.description], r)))
                        .get("consultant_number")
                        for r in rows
                    ]
                    placeholders = ",".join([_ph] * len(cn_list))
                    cur.execute(
                        f"SELECT consultant_number, first_name, last_name FROM unit_members "
                        f"WHERE consultant_id = {_ph} AND consultant_number IN ({placeholders})",
                        (consultant_id, *cn_list),
                    )
                    name_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
                    enriched = []
                    for r in rows:
                        d = dict(r) if hasattr(r, "keys") else dict(zip([d[0] for d in cur.description], r))
                        cn = d.get("consultant_number")
                        if cn and cn in name_map:
                            d["first_name"], d["last_name"] = name_map[cn]
                        enriched.append(d)
                    rows = enriched
    except Exception as e:
        print(f"[UnitQuery] DB error: {e}")
        return ChatReply(ui["unit_query_error"])

    # Deduplicate by consultant_number (or first+last name as fallback) — JOIN queries
    # can produce duplicate rows when the LLM generates a non-DISTINCT query
    _seen = set()
    _deduped = []
    for _r in rows:
        _d = dict(_r) if hasattr(_r, "keys") else _r
        _key = _d.get("consultant_number") or f"{_d.get('first_name','')}|{_d.get('last_name','')}"
        if _key not in _seen:
            _seen.add(_key)
            _deduped.append(_d)
    rows = _deduped

    return ChatReply(_format_unit_results(rows, msg, ui=ui))


def _format_unit_results(rows: list, original_msg: str, ui: dict = None) -> str:
    """Format unit query results as a natural language response."""
    if ui is None:
        ui = UI_EN
    if not rows:
        return ui["unit_no_results"]

    # Normalize rows to dicts
    if hasattr(rows[0], "keys"):
        dicts = [dict(r) for r in rows]
    elif hasattr(rows[0], "_fields"):
        dicts = [r._asdict() for r in rows]
    else:
        return f"{len(rows)} result(s) found."

    cols = list(dicts[0].keys())

    # Pure count result — also handles SQLite artifact where LLM mixes name cols with COUNT(*)
    _count_cols = [c for c in cols if "count" in c.lower()]
    _is_count_query = len(cols) == 1 and _count_cols
    # Mixed artifact: 1 row returned with both name columns AND a count column —
    # this happens in SQLite when LLM forgets GROUP BY; the count value is the real answer
    _is_mixed_count = (
        _count_cols
        and len(dicts) == 1
        and ("first_name" in cols or "last_name" in cols)
        and int(dicts[0].get(_count_cols[0]) or 0) != 1  # if count=1 it might be a real single result
    )
    if _is_count_query or _is_mixed_count:
        count = dicts[0].get(_count_cols[0])
        label = "consultant" if "consultant" in original_msg.lower() else "result"
        plural = "s" if count != 1 else ""
        return f"{count} {label}{plural}"

    import html as _html

    # Build name column if present
    has_name = "first_name" in cols and "last_name" in cols

    def _name(d: dict) -> str:
        fn = (d.get("first_name") or "").strip()
        ln = (d.get("last_name") or "").strip()
        return f"{fn} {ln}".strip() or d.get("consultant_number", "Unknown")

    def _name_link(d: dict) -> str:
        n = _name(d)
        safe = _html.escape(n)
        return f'<a href="#" data-send="team member {safe}">{safe}</a>'

    _SHOW_DETAIL = 20  # rows shown with full detail before collapsing to names-only

    # Names-only result
    value_cols = [c for c in cols if c not in ("first_name", "last_name", "consultant_id",
                                                 "intouch_contact_id", "synced_at", "id",
                                                 "is_personal_recruit", "recruiter_info",
                                                 "total_bundles", "production_month_key",
                                                 "level_achieved", "contest_begin_date",
                                                 "contest_end_date", "total_star_quarters")]
    if has_name and not value_cols:
        links = [_name_link(d) for d in dicts]
        header = ui["unit_consultants_count" if len(links) != 1 else "unit_consultant_count"].format(n=len(links))
        shown = links[:_SHOW_DETAIL]
        rest  = links[_SHOW_DETAIL:]
        body  = "\n".join(f"• {lnk}" for lnk in shown)
        if rest:
            rest_body = "\n".join(f"• {lnk}" for lnk in rest)
            body += (
                f"\n<details><summary style='cursor:pointer;color:var(--pink);font-weight:600'>"
                f"+ {len(rest)} more</summary>\n{rest_body}\n</details>"
            )
        return header + "\n" + body

    # Names + value columns
    # Strip contact-detail columns — they live on the consultant card, not the list view
    _CARD_ONLY = {"email", "phone", "address", "city", "state", "zip", "language",
                  "unit_number", "intouch_contact_id", "synced_at", "career_level_code"}
    value_cols = [c for c in value_cols if c not in _CARD_ONLY]

    # On financial report results (Great Start / Star Consultant), also suppress the
    # identity meta tags — those belong on team lists, not bundle/star rows
    _FINANCIAL_COLS = {"contest_amount", "needed_next_bundle", "total_bundles",
                       "needed_ruby", "needed_diamond", "needed_emerald", "needed_pearl",
                       "level_name", "level_achieved", "total_star_quarters",
                       "rsks_bundles", "rsks_production_left", "total_production",
                       "promotion_end_date", "amount_needed", "challenge_count",
                       "registered_count", "wait_list_count", "event_name"}
    # Always suppress internal FOReports fields — never meaningful to consultants
    _ALWAYS_SUPPRESS = {"rsks_bundles", "rsks_production_left", "total_production"}
    value_cols = [c for c in value_cols if c not in _ALWAYS_SUPPRESS]

    if any(c in _FINANCIAL_COLS for c in value_cols):
        value_cols = [c for c in value_cols if c not in {"career_level_desc", "activity_status", "consultant_number"}]

    if has_name and len(value_cols) <= 8:
        # Drop columns where every row has the same value — but keep identity columns
        # (consultant_number, career_level_desc, activity_status) always visible per row
        _ALWAYS_SHOW = {"consultant_number", "career_level_desc", "activity_status",
                        "last_order_date", "last_order_wholesale"}
        if len(dicts) > 1:
            uniform_cols = {c for c in value_cols
                            if c not in _ALWAYS_SHOW and len({d.get(c) for d in dicts}) == 1}
            value_cols = [c for c in value_cols if c not in uniform_cols]

        _LEVEL_EMOJI = {
            "Ruby": "❤️", "Diamond": "💎",
            "Emerald": "💚", "Pearl": "🤍", "Sapphire": "💙",
        }

        def _fmt_col(c: str, v) -> str | None:
            """Format a single column value. Returns None to skip."""
            if v is None:
                return None
            if c == "level_name":
                emoji = _LEVEL_EMOJI.get(v, "⭐")
                return f"{emoji} {v}"
            if c == "contest_amount":
                return f"${v:,.2f} this quarter"
            if c == "needed_next_bundle":
                return f"${v:,.2f} to next bundle"
            if c == "promotion_end_date":
                try:
                    from datetime import date as _dt
                    import calendar as _cal
                    _d = _dt.fromisoformat(str(v)[:10])
                    return f"ends {_cal.month_name[_d.month]} {_d.day}"
                except Exception:
                    return f"ends {str(v)[:10]}"
            if c in ("needed_ruby", "needed_diamond", "needed_emerald", "needed_pearl"):
                if v and v > 0:
                    return f"${v:,.2f} to {c.replace('needed_','').title()}"
                return None
            if "needed_for_next" in c or "next_level" in c:
                return f"${v:,.2f} to next level" if v and v > 0 else None
            if c == "challenge_count":
                if not v:
                    return None
                mo = "month" if v == 1 else "months"
                return f"{v} {mo} achieved"
            if c == "amount_needed":
                if v and v > 0:
                    return f"${v:,.2f} to qualify this month"
                return None
            if c == "consultant_number":
                return _html.escape(str(v))
            if c == "career_level_desc":
                return _html.escape(str(v))
            if c == "activity_status":
                return _html.escape(str(v))
            if c == "myshop_active":
                return "MyShop: " + ("✓" if v == 1 else "✗")
            if c == "last_order_date":
                try:
                    from datetime import date as _dt
                    _d = _dt.fromisoformat(str(v)[:10])
                    return _d.strftime("%m/%d/%y")
                except Exception:
                    return str(v)[:10]
            if c == "last_order_wholesale":
                try:
                    return f"${float(v):,.0f}"
                except Exception:
                    return f"${v}"
            if isinstance(v, float):
                return f"{c.replace('_',' ').title()}: ${v:,.2f}"
            return f"{c.replace('_',' ').title()}: {_html.escape(str(v))}"

        def _fmt_row(d: dict) -> str:
            # Identity columns (id, level, status) render as small gray meta tag like PCP badge
            _IDENTITY = ["consultant_number", "career_level_desc", "activity_status"]
            _VALUE_ORDER = ["level_name", "contest_amount", "challenge_count",
                            "amount_needed", "needed_next_bundle",
                            "promotion_end_date", "needed_ruby", "needed_diamond",
                            "needed_emerald", "needed_pearl"]

            id_parts = [p for c in _IDENTITY
                        if c in value_cols and (p := _fmt_col(c, d.get(c))) is not None]
            meta = (f" <span style='font-size:0.85em;color:#888'>· "
                    f"{' · '.join(id_parts)}</span>") if id_parts else ""

            val_ordered = [c for c in _VALUE_ORDER if c in value_cols]
            val_rest    = [c for c in value_cols if c not in _IDENTITY and c not in _VALUE_ORDER]

            # last_order_date + last_order_wholesale render as a subline: "mm/dd/yy — $320"
            _ORDER_SUBLINE_COLS = {"last_order_date", "last_order_wholesale"}
            order_sub_parts = [p for c in ["last_order_date", "last_order_wholesale"]
                                if c in value_cols and (p := _fmt_col(c, d.get(c))) is not None]
            order_subline = ("\n  " + " — ".join(order_sub_parts)) if order_sub_parts else ""

            val_parts = [p for c in (val_ordered + val_rest)
                         if c not in _ORDER_SUBLINE_COLS
                         and (p := _fmt_col(c, d.get(c))) is not None]
            suffix = "  —  " + ", ".join(val_parts) if val_parts else ""

            return f"• {_name_link(d)}{meta}{suffix}{order_subline}"

        detail_dicts = dicts[:_SHOW_DETAIL]
        rest_dicts   = dicts[_SHOW_DETAIL:]

        total = len(dicts)
        header = ui["unit_consultants_count" if total != 1 else "unit_consultant_count"].format(n=total)
        body = "\n".join(_fmt_row(d) for d in detail_dicts)
        if rest_dicts:
            rest_body = "\n".join(_fmt_row(d) for d in rest_dicts)
            body += (
                f"\n<details><summary style='cursor:pointer;color:var(--pink);font-weight:600'>"
                f"+ {len(rest_dicts)} more</summary>\n{rest_body}\n</details>"
            )
        return header + "\n" + body

    # Fallback: just names or count
    if has_name:
        links = [_name_link(d) for d in dicts]
        total = len(links)
        header = ui["unit_consultants_count" if total != 1 else "unit_consultant_count"].format(n=total)
        shown = links[:_SHOW_DETAIL]
        rest  = links[_SHOW_DETAIL:]
        body  = "\n".join(f"• {lnk}" for lnk in shown)
        if rest:
            rest_body = "\n".join(f"• {lnk}" for lnk in rest)
            body += (
                f"\n<details><summary style='cursor:pointer;color:var(--pink);font-weight:600'>"
                f"+ {len(rest)} more</summary>\n{rest_body}\n</details>"
            )
        return header + "\n" + body

    # Single value column, no names
    if len(cols) == 1:
        vals = [str(list(d.values())[0]) for d in dicts]
        return "\n".join(vals)

    return f"{len(dicts)} result(s) found."


# -------------------------
# CRM text-to-SQL (data_query intent)
# -------------------------
