## update sql placeholders 2-14 10:15am

# mk_chat_core.py
import json
import calendar
import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from crm_store import find_customers_by_name, format_customer_card

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

def yes(s: str) -> bool:
    return (s or "").strip().lower() in (
        "y", "yes", "yeah", "yep", "ok", "okay", "confirm", "correct", "right",
        "si", "sí",  # optional Spanish
    )

def no(s: str) -> bool:
    return (s or "").strip().lower() in (
        "n", "no", "nope", "nah", "wrong", "incorrect",
    )

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

STATE_MAP = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

def normalize_state(state: str) -> str:
    s = (state or "").strip()
    if not s:
        return ""
    if len(s) == 2:
        return STATE_MAP.get(s.upper(), s)
    return s


STREET_SUFFIXES = (
    "st", "street", "rd", "road", "ave", "avenue", "blvd", "boulevard",
    "dr", "drive", "ln", "lane", "ct", "court", "cir", "circle",
    "pkwy", "parkway", "hwy", "highway", "pl", "place", "way"
)

def parse_address_line(s: str) -> Optional[Dict[str, str]]:
    """
    Best-effort parse of an address line into:
      Street, City, State, Postal Code

    Supports:
      - "444 4th St Arab, AL 35976"
      - "444 4th St, Arab, AL 35976"
      - "333 3rd st" (street-only)
    """
    raw = (s or "").strip()
    if not raw:
        return None

    # Normalize whitespace
    txt = re.sub(r"\s+", " ", raw).strip()

    # Pull ZIP first (required for full parse)
    mzip = re.search(r"\b(\d{5})(?:-\d{4})?\b", txt)
    zip5 = mzip.group(1) if mzip else ""

    # ---------- Pattern A: "street city, ST ZIP"
    # Example: "444 4th St Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s*,\s*(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?$",
        txt
    )
    if m:
        return {
            "Street": m.group("street").strip(),
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern B: "street, city, ST ZIP"
    # Example: "444 4th St, Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s*,\s*(?P<city>.+?)\s*,\s*(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?$",
        txt
    )
    if m:
        return {
            "Street": m.group("street").strip(),
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern D: "street city ST ZIP" (no commas)
    # Example: "333 3rd st arab al 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s+(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?$",
        txt
    )
    if m:
        return {
            "Street": m.group("street").strip(),
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern C: street-only
    # Only accept street-only if it looks like a street line (has a number + suffix)
    low = txt.lower()
    has_number = bool(re.search(r"\d", low))
    has_suffix = any(re.search(rf"\b{re.escape(suf)}\b", low) for suf in STREET_SUFFIXES)

    if has_number and has_suffix and not zip5:
        return {"Street": txt}

    # If it has a zip but didn't match full patterns, don't guess (avoid bad splits)
    return None

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

UI_EN = {
    "empty_prompt": "Say something like: “new customer Jane Doe …” or “order for Jane Doe: …”",
    "canceled": "Okay — canceled. Ready for your new customer or order.",

    "cust_submit_intro": "Okay — here’s the customer I’m about to submit:",
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "address": "Address",
    "birthday": "Birthday",
    "none": "(none)",
    "cust_confirm_q": "Does that look right? (yes/no)",
    "cust_edit_hint": "You can also say 'add...' or 'edit...'",

    "order_intro": "Okay — I have this order for {first} {last}:",
    "estimated_total": "Estimated retail total: {total}",
    "order_confirm_q": "Does that sound right? (yes/no)",

    "need_customer_for_order": "Who is this order for? Please tell me the customer name and paste the order again.",
    "need_items": "What items should I add to the order?",
    "no_matches": "No close matches. Try rewording the item (brand/line/shade helps).",
    "reply_yes_no_qty": "Reply yes/no — or type a quantity like `2` or `x2`.",
    "order_adjust_hint": "You can also say `add ...` or `remove ...`.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Parse error: {err}",
    "cant_tell": "I couldn’t tell if that was a new customer or an order. Try rephrasing.",
    "cust_confirmed": "✅ {first} {last} confirmed. Adding to MyCustomers now.",
    "cust_reject": "No problem — Send the corrected customer info and I’ll try again.",
    "order_confirmed": "✅ Order for {first} {last} confirmed. Sending to MyCustomers now.",
    "order_reject": "Okay — paste the corrected order and I’ll rebuild the summary.",
}

UI_ES = {
    "empty_prompt": "Di algo como: “nuevo cliente Jane Doe …” o “pedido para Jane Doe: …”",
    "canceled": "Listo — cancelado. Estoy listo para tu nuevo cliente o pedido.",

    "cust_submit_intro": "Perfecto — este es el cliente que estoy por enviar:",
    "name": "Nombre",
    "email": "Correo",
    "phone": "Teléfono",
    "address": "Dirección",
    "birthday": "Cumpleaños",
    "none": "(ninguno)",
    "cust_confirm_q": "¿Se ve correcto? (sí/no)",
    # keep add/edit commands in English so your parser stays simple
    "cust_edit_hint": "You can also say 'add...' or 'edit...'",

    "order_intro": "Perfecto — tengo este pedido para {first} {last}:",
    "estimated_total": "Total estimado (precio): {total}",
    "order_confirm_q": "¿Suena bien? (sí/no)",

    "need_customer_for_order": "¿Para quién es este pedido? Dime el nombre del cliente y vuelve a pegar el pedido.",
    "need_items": "¿Qué artículos debo agregar al pedido?",
    "no_matches": "No encuentro coincidencias cercanas. Intenta describirlo de otra forma (línea/tono/variante ayuda).",
    "reply_yes_no_qty": "Responde sí/no — o escribe una cantidad como `2` o `x2`.",
    "order_adjust_hint": "You can also say `add ...` or `remove ...`.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Error al interpretar: {err}",
    "cant_tell": "No pude determinar si era un cliente nuevo o un pedido. Intenta reformularlo.",
    "cust_confirmed": "✅ {first} {last} confirmado. Agregando a MyCustomers ahora.",
    "cust_reject": "No hay problema — envíame la info corregida del cliente y lo intento de nuevo.",
    "order_confirmed": "✅ Pedido para {first} {last} confirmado. Enviándolo a MyCustomers ahora.",
    "order_reject": "Listo — pega el pedido corregido y lo vuelvo a armar.",
}

def parse_add_remove(message: str):
    m = (message or "").strip()
    low = m.lower().strip()

    # ADD keywords (EN + ES)
    for kw in ("add ", "add:", "agrega ", "agrega:", "añade ", "añade:", "anade ", "anade:"):
        if low.startswith(kw):
            rest = m[len(kw):].strip()
            return ("add", rest)

    # REMOVE keywords (EN + ES)
    for kw in (
        "remove ", "remove:", "delete ", "delete:",
        "quita ", "quita:", "quitar ", "quitar:", "elimina ", "elimina:", "borrar ", "borrar:"
    ):
        if low.startswith(kw):
            rest = m[len(kw):].strip()
            return ("remove", rest)

    return (None, None)


def fix_qty_if_number_is_part_of_name(text: str, qty: int) -> int:
    t = (text or "").strip().lower()
    looks_like_x_in_1 = bool(re.match(r"^\d+\s*[-]?\s*in\s*[-]?\s*\d+", t)) or "in1" in t.replace(" ", "")[:10]
    if looks_like_x_in_1:
        return 1
    return qty


def propose_top(top: dict, current_qty: int) -> str:
    q = int(current_qty or 1)
    qtxt = f" x{q}" if q != 1 else ""

    price_txt = fmt_price(top.get("price"))
    parts = [top["product_name"]]

    if price_txt:
        parts.append(price_txt)

    line = " ".join(parts) + qtxt

    return f"I think you mean: {line}. Is that right? (yes/no)"

def render_top5(matches: List[dict]) -> str:
    top = matches[:TOP5]
    lines = ["Got it — pick the best match (reply 1-5), or type what you meant and I’ll search again:"]
    for i, m in enumerate(top, start=1):
        lines.append(f"{i}) {m['product_name']} {fmt_price(m.get('price'))}".strip())
    return "\n".join(lines)

def split_edit_parts(message: str) -> List[str]:
    """
    Splits a user edit message into chunks.
    IMPORTANT: do NOT split on commas, because addresses use commas.
    """
    s = (message or "").strip()
    if not s:
        return []

    # Split on semicolons OR the word "and" used as a separator OR newlines
    parts = re.split(r"\s*;\s*|\s+\band\b\s+|\n+", s, flags=re.IGNORECASE)

    return [p.strip() for p in parts if p.strip()]


def _looks_like_email(s: str) -> bool:
    return bool(re.search(r"[^\s]+@[^\s]+\.[^\s]+", s or ""))


def _extract_email(s: str) -> str:
    m = re.search(r"([^\s]+@[^\s]+\.[^\s]+)", s or "")
    return (m.group(1).strip() if m else "").strip()


def _extract_zip(s: str) -> str:
    m = re.search(r"\b(\d{5})\b", s or "")
    return (m.group(1) if m else "").strip()


def _extract_phone_candidate(s: str) -> str:
    # Keep digits; if 7/10/11 digits it's likely a phone
    digits = normalize_phone(s)
    if len(digits) in (7, 10, 11):
        return digits
    # Sometimes they paste "256-xxx-xxxx ext 2" -> still ok
    if len(digits) >= 10:
        return digits
    return ""


def _looks_like_birthday(s: str) -> bool:
    s2 = (s or "").strip()
    if not s2:
        return False
    # MM/DD, M-D, MM/DD/YYYY, YYYY-MM-DD, "Oct 14"
    if re.search(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", s2):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s2):
        return True
    # month name + day
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", s2, re.IGNORECASE):
        return True
    return False


def apply_customer_edits(customer: dict, message: str) -> Tuple[dict, List[str]]:
    """
    Applies 'add/edit' instructions to a pending customer dict.
    Returns: (updated_customer, notes[])
    """
    c = dict(customer or {})
    notes: List[str] = []

    parts = split_edit_parts(message)

    for raw in parts:
        txt = raw.strip()
        low = txt.lower()

        # strip leading verbs
        for prefix in ("edit ", "edit:", "add ", "add:", "update ", "update:"):
            if low.startswith(prefix):
                txt = txt[len(prefix):].strip()
                low = txt.lower()
                break

        if not txt:
            continue

        # --- Explicit field targets first ---
        # email:
        if low.startswith("email"):
            email = _extract_email(txt)
            if email:
                c["Email"] = email
                notes.append("Email updated")
            continue

        # phone:
        if low.startswith("phone") or low.startswith("cell") or low.startswith("mobile"):
            ph = _extract_phone_candidate(txt)
            if ph:
                c["Phone"] = ph
                notes.append("Phone updated")
            continue

        # birthday:
        if low.startswith("birthday") or low.startswith("bday") or low.startswith("dob"):
            b = normalize_birthday(txt.replace("birthday", "").replace("bday", "").replace("dob", "").strip())
            if b:
                c["Birthday"] = b
                notes.append("Birthday updated")
            continue

        # address:
        if low.startswith("address"):
            addr = txt.replace("address", "", 1).strip(": ").strip()
            if addr:
                # ✅ Try smart parse first
                parsed = parse_address_line(addr)
                if parsed:
                    c.update(parsed)
                    notes.append("Address updated")
                    continue

                # Fallback: your existing comma split
                if "," in addr:
                    chunks = [x.strip().strip(",") for x in addr.split(",") if x.strip()]
                    if len(chunks) >= 2:
                        c["Street"] = chunks[0]
                        c["City"] = chunks[1]
                        if len(chunks) >= 3:
                            stzip = chunks[2]
                            z = _extract_zip(stzip)
                            if z:
                                c["Postal Code"] = z
                            st_only = re.sub(r"\b\d{5}\b", "", stzip).strip()
                            if st_only:
                                c["State"] = st_only
                        notes.append("Address updated")
                        continue

                # Final fallback: at least save it
                c["Street"] = addr
                notes.append("Address updated (street)")
            continue

        # --- Guess by format ---
        # Email guess
        if _looks_like_email(txt):
            c["Email"] = _extract_email(txt)
            notes.append("Email updated")
            continue

        # Birthday guess
        if _looks_like_birthday(txt):
            b = normalize_birthday(txt)
            if b:
                c["Birthday"] = b
                notes.append("Birthday updated")
                continue

        # Phone guess
        ph = _extract_phone_candidate(txt)
        if ph:
            c["Phone"] = ph
            notes.append("Phone updated")
            continue

        # ✅ Address guess (must be BEFORE zip guess)
        parsed = parse_address_line(txt)
        if parsed:
            c.update(parsed)
            notes.append("Address updated")
            continue

        # Zip guess
        z = _extract_zip(txt)
        if z:
            c["Postal Code"] = z
            notes.append("Postal code updated")
            continue

        # Fallback: if they typed something else, ignore but keep a note
        notes.append(f"Couldn’t apply: “{raw}”")

    # Clean punctuation that causes "Street," to get saved to JSON
    for k in ("Street", "City", "State"):
        if k in c and isinstance(c[k], str):
            c[k] = c[k].strip().rstrip(",")

    # Re-normalize (important!)
    c["Phone"] = normalize_phone(c.get("Phone", ""))
    c["Birthday"] = normalize_birthday(c.get("Birthday", ""))
    c["State"] = normalize_state(c.get("State", ""))

    return c, notes

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
        self._catalog_cache = {}  # {"en": [...], "es": [...]}

    ##
    def handle_message(self, message: str, consultant_id: int, session_id: Optional[int] = None) -> ChatReply:
        sid = int(session_id or consultant_id)
        state = load_session_state(session_id=sid)

        from auth_core import get_consultant
        from db import tx
        from crm_store import find_customers_by_name, format_customer_card

        consultant = get_consultant(consultant_id)
        language = (consultant.get("language", "en") if consultant else "en") or "en"
        language = language.strip().lower()

        ui = UI_ES if language == "es" else UI_EN

        if language not in self._catalog_cache:
            catalog_path = get_catalog_path_for_language(language)
            self._catalog_cache[language] = load_catalog(catalog_path)

        catalog = self._catalog_cache[language]

        last_customer = state.get("last_customer")
        pending = state.get("pending")
        msg = (message or "").strip()

        if not msg:
            return ChatReply(ui["empty_prompt"])

        lowered = msg.lower()

        # -------------------------
        # CRM quick lookup: customer info (no LLM call)
        # -------------------------
        if not pending:
            triggers = ("what's", "whats", "what is", "lookup", "show", "info on", "information for")
            if any(t in lowered for t in triggers) and "order" not in lowered:
                import re

                m_clean = re.sub(r"[^\w\s']", " ", msg).strip()
                stop_words = {
                    "what", "is", "whats", "what's", "info", "information", "for", "on",
                    "lookup", "show", "me", "please", "customer", "customers"
                }

                tokens = []
                for raw in m_clean.split():
                    t = raw.strip()
                    if t.lower().endswith("'s"):
                        t = t[:-2]
                    if t and t.lower() not in stop_words:
                        tokens.append(t)

                guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else msg)

                with tx() as (conn, cur):
                    matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)

                if len(matches) == 0:
                    return ChatReply(
                        f"I couldn’t find **{guess}** in your saved customers yet. "
                        f"Want to add her now? (Paste: name, phone, address, email.)"
                    )

                if len(matches) == 1:
                    return ChatReply(format_customer_card(matches[0]))

                lines = ["I found a few matches — who did you mean?"]
                for c in matches[:10]:
                    full = f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip()
                    hint = " • ".join([p for p in [c.get("phone"), c.get("email")] if p]) or "—"
                    lines.append(f"- {full} ({hint})")
                return ChatReply("\n".join(lines))

        # -------------------------
        # CRM quick lookup: recent orders (no LLM call)
        # -------------------------
        if not pending:
            if "order" in lowered and any(k in lowered for k in ["last", "recent", "show", "lookup", "history"]):
                import re
                from crm_store import get_recent_orders_for_customer, format_recent_orders

                m_clean = re.sub(r"[^\w\s']", " ", msg).strip()
                stop_words = {
                    "last", "recent", "show", "lookup", "order", "orders", "history",
                    "for", "on", "info", "information", "what", "is", "whats", "what's",
                    "me", "please", "customer"
                }

                tokens = []
                for raw in m_clean.split():
                    t = raw.strip()
                    if t.lower().endswith("'s"):
                        t = t[:-2]
                    if t and t.lower() not in stop_words:
                        tokens.append(t)

                guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else msg)

                with tx() as (conn, cur):
                    matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)

                    if len(matches) == 0:
                        return ChatReply(f"I couldn’t find **{guess}** in your saved customers yet.")

                    if len(matches) > 1:
                        lines = ["I found a few matches — who did you mean?"]
                        for c in matches[:10]:
                            full = f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip()
                            hint = " • ".join([p for p in [c.get('phone'), c.get('email')] if p]) or "—"
                            lines.append(f"- {full} ({hint})")
                        return ChatReply("\n".join(lines))

                    c = matches[0]
                    customer_id = int(c["id"])
                    customer_name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()

                    orders = get_recent_orders_for_customer(cur, customer_id=customer_id, limit=3)

                return ChatReply(format_recent_orders(customer_name, orders))

        # Cancel command (works even outside pending)
        if msg.lower() in ("cancel", "stop", "nevermind", "never mind"):
            state["pending"] = None
            save_session_state(state, session_id=sid)
            return ChatReply(ui["canceled"])

        # -------------------------
        # Pending flows
        # -------------------------
        if pending:
            kind = pending.get("kind")

            if kind == "customer_confirm":
                if yes(msg):
                    customer = pending["customer"]

                    # 1) Save to CRM (permanent)
                    from crm_store import upsert_customer_from_pending

                    with tx() as (conn, cur):
                        upsert_customer_from_pending(cur, consultant_id=consultant_id, customer=customer)

                    # 2) Keep existing behavior: job for worker/playwright
                    insert_job("NEW_CUSTOMER", customer, consultant_id=consultant_id)

                    state["last_customer"] = customer
                    state["pending"] = None
                    save_session_state(state, session_id=sid)

                    return ChatReply(
                        ui["cust_confirmed"].format(
                            first=customer.get("First Name", "").strip(),
                            last=customer.get("Last Name", "").strip(),
                        )
                    )

                if no(msg):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["cust_reject"])

                updated, notes = apply_customer_edits(pending["customer"], msg)
                pending["customer"] = updated
                state["pending"] = pending
                save_session_state(state, session_id=sid)

                note_line = ""
                if notes:
                    note_line = "Updated: " + ", ".join(notes[:3]) + ("…" if len(notes) > 3 else "") + "\n\n"

                return ChatReply(note_line + self._format_customer_confirm(updated, ui))

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
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                if no(msg):
                    state["pending"] = {
                        "kind": "order_line_pick_top5_or_search",
                        "order": order,
                        "line_index": line_index,
                        "matches": matches[:MATCH_LIMIT],
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches))

                return ChatReply(ui["reply_yes_no_qty"])

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
                        return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                new_matches = best_matches(catalog, msg, limit=MATCH_LIMIT)
                if not new_matches:
                    return ChatReply(ui["no_matches"])

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
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                if action == "remove":
                    target = (rest or "").strip()
                    if not target:
                        return ChatReply("Tell me what to remove, e.g. `remove 2` or `remove satin lips`.")
                    removed = self._remove_line(order, target)
                    if not removed:
                        return ChatReply("I couldn’t find that item to remove. Try `remove 2` or part of the name.")
                    state["pending"] = {"kind": "order_confirm", "order": order}
                    save_session_state(state, session_id=sid)
                    return ChatReply(self._format_order_confirm(order, ui) + "\n\n" + ui["order_adjust_hint"])

                if yes(msg):
                    cust_first = order["customer"]["First Name"]
                    cust_last = order["customer"]["Last Name"]

                    # 1) Save order + items to CRM (permanent, even if Playwright fails)
                    from crm_store import get_customer_id_by_name, create_order_from_confirmed, upsert_customer_from_pending

                    with tx() as (conn, cur):
                        customer_id = get_customer_id_by_name(cur, consultant_id, cust_first, cust_last)

                        if customer_id is None:
                            customer_id = upsert_customer_from_pending(
                                cur,
                                consultant_id=consultant_id,
                                customer={"First Name": cust_first, "Last Name": cust_last},
                            )

                        create_order_from_confirmed(
                            cur,
                            consultant_id=consultant_id,
                            customer_id=customer_id,
                            order_lines=order["lines"],
                            source="chat",
                        )

                    # 2) Keep existing behavior: create jobs for worker/playwright
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
                    return ChatReply(ui["order_confirmed"].format(first=cust_first, last=cust_last))

                if no(msg):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["order_reject"])

                return ChatReply("Reply yes/no — or say `add ...` / `remove ...` to adjust the order.")

        # -------------------------
        # Normal parse
        # -------------------------
        try:
            parsed = parse_with_openai(self.client, msg, last_customer)
        except Exception as e:
            return ChatReply(ui["parse_error"].format(err=str(e)))

        if parsed.get("type") == "customer":
            customer = parsed.get("customer") or {}
            customer["State"] = normalize_state(customer.get("State", ""))
            customer["Phone"] = normalize_phone(customer.get("Phone", ""))
            customer["Birthday"] = normalize_birthday(customer.get("Birthday", ""))

            state["pending"] = {"kind": "customer_confirm", "customer": customer}
            save_session_state(state, session_id=sid)
            return ChatReply(self._format_customer_confirm(customer, ui))

        if parsed.get("type") == "order":
            order = parsed.get("order") or {}
            cust_first = (order.get("customer_first") or "").strip()
            cust_last = (order.get("customer_last") or "").strip()

            if (not cust_first or not cust_last) and last_customer:
                cust_first = (last_customer.get("First Name") or "").strip()
                cust_last = (last_customer.get("Last Name") or "").strip()

            if not cust_first or not cust_last:
                return ChatReply(ui["need_customer_for_order"])

            items = order.get("items") or []
            if not items:
                return ChatReply(ui["need_items"])

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
            return ChatReply(self._format_order_confirm(order_draft, ui) + "\n\n" + ui["order_adjust_hint"])

        return ChatReply(ui["cant_tell"])

# Internal helper methods
# -------------------------
    def _continue_resolving_and_reply(
        self,
        state: dict,
        order: dict,
        consultant_id: int,
        sid: int,
        catalog: List[dict],
        ui: dict,  # 👈 ADD THIS
    ) -> ChatReply:

        while True:
            nxt = self._next_unresolved_index(order)

            if nxt is None:
                state["pending"] = {"kind": "order_confirm", "order": order}
                state["last_customer"] = order["customer"]
                save_session_state(state, session_id=sid)

                return ChatReply(
                    self._format_order_confirm(order, ui)
                    + "\n\n"
                    + ui["order_adjust_hint"]
                )

            picked, _m = auto_pick_match(catalog, order["lines"][nxt]["text"])
            if picked:
                order["lines"][nxt]["chosen"] = picked
                continue

            top, matches, _ = self._start_line_resolution(catalog, order, nxt)
            pick_idx = llm_pick_from_candidates(
                self.client,
                order["lines"][nxt]["text"],
                matches,
            )

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

    ## format_customer_confirm
    def _format_customer_confirm(self, customer: dict, ui: dict) -> str:
        street = (customer.get("Street") or "").strip()
        city = (customer.get("City") or "").strip()
        st = (customer.get("State") or "").strip()
        postal = (customer.get("Postal Code") or "").strip()

        # Build address safely (no double commas)
        parts = []
        if street:
            parts.append(street.rstrip(","))
        if city:
            parts.append(city.rstrip(","))

        line2 = " ".join([p for p in [st, postal] if p]).strip()
        if line2:
            parts.append(line2)

        addr = ", ".join(parts) if parts else ui["none"]

        phone_disp = format_phone_display(customer.get("Phone", ""))
        birthday_disp = birthday_display(customer.get("Birthday", ""))

        return (
            f"{ui['cust_submit_intro']}\n"
            f"• {ui['name']}: {customer.get('First Name','').strip()} {customer.get('Last Name','').strip()}\n"
            f"• {ui['email']}: {(customer.get('Email','') or '').strip() or ui['none']}\n"
            f"• {ui['phone']}: {phone_disp or ui['none']}\n"
            f"• {ui['address']}: {addr}\n"
            f"• {ui['birthday']}: {birthday_disp or ui['none']}\n"
            f"{ui['cust_confirm_q']}\n"
            f"{ui['cust_edit_hint']}"
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

    def _format_order_confirm(self, order: dict, ui: dict) -> str:
        cust = order["customer"]
        out = [ui["order_intro"].format(first=cust["First Name"], last=cust["Last Name"])]

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
            out.append(ui["estimated_total"].format(total=f"${total:.2f}"))

        out.append(ui["order_confirm_q"])
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
