## update sql placeholders 2-14 10:15am

# mk_chat_core.py
import json
import calendar
import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz, process

from db import connect, is_postgres

# -------------------------
# Paths / Settings
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
CATALOG_DIR = BASE_DIR / "catalog"
MODEL = "gpt-4.1-mini"

MATCH_LIMIT = 25
TOP5 = 5

# Placeholder differs:
# - SQLite: ?
# - Postgres (psycopg): %s
PH = "%s" if is_postgres() else "?"


# -------------------------
# DB helpers
# -------------------------
def db_connect():
    return connect()


def get_catalog_path_for_language(language: str) -> Path:
    language = (language or "en").strip().lower()
    if language == "es":
        return CATALOG_DIR / "es.csv"
    return CATALOG_DIR / "en.csv"


def ensure_sessions_table():
    """
    Keep sessions schema compatible across SQLite + Postgres.
    We use session_id (not id) to avoid reserved-word headaches and to match your app usage.
    """
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id BIGINT PRIMARY KEY,
                  state_json TEXT NOT NULL DEFAULT '{}',
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id INTEGER PRIMARY KEY,
                  state_json TEXT NOT NULL DEFAULT '{}',
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def load_session_state(session_id: int = 1) -> dict:
    ensure_sessions_table()
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT state_json FROM sessions WHERE session_id={PH}", (session_id,))
        row = cur.fetchone()

        if not row:
            state = {"last_customer": None, "pending": None}
            cur.execute(
                f"INSERT INTO sessions (session_id, state_json) VALUES ({PH}, {PH})",
                (session_id, json.dumps(state)),
            )
            conn.commit()
            return state

        # row could be tuple (sqlite) or dict-like (psycopg dict_row)
        if isinstance(row, dict):
            return json.loads(row.get("state_json") or "{}")
        return json.loads(row[0])
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def save_session_state(state: dict, session_id: int = 1) -> None:
    ensure_sessions_table()
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                f"UPDATE sessions SET state_json={PH}, updated_at=NOW() WHERE session_id={PH}",
                (json.dumps(state), session_id),
            )
        else:
            cur.execute(
                f"UPDATE sessions SET state_json={PH}, updated_at=CURRENT_TIMESTAMP WHERE session_id={PH}",
                (json.dumps(state), session_id),
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def insert_job(job_type: str, payload: dict, consultant_id: int) -> int:
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO jobs (type, payload_json, status, consultant_id)
                VALUES ({PH}, {PH}, 'queued', {PH})
                RETURNING id
                """,
                (job_type, json.dumps(payload), int(consultant_id)),
            )
            row = cur.fetchone()
            job_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cur.execute(
                f"INSERT INTO jobs (type, payload_json, status, consultant_id) VALUES ({PH}, {PH}, 'queued', {PH})",
                (job_type, json.dumps(payload), int(consultant_id)),
            )
            job_id = cur.lastrowid

        conn.commit()
        return int(job_id)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


# -------------------------
# Catalog
# -------------------------
def load_catalog(path: Path) -> List[dict]:
    """
    Loads catalog CSV with headers: sku (lowercase), product_name, price
    Filters obvious samples/collateral to improve matching.
    """
    import csv

    if not path.exists():
        raise FileNotFoundError(f"Catalog not found at: {path}")

    items: List[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            name = (row.get("product_name") or "").strip()
            price = row.get("price")

            if not sku or not name:
                continue

            name_l = name.lower()
            if "sample" in name_l:
                continue
            if "the look" in name_l or "booklet" in name_l or "look (" in name_l:
                continue
            if "pk./" in name_l or "pk/" in name_l:
                continue

            try:
                price_val = float(price) if price else None
            except ValueError:
                price_val = None

            items.append({"sku": sku, "product_name": name, "price": price_val})
    return items


def fmt_price(p: Any) -> str:
    if isinstance(p, (int, float)):
        return f"${p:.2f}"
    return ""


def best_matches(catalog: List[dict], query: str, limit: int = 5) -> List[dict]:
    q = (query or "").lower().strip()
    q_compact = re.sub(r"\s+", " ", q)

    anchors = [
        "4-in-1",
        "4 in 1",
        "timewise 3d",
        "3d",
        "cc cream",
        "miracle set",
        "satin hands",
        "satin lips",
        "foundation primer",
        "foundation brush",
        "shimmer eye shadow stick",
        "undereye corrector",
        "eye cream",
        "roll-up bag",
        "great heights",
        "sheer illusion",
        "cleanser",
        "set",
    ]

    anchored = None
    for a in anchors:
        if a in q_compact:
            anchored = a
            break

    candidates = catalog
    if anchored:
        a_l = anchored.lower()
        filtered = [c for c in catalog if a_l in c["product_name"].lower()]
        if filtered:
            candidates = filtered

    names = [c["product_name"] for c in candidates]
    results = process.extract(q, names, scorer=fuzz.WRatio, limit=limit)

    matches: List[dict] = []
    for name, score, idx in results:
        c = candidates[idx]
        matches.append(
            {"sku": c["sku"], "product_name": c["product_name"], "price": c["price"], "score": score}
        )
    return matches


def auto_pick_match(catalog: List[dict], query: str) -> Tuple[Optional[dict], List[dict]]:
    matches = best_matches(catalog, query, limit=MATCH_LIMIT)
    if not matches:
        return None, matches

    top = matches[0]
    second = matches[1] if len(matches) > 1 else {"score": 0}

    if top["score"] >= 88 and (top["score"] - second["score"]) >= 6:
        return top, matches

    return None, matches


def llm_pick_from_candidates(client: OpenAI, item_text: str, candidates: List[dict]) -> Optional[int]:
    if not candidates:
        return None

    k = min(len(candidates), MATCH_LIMIT)
    short = candidates[:k]

    lines = []
    for i, c in enumerate(short, start=1):
        price = fmt_price(c.get("price"))
        lines.append(f"{i}) {c['product_name']} {price}".strip())

    system = (
        "You help select the best matching Mary Kay catalog item.\n"
        "You MUST choose from the provided list only.\n"
        "Return ONLY JSON like: {\"pick\": 3} or {\"pick\": null}.\n"
        "Rules:\n"
        "- If the user mentions a variant (Normal/Dry, Combination/Oily, shade/color), prefer the matching variant.\n"
        "- If multiple are plausible, pick the closest overall.\n"
        "- If none are clearly correct, return {\"pick\": null}.\n"
    )

    user = f"User requested item: {item_text}\n\nCandidates:\n" + "\n".join(lines)

    try:
        resp = client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        txt = resp.output[0].content[0].text.strip()
        data = json.loads(txt)
        pick = data.get("pick")
        if pick is None:
            return None
        if isinstance(pick, int) and 1 <= pick <= k:
            return pick - 1
        return None
    except Exception:
        return None


# -------------------------
# OpenAI parsing
# -------------------------
def parse_with_openai(client: OpenAI, text: str, last_customer: Optional[dict]) -> dict:
    system_prompt = (
        "You extract structured data from user text.\n"
        "Return ONLY valid JSON.\n\n"
        "If NEW CUSTOMER:\n"
        "{\n"
        '  "type": "customer",\n'
        '  "customer": {\n'
        '    "First Name": "",\n'
        '    "Last Name": "",\n'
        '    "Email": "",\n'
        '    "Phone": "",\n'
        '    "Street": "",\n'
        '    "City": "",\n'
        '    "State": "",\n'
        '    "Postal Code": "",\n'
        '    "Birthday": ""\n'
        "  }\n"
        "}\n\n"
        "If ORDER:\n"
        "{\n"
        '  "type": "order",\n'
        '  "order": {\n'
        '    "customer_first": "",\n'
        '    "customer_last": "",\n'
        '    "items": [{"text": "", "qty": 1}]\n'
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- State must be full name (e.g., Alabama).\n"
        "- Birthday may be provided as MM/DD, Month Day, or YYYY-MM-DD. Output as YYYY-MM-DD. If year missing, use 2000.\n"
        "- If an order does not include a customer name, reuse the last customer if provided.\n"
        "- For shades/colors/variants (Normal/Dry, Combination/Oily), include them in item text if present.\n"
        "- If the user says a variant applies to multiple items (e.g., 'normal/dry both'), append that variant phrase to each affected item.\n"
        "- Do NOT treat numbers that are part of a product name as quantity (examples: '4-in-1 cleanser', '2-in-1', '3D').\n"
        "- Only set qty > 1 if the user explicitly indicates quantity (two, x2, qty 2, three of them, etc.). Otherwise qty must be 1.\n"
        "- If the user says a quantity change like 'make that 2' or 'change it to 3', do NOT output a new order. That will be handled separately.\n"
    )

    last_ctx = ""
    if last_customer and last_customer.get("First Name") and last_customer.get("Last Name"):
        last_ctx = f"Last customer: {last_customer['First Name']} {last_customer['Last Name']}\n"

    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": last_ctx + text},
        ],
    )

    output_text = resp.output[0].content[0].text.strip()
    return json.loads(output_text)


# -------------------------
# Misc helpers
# -------------------------
def normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def format_phone_display(phone: str) -> str:
    digits = normalize_phone(phone)
    if not digits:
        return ""
    if len(digits) >= 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) >= 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    if len(digits) == 7:
        return f"{digits[0:3]}-{digits[3:7]}"
    return digits


def normalize_birthday(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            y, mo, d = map(int, s.split("-"))
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", s)
    if m:
        mo = int(m.group(1))
        d = int(m.group(2))
        y_raw = m.group(3)
        if y_raw is None:
            y = 2000
        else:
            y_i = int(y_raw)
            if len(y_raw) == 2:
                y = 2000 + y_i if y_i <= 29 else 1900 + y_i
            else:
                y = y_i
        try:
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    s2 = re.sub(r"[.,]", " ", s)
    s2 = re.sub(r"\s+", " ", s2).strip()

    month_map = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    month_map.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})

    parts = s2.split(" ")

    def _try(month_token: str, day_token: str, year_token: str | None) -> str:
        mo = month_map.get(month_token.lower())
        if not mo:
            return ""
        try:
            d = int(day_token)
        except Exception:
            return ""
        if year_token is None or year_token == "":
            y = 2000
        else:
            try:
                y_i = int(year_token)
            except Exception:
                return ""
            if len(year_token) == 2:
                y = 2000 + y_i if y_i <= 29 else 1900 + y_i
            else:
                y = y_i
        try:
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    if len(parts) >= 2 and parts[0].lower() in month_map:
        year = parts[2] if len(parts) >= 3 else None
        out = _try(parts[0], parts[1], year)
        if out:
            return out

    if len(parts) >= 2 and parts[1].lower() in month_map:
        year = parts[2] if len(parts) >= 3 else None
        out = _try(parts[1], parts[0], year)
        if out:
            return out

    return ""


def birthday_display(normalized: str) -> str:
    s = (normalized or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return ""
    y, mo, d = map(int, s.split("-"))
    month = calendar.month_name[mo]
    if y == 2000:
        return f"{month} {d}"
    return f"{month} {d}, {y}"


def yes(s: str) -> bool:
    return s.strip().lower() in ("y", "yes", "yeah", "yep", "ok", "okay", "confirm", "correct", "right")


def no(s: str) -> bool:
    return s.strip().lower() in ("n", "no", "nope", "nah", "wrong", "incorrect")


def fix_qty_if_number_is_part_of_name(text: str, qty: int) -> int:
    t = (text or "").strip().lower()
    looks_like_x_in_1 = bool(re.match(r"^\d+\s*[-]?\s*in\s*[-]?\s*\d+", t)) or "in1" in t.replace(" ", "")[:10]
    if looks_like_x_in_1:
        return 1
    return qty


def propose_top(top: dict, current_qty: int) -> str:
    q = int(current_qty or 1)
    qtxt = f" x{q}" if q != 1 else ""
    return f"I think you mean: {top['product_name']} {fmt_price(top.get('price'))}{qtxt}. Is that right? (yes/no)"


def render_top5(matches: List[dict]) -> str:
    top = matches[:TOP5]
    lines = ["Got it — pick the best match (reply 1-5), or type what you meant and I’ll search again:"]
    for i, m in enumerate(top, start=1):
        lines.append(f"{i}) {m['product_name']} {fmt_price(m.get('price'))}".strip())
    return "\n".join(lines)


def parse_add_remove(message: str):
    m = (message or "").strip()
    low = m.lower()

    for kw in ("add ", "add:"):
        if low.startswith(kw):
            rest = m[len(kw):].strip()
            return ("add", rest)

    for kw in ("remove ", "remove:", "delete ", "delete:"):
        if low.startswith(kw):
            rest = m[len(kw):].strip()
            return ("remove", rest)

    return (None, None)


def parse_qty_prefix(text: str) -> Tuple[int, str]:
    t = (text or "").strip()
    m = re.match(r"^\s*(\d+)\s+(.+)$", t)
    if not m:
        return (1, t)

    q = int(m.group(1))
    rest = m.group(2).strip()

    rest_low = rest.lower()
    if re.match(r"^(?:-?\s*in\s*-?\s*\d+)\b", rest_low):
        return (1, t)

    if q >= 1:
        return (q, rest)

    return (1, t)


def parse_qty_change(msg: str) -> Optional[int]:
    s = (msg or "").strip().lower()

    if s.isdigit():
        q = int(s)
        if 1 <= q <= 99:
            return q

    m = re.search(r"\bx\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))

    m = re.search(r"\bqty\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))

    m = re.search(r"\bmake (?:that|it)\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))

    m = re.search(r"\bchange (?:that|it)?\s*(?:to)?\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))

    return None


# -------------------------
# Chat Engine
# -------------------------
@dataclass
class ChatReply:
    reply: str


class MKChatEngine:
    """
    Stateless per-request; state is loaded/saved to sessions table (SQLite or Postgres).
    """
    def __init__(self):
        load_dotenv()
        self.client = OpenAI()

    def handle_message(self, message: str, consultant_id: int, session_id: Optional[int] = None) -> ChatReply:
        sid = int(session_id or consultant_id)
        state = load_session_state(session_id=sid)

        from auth_core import get_consultant

        consultant = get_consultant(consultant_id)
        language = consultant.get("language", "en") if consultant else "en"

        catalog_path = get_catalog_path_for_language(language)
        catalog = load_catalog(catalog_path)

        last_customer = state.get("last_customer")
        pending = state.get("pending")
        msg = (message or "").strip()

        if not msg:
            return ChatReply("Say something like: “new customer Jane Doe …” or “order for Jane Doe: …”")

        if msg.lower() in ("cancel", "stop", "nevermind", "never mind"):
            state["pending"] = None
            save_session_state(state, session_id=sid)
            return ChatReply("Okay — canceled. Ready for your new customer or order.")

        # -------------------------
        # Pending flows
        # -------------------------
        if pending:
            kind = pending.get("kind")

            if kind == "customer_confirm":
                if yes(msg):
                    customer = pending["customer"]
                    insert_job("NEW_CUSTOMER", customer, consultant_id=consultant_id)
                    state["last_customer"] = customer
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(f"✅ {customer['First Name']} {customer['Last Name']} confirmed. Adding to MyCustomers now.")
                if no(msg):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply("No problem — Send the corrected customer info and I’ll try again.")
                return ChatReply("Please reply yes or no.")

            if kind == "order_line_confirm_top":
                order = pending["order"]
                line_index = pending["line_index"]
                top = pending["top"]
                matches = pending["matches"]

                q_new = parse_qty_change(msg)
                if q_new is not None:
                    order["lines"][line_index]["qty"] = q_new
                    state["pending"] = {
                        "kind": "order_line_confirm_top",
                        "order": order,
                        "line_index": line_index,
                        "top": top,
                        "matches": matches,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(propose_top(top, current_qty=q_new))

                if yes(msg):
                    order["lines"][line_index]["chosen"] = top
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog)

                if no(msg):
                    state["pending"] = {
                        "kind": "order_line_pick_top5_or_search",
                        "order": order,
                        "line_index": line_index,
                        "matches": matches[:MATCH_LIMIT],
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches))

                return ChatReply("Reply yes/no — or type a quantity like `2` or `x2`.")

            if kind == "order_line_pick_top5_or_search":
                order = pending["order"]
                line_index = pending["line_index"]
                matches = pending.get("matches") or []

                if msg.isdigit():
                    i = int(msg)
                    if 1 <= i <= min(TOP5, len(matches)):
                        picked = matches[i - 1]
                        order["lines"][line_index]["chosen"] = picked
                        state["pending"] = None
                        return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog)

                new_matches = best_matches(catalog, msg, limit=MATCH_LIMIT)
                if not new_matches:
                    return ChatReply("No close matches. Try rewording the item (brand/line/shade helps).")

                state["pending"] = {
                    "kind": "order_line_pick_top5_or_search",
                    "order": order,
                    "line_index": line_index,
                    "matches": new_matches[:MATCH_LIMIT],
                }
                save_session_state(state, session_id=sid)
                return ChatReply(render_top5(new_matches))

            if kind == "order_confirm":
                order = pending["order"]

                action, rest = parse_add_remove(msg)
                if action == "add":
                    qty, item_text = parse_qty_prefix(rest)
                    if not item_text:
                        return ChatReply("Tell me what to add, e.g. `add satin hands`.")
                    order["lines"].append({"text": item_text, "qty": qty, "chosen": None})
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog)

                if action == "remove":
                    target = (rest or "").strip()
                    if not target:
                        return ChatReply("Tell me what to remove, e.g. `remove 2` or `remove satin lips`.")
                    removed = self._remove_line(order, target)
                    if not removed:
                        return ChatReply("I couldn’t find that item to remove. Try `remove 2` or part of the name.")
                    state["pending"] = {"kind": "order_confirm", "order": order}
                    save_session_state(state, session_id=sid)
                    return ChatReply(self._format_order_confirm(order) + "\n\nYou can also say `add ...` or `remove ...`.")

                if yes(msg):
                    cust_first = order["customer"]["First Name"]
                    cust_last = order["customer"]["Last Name"]

                    for line in order["lines"]:
                        sku = line["chosen"]["sku"]
                        qty = int(line["qty"])
                        for _ in range(max(1, qty)):
                            insert_job(
                                "NEW_ORDER_ROW",
                                {"First Name": cust_first, "Last Name": cust_last, "SKU": sku},
                                consultant_id=consultant_id,
                            )

                    state["pending"] = None
                    state["last_customer"] = {"First Name": cust_first, "Last Name": cust_last}
                    save_session_state(state, session_id=sid)
                    return ChatReply(f"✅ Order for {cust_first} {cust_last} confirmed. Sending to MyCustomers now.")

                if no(msg):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply("Okay — paste the corrected order and I’ll rebuild the summary.")

                return ChatReply("Reply yes/no — or say `add ...` / `remove ...` to adjust the order.")

        # -------------------------
        # Normal parse
        # -------------------------
        try:
            parsed = parse_with_openai(self.client, msg, last_customer)
        except Exception as e:
            return ChatReply(f"❌ Parse error: {e}")

        if parsed.get("type") == "customer":
            customer = parsed.get("customer") or {}
            customer["Phone"] = normalize_phone(customer.get("Phone", ""))
            customer["Birthday"] = normalize_birthday(customer.get("Birthday", ""))

            state["pending"] = {"kind": "customer_confirm", "customer": customer}
            save_session_state(state, session_id=sid)
            return ChatReply(self._format_customer_confirm(customer))

        if parsed.get("type") == "order":
            order = parsed.get("order") or {}
            cust_first = (order.get("customer_first") or "").strip()
            cust_last = (order.get("customer_last") or "").strip()

            if (not cust_first or not cust_last) and last_customer:
                cust_first = (last_customer.get("First Name") or "").strip()
                cust_last = (last_customer.get("Last Name") or "").strip()

            if not cust_first or not cust_last:
                return ChatReply("Who is this order for? Please include first and last name.")

            items = order.get("items") or []
            if not items:
                return ChatReply("What items should I add to the order?")

            order_draft = self._make_order_draft(cust_first, cust_last, items)
            if not order_draft["lines"]:
                return ChatReply("I didn’t catch any items — try again with the product names.")

            for line in order_draft["lines"]:
                picked, _m = auto_pick_match(catalog, line["text"])
                if picked:
                    line["chosen"] = picked

            nxt = self._next_unresolved_index(order_draft)
            if nxt is not None:
                top, matches, _ = self._start_line_resolution(catalog, order_draft, nxt)
                pick_idx = llm_pick_from_candidates(self.client, order_draft["lines"][nxt]["text"], matches)
                if pick_idx is not None:
                    top = matches[pick_idx]

                state["pending"] = {
                    "kind": "order_line_confirm_top",
                    "order": order_draft,
                    "line_index": nxt,
                    "top": top,
                    "matches": matches,
                }
                state["last_customer"] = {"First Name": cust_first, "Last Name": cust_last}
                save_session_state(state, session_id=sid)
                return ChatReply(propose_top(top, current_qty=order_draft["lines"][nxt]["qty"]))

            state["pending"] = {"kind": "order_confirm", "order": order_draft}
            state["last_customer"] = {"First Name": cust_first, "Last Name": cust_last}
            save_session_state(state, session_id=sid)
            return ChatReply(self._format_order_confirm(order_draft) + "\n\nYou can also say `add ...` or `remove ...`.")

        return ChatReply("I couldn’t tell if that was a new customer or an order. Try rephrasing.")

    # -------------------------
    # Internal helper methods
    # -------------------------
    def _continue_resolving_and_reply(self, state: dict, order: dict, consultant_id: int, sid: int, catalog: List[dict]) -> ChatReply:
        while True:
            nxt = self._next_unresolved_index(order)
            if nxt is None:
                state["pending"] = {"kind": "order_confirm", "order": order}
                state["last_customer"] = order["customer"]
                save_session_state(state, session_id=sid)
                return ChatReply(self._format_order_confirm(order) + "\n\nYou can also say `add ...` or `remove ...`.")

            picked, _m = auto_pick_match(catalog, order["lines"][nxt]["text"])
            if picked:
                order["lines"][nxt]["chosen"] = picked
                continue

            top, matches, _ = self._start_line_resolution(catalog, order, nxt)
            pick_idx = llm_pick_from_candidates(self.client, order["lines"][nxt]["text"], matches)
            if pick_idx is not None:
                top = matches[pick_idx]

            state["pending"] = {
                "kind": "order_line_confirm_top",
                "order": order,
                "line_index": nxt,
                "top": top,
                "matches": matches,
            }
            save_session_state(state, session_id=sid)
            return ChatReply(propose_top(top, current_qty=order["lines"][nxt]["qty"]))

    def _format_customer_confirm(self, customer: dict) -> str:
        street = (customer.get("Street") or "").strip() or "(none)"
        city = (customer.get("City") or "").strip()
        st = (customer.get("State") or "").strip()
        postal = (customer.get("Postal Code") or "").strip()

        addr = street
        if any([city, st, postal]):
            addr = f"{street}, {city}, {st} {postal}".strip()

        phone_disp = format_phone_display(customer.get("Phone", ""))
        birthday_disp = birthday_display(customer.get("Birthday", ""))

        return (
            "Okay — here’s the customer I’m about to submit:\n"
            f"• Name: {customer.get('First Name','').strip()} {customer.get('Last Name','').strip()}\n"
            f"• Email: {(customer.get('Email','') or '').strip() or '(none)'}\n"
            f"• Phone: {phone_disp or '(none)'}\n"
            f"• Address: {addr}\n"
            f"• Birthday: {birthday_disp or '(none)'}\n"
            "Does that look right? (yes/no)"
        )

    def _make_order_draft(self, cust_first: str, cust_last: str, items: List[dict]) -> dict:
        lines = []
        for it in items:
            text = (it.get("text") or "").strip()
            if not text:
                continue
            qty = int(it.get("qty") or 1)
            qty = fix_qty_if_number_is_part_of_name(text, qty)
            if qty < 1:
                qty = 1
            lines.append({"text": text, "qty": qty, "chosen": None})
        return {"customer": {"First Name": cust_first, "Last Name": cust_last}, "lines": lines}

    def _format_order_confirm(self, order: dict) -> str:
        cust = order["customer"]
        out = [f"Okay — I have this order for {cust['First Name']} {cust['Last Name']}:"]
        total = 0.0
        any_prices = False

        for i, line in enumerate(order["lines"], start=1):
            chosen = line["chosen"]
            qty = int(line["qty"])
            price = chosen.get("price")

            if isinstance(price, (int, float)):
                any_prices = True
                total += price * qty

            out.append(f"• {i}) {chosen['product_name']} {fmt_price(price)} x{qty}")

        if any_prices:
            out.append(f"Estimated retail total: ${total:.2f}")

        out.append("Does that sound right? (yes/no)")
        return "\n".join(out)

    def _next_unresolved_index(self, order: dict) -> Optional[int]:
        for i, line in enumerate(order["lines"]):
            if line["chosen"] is None:
                return i
        return None

    def _start_line_resolution(self, catalog: List[dict], order: dict, line_index: int) -> Tuple[dict, List[dict], str]:
        text = order["lines"][line_index]["text"]
        matches = best_matches(catalog, text, limit=MATCH_LIMIT)
        if not matches:
            return {"sku": "", "product_name": "No close matches found", "price": None, "score": 0}, [], text
        return matches[0], matches, text

    def _remove_line(self, order: dict, target: str) -> bool:
        t = (target or "").strip()
        if not t:
            return False

        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(order["lines"]):
                order["lines"].pop(idx)
                return True
            return False

        low = t.lower()
        for i, line in enumerate(order["lines"]):
            chosen = line.get("chosen")
            name = chosen.get("product_name") if chosen else (line.get("text") or "")
            if low in (name or "").lower():
                order["lines"].pop(i)
                return True

        return False
