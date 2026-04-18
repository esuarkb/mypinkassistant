## update sql placeholders 2-14 10:15am

# mk_chat_core.py
import html as _html
import json
import calendar
import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from crm_store import find_customers_by_name, format_customer_card, get_recent_orders_for_customer
from intent_router import parse_intent
from inventory_store import (
    upsert_inventory_quantity,
    get_inventory_item,
    list_inventory,
)

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

def maybe_queue_initial_customer_import(cur, consultant_id: int) -> bool:
    """
    Queue the first silent MyCustomers import after successful billing activation.
    Returns True if a job was queued, else False.
    """
    cur.execute(
        f"""
        SELECT
            billing_status,
            intouch_username,
            intouch_password_enc,
            initial_customer_import_queued
        FROM consultants
        WHERE id = {PH}
        LIMIT 1
        """,
        (consultant_id,),
    )
    row = cur.fetchone()
    if not row:
        return False

    if isinstance(row, dict):
        billing_status = (row.get("billing_status") or "").strip().lower()
        intouch_username = (row.get("intouch_username") or "").strip()
        intouch_password_enc = (row.get("intouch_password_enc") or "").strip()
        already_queued = int(row.get("initial_customer_import_queued") or 0)
    else:
        billing_status = (row[0] or "").strip().lower()
        intouch_username = (row[1] or "").strip()
        intouch_password_enc = (row[2] or "").strip()
        already_queued = int(row[3] or 0)

    if billing_status not in ("active", "trialing"):
        return False

    if already_queued:
        return False

    if not intouch_username or not intouch_password_enc:
        return False

    insert_job(
        "IMPORT_CUSTOMERS",
        {"silent_initial_sync": True},
        consultant_id=consultant_id,
    )

    cur.execute(
        f"""
        UPDATE consultants
        SET initial_customer_import_queued = 1
        WHERE id = {PH}
        """,
        (consultant_id,),
    )

    return True


# -------------------------
# Catalog
# -------------------------
def load_catalog(path: Path) -> List[dict]:
    """
    Loads catalog CSV with headers: sku (lowercase), product_name, price, search_terms
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
            name = (row.get("product_name") or "").strip().replace("®", "")
            price = row.get("price")

            # ✅ NEW
            search_terms = (row.get("search_terms") or "").strip()

            if not sku or not name:
                continue

            name_l = name.lower()
            if "sample" in name_l:
                continue
            if "the look" in name_l or "booklet" in name_l or "look (" in name_l:
                continue
            if "(old sku)" in name_l:
                continue

            try:
                price_val = float(price) if price else None
            except ValueError:
                price_val = None

            items.append({
                "sku": sku,
                "product_name": name,
                "price": price_val,
                "search_terms": search_terms,
                "search_string": f"{name} {search_terms}".strip(),
            })

    return items


def fmt_price(p: Any) -> str:
    if isinstance(p, (int, float)):
        return f"${p:.2f}"
    return ""


_SEARCH_STOP_WORDS = {"mary", "kay"}

def best_matches(catalog: List[dict], query: str, limit: int = 5, min_score: int = 30) -> List[dict]:
    q = (query or "").lower().strip()
    q_compact = re.sub(r"\s+", " ", q)

    # Strip noise words that appear in most product names and hurt WRatio scoring
    q_words = [w for w in q_compact.split() if w not in _SEARCH_STOP_WORDS]
    if q_words:
        q = " ".join(q_words)

    anchors = [
        "4-in-1",
        "4 in 1",
        "timewise 3d",
        "3d",
        "cc cream",
        "miracle set",
        "repair set",
        "volu-firm set",
        "satin hands",
        "satin lips",
        "foundation primer",
        "foundation brush",
        "shimmer eye shadow stick",
        "undereye corrector",
        "eye renewal cream",
        "repair eye cream",
        "volu-firm eye cream",
        "volu firm eye cream",
        "timewise repair eye cream",
        "eye cream",
        "roll-up bag",
        "great heights",
        "sheer illusion",
        "cleanser",
    ]

    anchored = None
    for a in anchors:
        if a in q_compact:
            anchored = a
            break

    candidates = catalog
    if anchored:
        a_l = anchored.lower()
        words = a_l.split()
        filtered = [
            c for c in catalog
            if all(
                w in f"{c['product_name'].lower()} {(c.get('search_terms') or '').lower()}"
                for w in words
            )
        ]
        if filtered:
            candidates = filtered

    # Pre-filter: keep only candidates that contain at least one significant
    # query word (3+ chars) as a whole word. This prevents short queries like
    # "charcoal" from matching unrelated products via character-level fuzz.
    sig_tokens = [t for t in re.split(r"\s+", q) if len(t) >= 3]
    if sig_tokens:
        pattern = "|".join(re.escape(t) for t in sig_tokens)
        candidates = [
            c for c in candidates
            if re.search(rf"\b(?:{pattern})\b", c["search_string"], re.IGNORECASE)
        ]

    names = [c["search_string"] for c in candidates]
    results = process.extract(q, names, scorer=fuzz.WRatio, limit=limit)

    q_words = {w for w in re.split(r"\s+", q) if len(w) >= 3}

    matches: List[dict] = []
    for name, score, idx in results:
        if score < min_score:
            continue
        c = candidates[idx]
        name_l = c["product_name"].lower()
        word_hits = sum(1 for w in q_words if re.search(rf"\b{re.escape(w)}\b", name_l))
        on_the_go = 1 if "the go set" in name_l else 0
        matches.append(
            {"sku": c["sku"], "product_name": c["product_name"], "price": c["price"], "score": score, "_hits": word_hits, "_otg": on_the_go}
        )

    matches.sort(key=lambda m: (m["score"], m["_hits"], -m["_otg"]), reverse=True)
    for m in matches:
        del m["_hits"]
        del m["_otg"]
    return matches


def auto_pick_match(catalog: List[dict], query: str) -> Tuple[Optional[dict], List[dict]]:
    q = (query or "").strip().lower()
    matches = best_matches(catalog, query, limit=MATCH_LIMIT)
    if not matches:
        return None, matches

    # Broad / ambiguous product phrases should not auto-pick
    broad_queries = {
        "eye cream",
        "cleanser",
        "foundation",
        "lipstick",
        "mascara",
        "serum",
        "moisturizer",
        "night cream",
        "day cream",
    }
    if q in broad_queries:
        return None, matches

    top = matches[0]
    second = matches[1] if len(matches) > 1 else {"score": 0}

    if top["score"] >= 88 and (top["score"] - second["score"]) >= 6:
        return top, matches

    return None, matches

def _extract_order_name_hint(message: str) -> tuple[str, str]:
    """
    Best-effort extraction of customer name from raw order text like:
      - 'new order for Jerri beach bronze...'
      - 'order for Cierra Guinn mascara'
    Returns (first, last) or ("","") if no clear hint.
    """
    import re

    msg = (message or "").strip()

    # Capture text right after "new order for" or "order for"
    m = re.search(r"\b(?:new\s+order|order)\s+for\s+(.+)$", msg, re.IGNORECASE)
    if not m:
        return "", ""

    tail = m.group(1).strip()
    if not tail:
        return "", ""

    # Split into words
    words = tail.split()
    if not words:
        return "", ""

    # Stop once we hit something that looks like product text
    stop_words = {
        "one", "two", "three", "four", "five",
        "a", "an",
        "and",
        "ultimate", "mascara", "bronze", "beach", "foundation", "primer",
        "cc", "cream", "brush", "charcoal", "repair", "set", "lipstick",
        "ordered", "wants", "needs"
    }

    name_parts = []
    for w in words:
        wl = w.lower().strip(",")
        if wl in stop_words:
            break
        name_parts.append(w.strip(","))
        if len(name_parts) >= 2:
            break

    if not name_parts:
        return "", ""

    first = name_parts[0]
    last = name_parts[1] if len(name_parts) >= 2 else ""
    return first, last

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
        "- If the user says 'ultimate', prefer items with 'Ultimate' in the name.\n"
        "- If the user says 'go set' or 'travel', prefer items with 'Go Set' in the name.\n"
        "- If the user does NOT say 'ultimate', 'beyond', or 'go', prefer the standard base set (shortest name, lowest price).\n"
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
            timeout=30,
        )
        txt = (resp.output[0].content[0].text or "").strip()
        data = extract_json_object(txt) or {}
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
def extract_json_object(s: str) -> Optional[dict]:
    s = (s or "").strip()
    if not s:
        return None

    # Remove ```json fences if present
    if s.startswith("```"):
        s = s.strip()
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()

    # Find JSON object boundaries
    i = s.find("{")
    j = s.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return None

    candidate = s[i : j + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def parse_with_openai(client: OpenAI, text: str, last_customer: Optional[str]) -> dict:
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
        '    "Street2": "",\n'
        '    "City": "",\n'
        '    "State": "",\n'
        '    "Postal Code": "",\n'
        '    "Birthday": "",\n'
        '    "Tags": ""\n'
        "  }\n"
        "}\n\n"
        "If ORDER:\n"
        "{\n"
        '  "type": "order",\n'
        '  "order": {\n'
        '    "customer_first": "",\n'
        '    "customer_last": "",\n'
        '    "fulfillment_method": "inventory",\n'
        '    "leave_pending": false,\n'
        '    "order_date": "",\n'
        '    "items": [{"text": "", "qty": 1}]\n'
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- State must be full name (e.g., Alabama).\n"
        "- Street is the street number and name only. Put apt/unit/suite/lot/# info in Street2.\n"
        "- Extract comma-separated tags from 'tag:' or 'tags:' keyword into Tags as a plain comma-separated string.\n"
        "- Birthday may be provided as MM/DD, Month Day, or YYYY-MM-DD. Output as YYYY-MM-DD. If year missing, use 2000.\n"
        "- Each word or phrase separated by 'and' or a comma is a separate item unless it is clearly a shade/variant of the immediately adjacent product (e.g. 'Normal/Dry', 'Ivory 1', 'Berry Kissable'). When in doubt, treat it as a separate product.\n"
        "- For shades/colors/variants (Normal/Dry, Combination/Oily), include them in item text if present.\n"
        "- If the user says a variant applies to multiple items (e.g., 'normal/dry both'), append that variant phrase to each affected item.\n"
        "- Do NOT treat numbers that are part of a product name as quantity (examples: '4-in-1 cleanser', '2-in-1', '3D').\n"
        "- Only set qty > 1 if the user explicitly indicates quantity (two, x2, qty 2, three of them, etc.). Otherwise qty must be 1.\n"
        "- If the user says a quantity change like 'make that 2' or 'change it to 3', do NOT output a new order. That will be handled separately.\n"
        '- Set fulfillment_method to "cds" if the user mentions CDS or customer delivery. Default is "inventory".\n'
        '- Do NOT include "cds", "pending", "customer delivery" as items in the items list — these are order flags only.\n'
        '- Set leave_pending to true if the user says "pending order", "save as pending", or "leave it pending". Default is false.\n'
        '- A CDS order always implies leave_pending true.\n'
        f"- Today's date is {__import__('datetime').date.today().isoformat()}. Extract order_date if a specific date is mentioned (e.g. 'April 5', 'last Tuesday', 'sold this on March 10', '1-16-24', '1/16/24', '01/16/2024', 'Jan 16 2024'). Output as YYYY-MM-DD. For 2-digit years, assume 2000s (e.g. '24' = 2024). Leave empty string if no full specific date is clearly stated — do not guess from a day number or month alone.\n"
    )

    last_ctx = ""
    if last_customer and last_customer.strip():
        last_ctx = f"Last customer: {last_customer.strip()}\n"

    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": last_ctx + text},
        ],
        timeout=30,
    )

    output_text = ""
    try:
        # Some responses have multiple output blocks; join all text we can find
        parts = []
        for out in (resp.output or []):
            for c in (getattr(out, "content", None) or []):
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
        output_text = "\n".join(parts).strip()
    except Exception:
        # fallback (your original path)
        try:
            output_text = (resp.output[0].content[0].text or "").strip()
        except Exception:
            output_text = ""

    # ✅ TEST LINES (keep these until it's stable)
    print("---- OPENAI RAW TEXT (repr) ----")
    print(repr(output_text))
    print("---- END RAW TEXT ----")

    data = extract_json_object(output_text)

    # If the model returned nothing usable, treat it as unknown instead of erroring
    if not data:
        return {"type": "unknown"}

    # If JSON exists but is missing the expected structure
    if not isinstance(data, dict) or not data.get("type"):
        return {"type": "unknown"}

    return data


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
    "DC": "Washington, D.C.",
}

def normalize_state(state: str) -> str:
    s = (state or "").strip()
    if not s:
        return ""
    # Normalize DC variants
    if s.upper() in ("DC", "D.C.", "WASHINGTON DC", "WASHINGTON D.C.", "DISTRICT OF COLUMBIA"):
        return "Washington, D.C."
    if len(s) == 2:
        return STATE_MAP.get(s.upper(), s)
    return s

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

def _parse_small_number(text: str) -> Optional[int]:
    s = (text or "").strip().lower()
    if s.isdigit():
        return int(s)
    return NUMBER_WORDS.get(s)

STREET_SUFFIXES = (
    "st", "street", "rd", "road", "ave", "avenue", "blvd", "boulevard",
    "dr", "drive", "ln", "lane", "ct", "court", "cir", "circle",
    "pkwy", "parkway", "hwy", "highway", "pl", "place", "way"
)

def _append_unit_suffix_if_present(street: str, extra: str) -> tuple:
    unit_words = ("apt", "apartment", "unit", "lot", "suite", "ste", "#", "trlr", "trailer", "bldg", "building", "spc", "space")
    extra = (extra or "").strip()

    if extra:
        if not any(word in extra.lower() for word in unit_words):
            return street, ""

        # Stop before anything that looks like a date, like 10-14 or 10/14
        parts = extra.split()
        clean_parts = []
        for p in parts:
            if re.match(r"\d{1,2}[-/]\d{1,2}$", p):
                break
            clean_parts.append(p)

        extra_clean = " ".join(clean_parts).strip()
        return street, extra_clean if extra_clean else ""

    # No extra — check if the street string itself contains a unit keyword
    # e.g. "555 5th st apt 5" -> ("555 5th st", "apt 5")
    street_lower = street.lower()
    for word in unit_words:
        m = re.search(r'\b' + re.escape(word) + r'\b', street_lower)
        if m:
            base = street[:m.start()].strip()
            unit = street[m.start():].strip()
            if base:
                return base, unit

    return street, ""

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

    # Special case: "31 W East st madison, WI 35976"
    # Split street at a real street suffix, then treat the rest as city/state/zip.
    m = re.match(
        r"^(?P<street>.+?\b(?:st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|ct|court|cir|circle|pkwy|parkway|hwy|highway|pl|place|way)\b)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s*,\s*(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt,
        re.IGNORECASE,
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # Special case (no comma): "232 Queens St Sun Prairie WI 53590"
    # Same suffix-split logic as above but without requiring a comma before state.
    m = re.match(
        r"^(?P<street>.+?\b(?:st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|ct|court|cir|circle|pkwy|parkway|hwy|highway|pl|place|way)\b)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s+(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt,
        re.IGNORECASE,
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # Pull ZIP first (required for full parse)
    mzip = re.search(r"\b(\d{5})(?:-\d{4})?\b", txt)
    zip5 = mzip.group(1) if mzip else ""

    # ---------- Pattern A: "street city, ST ZIP"
    # Example: "444 4th St Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s*,\s*(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip().rstrip(",").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern B: "street, city, ST ZIP"
    # Example: "444 4th St, Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s*,\s*(?P<city>.+?)\s*,\s*(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern D: "street city ST ZIP" (no commas)
    # Example: "333 3rd st arab al 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s+(?P<state>[A-Za-z]{2,})\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
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

def normalize_city(city: str) -> str:
    s = (city or "").strip()
    if not s:
        return ""
    # Fix "st X" → "St. X" (e.g. "st paul" → "St. Paul")
    # Also handle "st." prefix and bleed cases like "st st paul" or "st. st paul"
    s = re.sub(r"^st\.?\s+st\.?\s*", "St. ", s, flags=re.IGNORECASE)
    s = re.sub(r"^st\.?\s+", "St. ", s, flags=re.IGNORECASE)
    # Title case the result
    return s.title()


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

    # Full date
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        y, mo, d = map(int, s.split("-"))
        month = calendar.month_name[mo]
        # Year 2000 is our default placeholder when no year was provided — don't show it
        if y == 2000:
            return f"{month} {d}"
        return f"{month} {d}, {y}"

    # Month/day only
    if re.fullmatch(r"\d{2}-\d{2}", s):
        mo, d = map(int, s.split("-"))
        month = calendar.month_name[mo]
        return f"{month} {d}"

    return ""

UI_EN = {
    "empty_prompt": "Say something like: “new customer Jane Doe …” or “order for Jane Doe: …”",
    "canceled": "Okay — canceled. Ready for your new customer or order.",

    "cust_submit_intro": "Okay — here's the customer I'm about to submit:",
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "address": "Address",
    "birthday": "Birthday",
    "none": "(none)",
    "cust_confirm_q": "Does that look right? (yes/no)",
    "cust_edit_hint": "If you need to add or edit just add the correct information in chat.",

    "order_intro": "Okay — I have this order for {first} {last}:",
    "estimated_total": "Estimated retail total: {total}",
    "order_confirm_q": "Does that sound right? (yes/no)",

    "need_customer_for_order": "Who is this order for? Please tell me the customer name and paste the order again.",
    "need_items": "What items should I add to the order?",
    "got_it_ordering_for": "Got it — order for {name}.",
    "no_matches": "No close matches. Try rewording the item (brand/line/shade helps).",
    "reply_yes_no_qty": "Reply yes or no — or add a quantity like 'x2'",
    "order_adjust_hint": "You can also say `add` or `remove`, or `cancel` to start over.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Parse error: {err}",
    "cant_tell": "I couldn't tell if that was a new customer or an order. Try rephrasing.",
    "cust_confirmed": "✅ {first} {last} confirmed. Adding to MyCustomers now.",
    "cust_reject": "No problem — Send the corrected customer info and I'll try again.",
    "order_confirmed": "✅ Order for {first} {last} confirmed. Sending to MyCustomers now.",
    "order_reject": "Okay — paste the corrected order and I'll rebuild the summary.",

    "no_catalog_match": "I couldn't match that product in the catalog. Try rewording it.",
    "no_customer_found": "I couldn't find {name} in your saved customers.",
    "no_customer_found_yet": "I couldn't find {name} in your saved customers yet.",
    "no_customer_id": "I couldn't find a customer with ID {cid}.",
    "customer_spent": "{name} has spent ${total} ({period}).",
    "who_is_customer": "Who is the customer? Try: \u201cshow Jane\u2019s info\u201d.",
    "multiple_matches": "Multiple matches: Reply with 1, 2, or 3 — or type cancel.",
    "lost_order_draft": "I lost track of that order draft. Please paste the order again.",
    "what_to_do_customer": "Okay — what would you like to do with that customer?",
    "inventory_added": "Added {qty} of {product} to your inventory. You currently have {current} on hand.",
    "inventory_removed": "Removed {qty} of {product} from your inventory. You currently have {current} on hand.",
    "inventory_set": "Set {product} inventory to {qty}. You currently have {current} on hand.",
    "inventory_report": "Here's your inventory report: {link}",
    "reply_yes_no": "Reply yes or no.",
    "pick_match_5": "Pick the best match with 1-5, or type cancel.",
    "low_stock_set": "Got it — I'll flag {product} when you have fewer than {qty} on hand.",
    "confirming_customer": "You're confirming a new customer. Reply yes or no, or type cancel to retry.",
    "deleted_customer": "✅ Deleted {name} from MyPinkAssistant (MyCustomers was not changed).",
    "delete_failed": "I couldn't delete that customer (maybe it was already removed).",
    "delete_confirm_prompt": "To confirm deletion, type DELETE. Or type `cancel`.",
    "no_items_caught": "I didn't catch any items — try again with the product names.",
    "add_hint": "Tell me what to add, e.g. `add satin hands`.",
    "remove_hint": "Tell me what to remove, e.g. `remove 1` or `remove charcoal`.",
    "remove_not_found": "I couldn't find that item to remove. Try `remove 1` or part of the name.",
    "confirming_order": "You're confirming an order. Reply yes or no, or say add or remove to edit the order.",
    "reply_yes_no_adjust": "Reply yes or no — or say add or remove to adjust the order.",
    "trouble": "I'm having a little trouble right now, please try again in a moment.",
    "customer_not_in_mc": "I'm not finding {name} in MyCustomers. If you are sure they are already in MyCustomers, you can go to Settings and tap Import MyCustomers to sync the latest. Otherwise, we will need to add {name} as a new customer first.",
    "propose_top": "I think you mean: {line}. Is that right? (yes/no)",
    "render_top5_intro": "Got it \u2014 select the best match (reply {range}), or type different search words and I'll search again:",
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
    "cust_edit_hint": "Si necesitas agregar o editar, escribe la información correcta en el chat.",

    "order_intro": "Perfecto — tengo este pedido para {first} {last}:",
    "estimated_total": "Total estimado (precio): {total}",
    "order_confirm_q": "¿Suena bien? (sí/no)",

    "need_customer_for_order": "¿Para quién es este pedido? Dime el nombre del cliente y vuelve a pegar el pedido.",
    "need_items": "¿Qué artículos debo agregar al pedido?",
    "got_it_ordering_for": "Listo — pedido para {name}.",
    "no_matches": "No encuentro coincidencias cercanas. Intenta describirlo de otra forma (línea/tono/variante ayuda).",
    "reply_yes_no_qty": "Responde sí/no — o escribe una cantidad como `2` o `x2`.",
    "order_adjust_hint": "También puedes decir `add ...` o `remove ...`.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Error al interpretar: {err}",
    "cant_tell": "No pude determinar si era un cliente nuevo o un pedido. Intenta reformularlo.",
    "cust_confirmed": "✅ {first} {last} confirmado. Agregando a MyCustomers ahora.",
    "cust_reject": "No hay problema — envíame la info corregida del cliente y lo intento de nuevo.",
    "order_confirmed": "✅ Pedido para {first} {last} confirmado. Enviándolo a MyCustomers ahora.",
    "order_reject": "Listo — pega el pedido corregido y lo vuelvo a armar.",

    "no_catalog_match": "No pude encontrar ese producto en el catálogo. Intenta describirlo de otra forma.",
    "no_customer_found": "No encontré a {name} en tus clientes guardados.",
    "no_customer_found_yet": "Aún no encontré a {name} en tus clientes guardados.",
    "no_customer_id": "No encontré un cliente con ID {cid}.",
    "customer_spent": "{name} ha gastado ${total} ({period}).",
    "who_is_customer": "¿Quién es el cliente? Prueba: \u201cinfo de Jane\u201d.",
    "multiple_matches": "Varias coincidencias: responde con 1, 2 o 3 — o escribe cancelar.",
    "lost_order_draft": "Perdí el borrador del pedido. Por favor, vuelve a pegar el pedido.",
    "what_to_do_customer": "Listo — ¿qué quieres hacer con ese cliente?",
    "inventory_added": "Agregué {qty} de {product} a tu inventario. Actualmente tienes {current} disponibles.",
    "inventory_removed": "Eliminé {qty} de {product} de tu inventario. Actualmente tienes {current} disponibles.",
    "inventory_set": "Actualicé el inventario de {product} a {qty}. Actualmente tienes {current} disponibles.",
    "inventory_report": "Aquí está tu reporte de inventario: {link}",
    "reply_yes_no": "Responde sí o no.",
    "pick_match_5": "Elige la mejor opción del 1 al 5, o escribe cancelar.",
    "low_stock_set": "Listo — te avisaré sobre {product} cuando tengas menos de {qty} disponibles.",
    "confirming_customer": "Estás confirmando un nuevo cliente. Responde sí o no, o escribe cancelar para reintentar.",
    "deleted_customer": "✅ {name} eliminado de MyPinkAssistant (MyCustomers no fue modificado).",
    "delete_failed": "No pude eliminar ese cliente (quizás ya fue removido).",
    "delete_confirm_prompt": "Para confirmar la eliminación, escribe ELIMINAR. O escribe `cancelar`.",
    "no_items_caught": "No detecté ningún artículo — intenta de nuevo con los nombres de los productos.",
    "add_hint": "Dime qué agregar, por ejemplo: `add satin hands`.",
    "remove_hint": "Dime qué eliminar, por ejemplo: `remove 1` o `remove charcoal`.",
    "remove_not_found": "No encontré ese artículo para eliminarlo. Prueba `remove 1` o parte del nombre.",
    "confirming_order": "Estás confirmando un pedido. Responde sí o no, o di agregar o eliminar para editarlo.",
    "reply_yes_no_adjust": "Responde sí o no — o di agregar o eliminar para ajustar el pedido.",
    "trouble": "Estoy teniendo un pequeño problema ahora mismo, por favor intenta de nuevo en un momento.",
    "customer_not_in_mc": "No encuentro a {name} en MyCustomers. Si estás segura de que ya está en MyCustomers, ve a Configuración y toca Importar MyCustomers para sincronizar. De lo contrario, necesitaremos agregar a {name} como nueva cliente primero.",
    "propose_top": "Creo que te refieres a: {line}. ¿Es correcto? (sí/no)",
    "render_top5_intro": "Listo \u2014 elige la mejor opción (responde {range}), o escribe otras palabras de búsqueda:",
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

def _split_order_for_prefix(message: str) -> tuple[str, str]:
    """
    Splits messages like:
      'new order for Niiki satin hands, satin lips'
      'order for Cierra mascara'
    into:
      ('Niiki', 'satin hands, satin lips')
    or:
      ('Cierra', 'mascara')
    """
    import re

    msg = (message or "").strip()
    m = re.search(r"\b(?:new\s+order|order)\s+for\s+(.+)$", msg, re.IGNORECASE)
    if not m:
        return "", ""

    tail = m.group(1).strip()
    if not tail:
        return "", ""

    words = tail.split()
    if not words:
        return "", ""

    stop_words = {
        "one", "two", "three", "four", "five",
        "a", "an",
        "and",
        "ultimate", "mascara", "bronze", "beach", "foundation", "primer",
        "cc", "cream", "brush", "charcoal", "repair", "set", "lipstick",
        "satin", "hands", "lips", "ordered", "wants", "needs",
        "cds", "pending", "customer delivery", "customer delivery service",
    }

    name_parts = []
    item_start_idx = 0

    for i, w in enumerate(words):
        wl = w.lower().strip(",")
        if wl in stop_words:
            item_start_idx = i
            break
        name_parts.append(w.strip(","))
        item_start_idx = i + 1
        if len(name_parts) >= 2:
            break

    customer_hint = " ".join(name_parts).strip()
    # Take everything after the name boundary as items — do NOT filter stop words
    # out of the item text (they are product names, e.g. "charcoal", "repair set")
    item_hint = " ".join(words[item_start_idx:]).strip().strip(",").strip()

    return customer_hint, item_hint

def propose_top(top: dict, current_qty: int, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    q = int(current_qty or 1)
    qtxt = f" x{q}" if q != 1 else ""

    price_txt = fmt_price(top.get("price"))
    parts = [top["product_name"]]

    if price_txt:
        parts.append(price_txt)

    line = " ".join(parts) + qtxt

    return ui["propose_top"].format(line=line) + _QR_YN

def _qr(options: list) -> str:
    """HTML quick-reply buttons (shown on mobile only via CSS)."""
    btns = "".join(
        f'<button class="qr-btn qr-{opt["cls"]}" data-send="{opt["send"]}">{opt["label"]}</button>'
        for opt in options
    )
    return f'<div class="quick-replies">{btns}</div>'

_QR_YN = _qr([
    {"cls": "yes", "send": "yes", "label": "Yes"},
    {"cls": "no",  "send": "no",  "label": "No"},
])


def render_top5(matches: List[dict], show_scores: bool = False, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    top = matches[:TOP5]
    n = len(top)
    reply_range = "1" if n == 1 else f"1-{n}"
    intro = _html.escape(ui["render_top5_intro"].format(range=reply_range))
    rows = ""
    for i, m in enumerate(top, start=1):
        name = _html.escape(m["product_name"])
        price = _html.escape(fmt_price(m.get("price")))
        score_str = f' <span class="select-score">[{int(m.get("score") or 0)}%]</span>' if show_scores else ""
        rows += f'<div class="select-row" data-send="{i}"><span class="select-num">{i}</span><span class="select-text">{name} {price}{score_str}</span></div>'
    return f'<div class="select-intro">{intro}</div><div class="select-list">{rows}</div>'

def render_customer_picker(matches: List[dict], intro: str = "") -> str:
    top = (matches or [])[:3]
    n = len(top)

    # Single match — show name card + Yes/No buttons
    if n == 1 and not intro:
        c = top[0]
        full = _html.escape(f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip())
        phone_hint = _html.escape(format_phone_display(c.get("phone") or ""))
        email_hint = _html.escape((c.get("email") or "").strip())
        hint_parts = [p for p in (phone_hint, email_hint) if p]
        detail = f'<span class="select-detail">{" • ".join(hint_parts)}</span>' if hint_parts else ""
        yn = _qr([
            {"cls": "yes", "send": "1",  "label": "Yes"},
            {"cls": "no",  "send": "no", "label": "No"},
        ])
        return (
            f'<div class="select-intro">Is this who you mean?</div>'
            f'<div class="select-list">'
            f'<div class="select-row" data-send="1"><span class="select-num">1</span>'
            f'<div class="select-text"><span>{full}</span>{detail}</div></div>'
            f'</div>{yn}'
        )

    if not intro:
        intro = f"I found multiple matches — reply with 1-{n}:"
    rows = ""
    for i, c in enumerate(top, start=1):
        full = _html.escape(f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip())
        phone_hint = _html.escape(format_phone_display(c.get("phone") or ""))
        email_hint = _html.escape((c.get("email") or "").strip())
        hint_parts = [p for p in (phone_hint, email_hint) if p]
        detail = f' <span class="select-detail">• {" • ".join(hint_parts)}</span>' if hint_parts else ""
        rows += f'<div class="select-row" data-send="{i}"><span class="select-num">{i}</span><span class="select-text">{full}{detail}</span></div>'
    return f'<div class="select-intro">{_html.escape(intro)}</div><div class="select-list">{rows}</div>'

def render_customer_delete_picker(matches: List[dict], recent_orders_map: dict[int, list[dict]]) -> str:
    top = (matches or [])[:3]
    n = len(top)
    intro = f"I found multiple matches. Reply with 1{f'-{n}' if n > 1 else ''} to choose which customer to delete:"
    rows = ""

    for i, c in enumerate(top, start=1):
        cid = int(c["id"])
        full = _html.escape(f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip())

        email = _html.escape((c.get("email") or "").strip() or "(none)")
        phone = _html.escape(format_phone_display(c.get("phone") or "") or "(none)")

        street = (c.get("street") or "").strip()
        city = (c.get("city") or "").strip()
        state = (c.get("state") or "").strip()
        postal = (c.get("postal_code") or "").strip()

        addr_parts = []
        if street:
            addr_parts.append(street)
        if city:
            addr_parts.append(city)
        line2 = " ".join([p for p in [state, postal] if p]).strip()
        if line2:
            addr_parts.append(line2)

        address = _html.escape(", ".join(addr_parts) if addr_parts else "(none)")
        birthday = _html.escape(birthday_display(c.get("birthday") or "") or "(none)")

        recent_orders = recent_orders_map.get(cid) or []
        order_lines = ""
        if recent_orders:
            for o in recent_orders[:2]:
                raw_dt = o.get("order_date_display") or o.get("order_date") or ""
                if hasattr(raw_dt, "strftime"):
                    dt = raw_dt.strftime("%Y-%m-%d")
                else:
                    dt = str(raw_dt)[:10] if raw_dt else ""
                total = o.get("total")
                total_txt = f"${float(total):.2f}" if isinstance(total, (int, float)) else ""
                order_lines += f'<span class="delete-order">{_html.escape(dt + (" • " + total_txt if total_txt else ""))}</span>'
            orders_html = f'<span class="delete-label">Orders:</span> {order_lines}'
        else:
            orders_html = '<span class="delete-label">Orders:</span> none'

        rows += (
            f'<div class="select-row delete-row" data-send="{i}">'
            f'<span class="select-num">{i}</span>'
            f'<div class="select-text">'
            f'<span class="delete-name">{full}</span>'
            f'<span class="delete-detail">{email} • {phone}</span>'
            f'<span class="delete-detail">{address}</span>'
            f'<span class="delete-detail">Birthday: {birthday}</span>'
            f'<span class="delete-detail">{orders_html}</span>'
            f'</div></div>'
        )

    return f'<div class="select-intro">{_html.escape(intro)}</div><div class="select-list">{rows}</div>'

def _looks_like_new_order_entry(text: str) -> bool:
                t = (text or "").strip().lower()

                has_order_verb = any(x in t for x in ("order ", "ordered ", "wants ", "want ", "needs ", "need "))
                has_item_connector = any(x in t for x in (" and ", ","))
                has_quantity = bool(re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", t))
                has_product_hint = any(
                    x in t for x in (
                        "mask", "set", "cleanser", "cream", "lipstick", "foundation",
                        "charcoal", "poppy", "repair", "cc cream", "satin hands"
                    )
                )

                score = sum([
                    has_order_verb,
                    has_item_connector,
                    has_quantity,
                    has_product_hint,
                ])

                return score >= 2

def looks_like_command(msg: str) -> bool:
    s = (msg or "").strip().lower()
    if not s:
        return False

    # direct command starts
    command_starts = (
        "show ", "lookup ", "info ", "information ",
        "what is", "what's", "whats",
        "top ", "leaderboard", "spent", "last ", "recent ", "history",
        "new customer", "add customer", "create customer", "create ",
        "new order", "order for", "add order",
        "delete ", "remove ",
    )

    if s.startswith(command_starts):
        return True

    # detect possessive info requests like: "Jane's info"
    if re.search(r"\b\w+'\s*s?\s*(info|email|phone|address|birthday)\b", s):
        return True

    # detect patterns like "Jane info"
    if re.search(r"\b\w+\s+(info|email|phone|address|birthday)\b", s):
        return True

    # detect "top X customers"
    if re.search(r"\btop\s*\d+\s*customers?\b", s):
        return True

    return False

def split_edit_parts(message: str) -> List[str]:
    """
    Splits a user edit message into chunks.
    IMPORTANT:
    - Do NOT split on commas (addresses)
    - Do NOT split on 'and' (addresses like 'Fish and Game Rd')
    """
    s = (message or "").strip()
    if not s:
        return []

    # Split only on semicolons OR newlines
    parts = re.split(r"\s*;\s*|\n+", s)

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
            b_raw = re.sub(r"^(birthday|bday|dob)\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            b = normalize_birthday(b_raw)
            if b:
                c["Birthday"] = b
                notes.append("Birthday updated")
            continue

        # tags:
        if low.startswith("tag"):
            raw = re.sub(r"^tags?\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            tags = ", ".join(t.strip() for t in raw.split(",") if t.strip())
            if tags:
                c["Tags"] = tags
                notes.append("Tags updated")
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

        # ✅ Address guess (must be BEFORE zip guess)
        parsed = parse_address_line(txt)
        if parsed:
            c.update(parsed)
            notes.append("Address updated")
            continue

        # Phone guess
        ph = _extract_phone_candidate(txt)
        if ph:
            c["Phone"] = ph
            notes.append("Phone updated")
            continue



        # Zip guess
        z = _extract_zip(txt)
        if z:
            c["Postal Code"] = z
            notes.append("Postal code updated")
            continue

        # Fallback: if they typed something else, ignore but keep a note
        notes.append(f"Couldn't apply: “{raw}”")

    # Clean punctuation that causes "Street," to get saved to JSON
    for k in ("Street", "City", "State"):
        if k in c and isinstance(c[k], str):
            c[k] = c[k].strip().rstrip(",")

    # Re-normalize (important!)
    c["Phone"] = normalize_phone(c.get("Phone", ""))
    c["Birthday"] = normalize_birthday(c.get("Birthday", ""))
    c["State"] = normalize_state(c.get("State", ""))
    c["City"] = normalize_city(c.get("City", ""))

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

def _looks_like_inventory_add(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return "inventory" in s and (s.startswith("add ") or s.startswith("remove ") or s.startswith("set "))

def _normalize_inventory_command_text(msg: str) -> str:
    s = (msg or "").strip().lower()

    # Remove common inventory phrases anywhere in the message
    replacements = [
        "to my inventory",
        "from my inventory",
        "my inventory",
        "to inventory",
        "from inventory",
        "inventory",
    ]

    for phrase in replacements:
        s = s.replace(phrase, " ")

    # Clean extra spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _looks_like_inventory_show(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return s in (
        "show my inventory",
        "show inventory",
        "my inventory",
        "inventory",
    )

def _inventory_help_text() -> str:
    return (
        "Here are a few inventory things you can say:\n"
        "\n"
        "📦 View & update quantities:\n"
        "• show my inventory\n"
        "• how many charcoal masks do I have\n"
        "• add 3 satin hands to inventory\n"
        "• remove 1 charcoal mask from inventory\n"
        "• set satin hands inventory to 5\n"
        "\n"
        "🎯 Set a desired quantity (your 'always keep on hand' level):\n"
        "• set charcoal mask par to 3\n"
        "\n"
        "📋 Check what to reorder:\n"
        "• what am I low on\n"
        "• what should I order\n"
        "\n"
        "🖨️ Print your inventory:\n"
        "• print my inventory"
    )

def _looks_like_inventory_count(msg: str) -> bool:
    s = (msg or "").strip().lower()
    if "how many" in s and " do i have" in s:
        return True
    if s.endswith(" in inventory"):
        return True
    if "how many" in s and "inventory" in s:
        return True
    return False


def _parse_inventory_write(msg: str) -> tuple[str | None, int | None, str]:
    """
    Returns (action, qty, product_text)
    action = add | remove | set | None

    Requires the original message to contain 'inventory' somewhere.
    After inventory words are removed, supports:
    - add <qty> <product>
    - remove <qty> <product>
    - set <product> to <qty>
    """
    raw = (msg or "").strip()
    if "inventory" not in raw.lower():
        return (None, None, "")

    s = _normalize_inventory_command_text(raw)

    m = re.match(r"^\s*add\s+(\w+)\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return ("add", qty, m.group(2).strip())

    m = re.match(r"^\s*remove\s+(\w+)\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return ("remove", qty, m.group(2).strip())

    m = re.match(r"^\s*set\s+(.+?)\s+to\s+(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            return ("set", qty, m.group(1).strip())

    return (None, None, "")

def _looks_like_bare_inventory_write(msg: str) -> bool:
    s = (msg or "").strip().lower()

    # Ignore if they already clearly said inventory
    if "inventory" in s:
        return False

    # Ignore threshold-setting phrases — those are handled separately
    if "on hand" in s or bool(re.search(r"\bpar\b", s)) or "minimum" in s:
        return False

    m = re.match(r"^\s*(add|remove)\s+(\w+)\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        return qty is not None

    m = re.match(r"^\s*set\s+(.+?)\s+to\s+(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        return qty is not None

    return False

def _parse_inventory_lookup_text(msg: str) -> str:
    s = (msg or "").strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+do\s+i\s+have\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*(.+?)\s+in\s+inventory\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+(?:in\s+)?inventory\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""

def _format_inventory_list(rows: List[dict], catalog: List[dict]) -> str:
    if not rows:
        return "Your inventory is empty."

    by_sku = {str(c.get("sku") or "").strip(): c for c in catalog}
    lines = ["Here is your current inventory:"]

    shown_any = False

    for row in rows:
        sku = str(row.get("sku") or "").strip()
        qty = int(row.get("qty_on_hand") or 0)

        # Hide zero or negative inventory items
        if qty <= 0:
            continue

        shown_any = True

        cat = by_sku.get(sku) or {}
        name = (cat.get("product_name") or sku or "Unknown product").strip()
        retail = cat.get("price")
        retail_txt = fmt_price(retail)

        if retail_txt:
            lines.append(f"• {name} {retail_txt} — {qty} on hand")
        else:
            lines.append(f"• {name} — {qty} on hand")

    if not shown_any:
        return "We have not yet added any items to your inventory."

    return "\n".join(lines)

def _normalize_match_text(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _find_exact_catalog_match(catalog: List[dict], product_text: str) -> Optional[dict]:
    target = _normalize_match_text(product_text)
    if not target:
        return None

    for c in catalog:
        name_norm = _normalize_match_text(c.get("product_name") or "")
        if target == name_norm:
            return c

        raw_terms = (c.get("search_terms") or "").strip()
        if raw_terms:
            for term in raw_terms.split("|"):
                if target == _normalize_match_text(term):
                    return c

    return None

def _format_inventory_item(row: dict | None, catalog_item: dict | None, requested_text: str) -> str:
    if not row:
        return f"You have 0 {requested_text} in inventory."

    qty = int(row.get("qty_on_hand") or 0)
    name = (
        (catalog_item or {}).get("product_name")
        or requested_text
    )
    return f"You have {qty} {name} in inventory."


def _looks_like_inventory_print(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return any(phrase in s for phrase in (
        "print my inventory",
        "print inventory",
        "inventory pdf",
        "download inventory",
        "export inventory",
        "inventory report",
    ))


def _looks_like_low_stock_query(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return any(phrase in s for phrase in (
        "what am i low on",
        "what's low",
        "whats low",
        "what is low",
        "low on",
        "running low",
        "what should i order",
        "what do i need to order",
        "what do i need to reorder",
        "what should i reorder",
        "show low",
        "low inventory",
        "low stock",
    ))


def _format_low_stock_list(rows: list[dict], catalog: list[dict]) -> str:
    if not rows:
        return "You're all stocked up — nothing is below your desired on-hand levels."

    by_sku = {str(c.get("sku") or "").strip(): c for c in catalog}
    lines = ["Here's what you need to reorder:"]

    for row in rows:
        sku = str(row.get("sku") or "").strip()
        qty = int(row.get("qty_on_hand") or 0)
        threshold = int(row.get("low_stock_threshold") or 0)
        needed = threshold - qty

        cat = by_sku.get(sku) or {}
        name = (cat.get("product_name") or sku or "Unknown product").strip()

        lines.append(f"• {name} — you have {qty}, want {threshold} (need {needed} more)")

    return "\n".join(lines)


def _looks_like_inventory_threshold(msg: str) -> bool:
    s = (msg or "").strip().lower()
    has_qty = bool(re.search(r"\b\d+\b|\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", s))
    if not has_qty:
        return False
    return (
        "on hand" in s
        or bool(re.search(r"\bpar\b", s))
        or "minimum" in s
        or bool(re.search(r"\bmin\s+\d", s))
    )


def _parse_inventory_threshold(msg: str) -> tuple[int | None, str]:
    """
    Returns (qty, product_text) or (None, "")
    Trigger words: "on hand", "par", "minimum" / "min"

    on hand:
    - keep 3 charcoal mask on hand
    - 3 charcoal mask on hand
    - I want (to) (always) have 3 charcoal mask on hand
    - set charcoal mask to 3 on hand

    par:
    - charcoal mask par 3
    - par 3 charcoal mask
    - set charcoal mask (to) par 3

    minimum / min:
    - minimum 3 charcoal mask
    - charcoal mask minimum 3
    - set minimum charcoal mask to 3
    """
    s = (msg or "").strip()

    # ---- on hand ----
    # "keep / want (to) (always) have <qty> <product> on hand"
    m = re.match(
        r"^\s*(?:keep|(?:i\s+)?want\s+(?:to\s+)?(?:always\s+)?have)\s+(\w+)\s+(.+?)\s+on\s+hand\s*$",
        s, re.IGNORECASE,
    )
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return qty, m.group(2).strip()

    # "set <product> to <qty> on hand"
    m = re.match(r"^\s*set\s+(.+?)\s+to\s+(\w+)\s+on\s+hand\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            return qty, m.group(1).strip()

    # "<qty> <product> on hand"
    m = re.match(r"^\s*(\w+)\s+(.+?)\s+on\s+hand\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return qty, m.group(2).strip()

    # ---- par ----
    # "set <product> (inventory) (to) par (to) <qty>"
    m = re.match(r"^\s*set\s+(.+?)\s+(?:inventory\s+)?(?:to\s+)?par\s+(?:to\s+)?(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            product = re.sub(r"\binventory\b", "", m.group(1), flags=re.IGNORECASE).strip()
            return qty, product

    # "<product> par <qty>"
    m = re.match(r"^\s*(.+?)\s+par\s+(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            return qty, m.group(1).strip()

    # "par <qty> <product>"
    m = re.match(r"^\s*par\s+(\w+)\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return qty, m.group(2).strip()

    # ---- minimum / min ----
    # "set minimum <product> to <qty>"
    m = re.match(r"^\s*set\s+(?:minimum|min)\s+(.+?)\s+to\s+(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            return qty, m.group(1).strip()

    # "minimum <qty> <product>"
    m = re.match(r"^\s*(?:minimum|min)\s+(\w+)\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(1))
        if qty is not None:
            return qty, m.group(2).strip()

    # "<product> minimum <qty>"
    m = re.match(r"^\s*(.+?)\s+(?:minimum|min)\s+(\w+)\s*$", s, re.IGNORECASE)
    if m:
        qty = _parse_small_number(m.group(2))
        if qty is not None:
            return qty, m.group(1).strip()

    return None, ""


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

        import os as _os
        _admin_emails = {e.strip().lower() for e in _os.environ.get("MK_ADMIN_EMAILS", "").split(",") if e.strip()}
        _consultant_email = (consultant.get("email") or "").strip().lower() if consultant else ""
        show_scores = _consultant_email in _admin_emails

        ui = UI_ES if language == "es" else UI_EN

        if language not in self._catalog_cache:
            catalog_path = get_catalog_path_for_language(language)
            self._catalog_cache[language] = load_catalog(catalog_path)

        catalog = self._catalog_cache[language]

        last_customer = (state.get("last_ref_customer_name") or "").strip() or None
        pending = state.get("pending")
        msg = (message or "").strip()

        # Replace standalone 8-digit SKU numbers with product names before any parsing
        import re as _re
        _sku_map = {str(item["sku"]).strip(): item["product_name"] for item in catalog if item.get("sku")}
        msg = _re.sub(r'\b(\d{8})\b', lambda m: _sku_map.get(m.group(1), m.group(1)), msg)

        intent_result = parse_intent(msg, state)
        print("[INTENT]", intent_result.intent, intent_result.confidence, intent_result.raw_text)

        # Intent override: some "recent_orders" phrasings are actually NEW order entry
        if intent_result.intent == "recent_orders" and _looks_like_new_order_entry(msg):
            intent_result.intent = "new_order"

        def _resolve_pronoun_guess(guess: str, state: dict) -> str:
            g = (guess or "").strip().lower()

            if g in ("she", "her", "he", "him", "they", "them"):
                name = (state.get("last_ref_customer_name") or "").strip()
                if name:
                    return name

            return guess

        if not msg:
            return ChatReply(ui["empty_prompt"])
        
        lowered = msg.lower()
        
        # -------------------------
        # Bare inventory-style write guardrail
        # -------------------------
        if _looks_like_bare_inventory_write(msg):
            return ChatReply(
                "That looks like an inventory update.\n"
                "Try again using the word 'inventory':\n"
                "• add 3 satin hands to inventory\n"
                "• remove 1 satin hands from inventory\n"
                "• set satin hands inventory to 5"
            )
        
        # -------------------------
        # Inventory: print / PDF report
        # -------------------------
        if _looks_like_inventory_print(msg):
            import os
            base_url = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
            link = f"{base_url}/inventory/print" if base_url else "/inventory/print"
            return ChatReply(ui["inventory_report"].format(link=link))

        # -------------------------
        # Inventory: quantity count query (early — before intent routing so
        # "how many X do I have" isn't misclassified as new_order)
        # -------------------------
        if _looks_like_inventory_count(msg):
            product_text = _parse_inventory_lookup_text(msg)
            if product_text:
                picked, matches = auto_pick_match(catalog, product_text)
                chosen = picked or (matches[0] if matches else None)
                if not chosen:
                    return ChatReply(ui["no_catalog_match"])
                sku = (chosen.get("sku") or "").strip()
                with tx() as (conn, cur):
                    row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                return ChatReply(_format_inventory_item(row, chosen, product_text))

        # -------------------------
        # Inventory: show full list (early — same reason)
        # -------------------------
        if _looks_like_inventory_show(msg):
            with tx() as (conn, cur):
                rows = list_inventory(cur, consultant_id=consultant_id)
            return ChatReply(_format_inventory_list(rows, catalog))

        # -------------------------
        # Inventory: low stock / what should I order
        # -------------------------
        if _looks_like_low_stock_query(msg):
            from inventory_store import list_low_stock, has_any_thresholds
            with tx() as (conn, cur):
                if not has_any_thresholds(cur, consultant_id=consultant_id):
                    return ChatReply(
                        "You haven't set any desired on-hand levels yet.\n"
                        "Try: \"keep 3 charcoal mask on hand\" and I'll track that for you."
                    )
                rows = list_low_stock(cur, consultant_id=consultant_id)
            return ChatReply(_format_low_stock_list(rows, catalog))

        # -------------------------
        # Inventory: set desired on-hand threshold
        # -------------------------
        if _looks_like_inventory_threshold(msg):
            qty, product_text = _parse_inventory_threshold(msg)
            if qty is not None and product_text:
                exact = _find_exact_catalog_match(catalog, product_text)
                if exact:
                    chosen = exact
                else:
                    matches = best_matches(catalog, product_text, limit=MATCH_LIMIT)
                    if not matches:
                        return ChatReply(ui["no_catalog_match"])
                    top = matches[0]
                    if int(top.get("score") or 0) >= 100:
                        chosen = top
                    else:
                        state["pending"] = {
                            "kind": "inventory_threshold_confirm_top",
                            "qty": int(qty),
                            "product_text": product_text,
                            "top": top,
                            "matches": matches[:MATCH_LIMIT],
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(propose_top(top, current_qty=1, ui=ui))

                sku = (chosen.get("sku") or "").strip()
                product_name = (chosen.get("product_name") or "").strip()
                with tx() as (conn, cur):
                    upsert_inventory_quantity(
                        cur,
                        consultant_id=consultant_id,
                        sku=sku,
                        low_stock_threshold=int(qty),
                    )
                return ChatReply(ui["low_stock_set"].format(product=product_name, qty=qty))

        # -------------------------
        # Inventory commands
        # -------------------------
        if "inventory" in lowered:
            action, qty, product_text = _parse_inventory_write(msg)

            if action and qty is not None and product_text:
                exact = _find_exact_catalog_match(catalog, product_text)
                if exact:
                    chosen = exact
                    matches = [exact]
                else:
                    matches = best_matches(catalog, product_text, limit=MATCH_LIMIT)
                    if not matches:
                        return ChatReply(ui["no_catalog_match"])

                    top = matches[0]
                    if int(top.get("score") or 0) >= 100:
                        chosen = top
                    else:
                        state["pending"] = {
                            "kind": "inventory_confirm_top",
                            "action": action,
                            "qty": int(qty),
                            "product_text": product_text,
                            "top": top,
                            "matches": matches[:MATCH_LIMIT],
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(propose_top(top, current_qty=1, ui=ui))

                sku = (chosen.get("sku") or "").strip()
                product_name = (chosen.get("product_name") or "").strip()

                with tx() as (conn, cur):
                    if action == "add":
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            qty_delta=int(qty),
                        )

                    elif action == "remove":
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            qty_delta=-int(qty),
                        )

                    else:  # set
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            set_qty=int(qty),
                        )

                    row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                    current_qty = int((row or {}).get("qty_on_hand") or 0)

                    if action == "add":
                        reply = (
                            f"Added {qty} of {product_name} to your inventory. "
                            f"You currently have {current_qty} on hand."
                        )
                    elif action == "remove":
                        reply = (
                            f"Removed {qty} of {product_name} from your inventory. "
                            f"You currently have {current_qty} on hand."
                        )
                    else:
                        reply = (
                            f"Set {product_name} inventory to {qty}. "
                            f"You currently have {current_qty} on hand."
                        )

                return ChatReply(reply)

            if _looks_like_inventory_show(msg):
                with tx() as (conn, cur):
                    rows = list_inventory(cur, consultant_id=consultant_id)
                return ChatReply(_format_inventory_list(rows, catalog))

            if _looks_like_inventory_count(msg):
                product_text = _parse_inventory_lookup_text(msg)
                if product_text:
                    picked, matches = auto_pick_match(catalog, product_text)
                    chosen = picked or (matches[0] if matches else None)

                    if not chosen:
                        return ChatReply(ui["no_catalog_match"])

                    sku = (chosen.get("sku") or "").strip()

                    with tx() as (conn, cur):
                        row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)

                    return ChatReply(_format_inventory_item(row, chosen, product_text))

            return ChatReply(_inventory_help_text())

        import re
        from crm_store import find_customers_by_name, get_customer_by_id, count_orders_for_customer, delete_customer_local

    

        def _looks_like_full_customer_entry(text: str) -> bool:
            t = (text or "").strip()

            has_zip = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", t))
            has_phone = bool(re.search(r"(?:\+?1[\s\-\.]?)?(?:\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4})", t))
            has_birthday_word = any(x in t.lower() for x in ("birthday", "bday", "dob"))
            has_month_name = bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", t, re.IGNORECASE))
            has_address_word = any(x in t.lower() for x in ("address", "street", "st ", "road", "rd ", "avenue", "ave ", "drive", "dr ", "lane", "ln ", "court", "ct ", "circle", "cir ", "way", "blvd", "boulevard", "unit", "apt", "apartment", "lot"))

            score = sum([
                has_zip,
                has_phone,
                has_birthday_word or has_month_name,
                has_address_word,
            ])

            # if it looks like a bundle of customer fields, treat it as a customer entry
            return score >= 2

        

        # -------------------------
        # CRM: delete customer (local only)
        # -------------------------
        if not pending:
            m = re.match(r"^\s*delete\s+(customer\s+)?(.+?)\s*$", msg, re.IGNORECASE)
            if m:
                target = (m.group(2) or "").strip()

                # delete by id: "delete customer id 7" or "delete id 7"
                m_id = re.search(r"\b(id)\s+(\d+)\b", target, re.IGNORECASE)
                with tx() as (conn, cur):
                    if m_id:
                        cid = int(m_id.group(2))
                        c = get_customer_by_id(cur, consultant_id=consultant_id, customer_id=cid)
                        if not c:
                            return ChatReply(ui["no_customer_id"].format(cid=cid))
                        order_count = count_orders_for_customer(cur, customer_id=cid)

                        state["pending"] = {
                            "kind": "delete_customer_confirm",
                            "customer_id": cid,
                            "customer_name": f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip(),
                            "order_count": order_count,
                        }
                        save_session_state(state, session_id=sid)

                        if order_count > 0:
                            return ChatReply(
                                f"This will delete {state['pending']['customer_name']} from MyPinkAssistant and also remove "
                                f"{order_count} local order(s). Type DELETE to confirm, or `cancel`."
                            )
                        return ChatReply(
                            f"This will delete {state['pending']['customer_name']} from MyPinkAssistant. "
                            f"Type DELETE to confirm, or `cancel`."
                        )

                    # delete by name
                    matches = find_customers_by_name(
                        cur,
                        consultant_id=consultant_id,
                        name=target,
                        limit=10,
                        include_removed=True,
                    )

                if len(matches) == 0:
                    return ChatReply(ui["no_customer_found"].format(name=target))

                if len(matches) == 1:
                    c = matches[0]
                    cid = int(c["id"])
                    with tx() as (conn, cur):
                        order_count = count_orders_for_customer(cur, customer_id=cid)

                    state["pending"] = {
                        "kind": "delete_customer_confirm",
                        "customer_id": cid,
                        "customer_name": f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip(),
                        "order_count": order_count,
                    }
                    save_session_state(state, session_id=sid)

                    if order_count > 0:
                        return ChatReply(
                            f"This will delete {state['pending']['customer_name']} from MyPinkAssistant and also remove "
                            f"{order_count} local order(s). Type DELETE to confirm, or `cancel`."
                        )
                    return ChatReply(
                        f"This will delete {state['pending']['customer_name']} from MyPinkAssistant. "
                        f"Type DELETE to confirm, or `cancel`."
                    )

                # Multiple matches -> richer delete picker

                top = matches[:3]
                recent_orders_map = {}

                with tx() as (conn, cur):
                    for c in top:
                        cid = int(c["id"])
                        recent_orders_map[cid] = get_recent_orders_for_customer(cur, customer_id=cid, limit=2)

                state["pending"] = {"kind": "pick_customer", "candidates": top, "action": "delete"}
                save_session_state(state, session_id=sid)

                return ChatReply(render_customer_delete_picker(top, recent_orders_map))

        ##
        # -------------------------
        # CRM quick lookup: leaderboard / top customers (no LLM call)
        # -------------------------
        if not pending:
            import re

            leaderboard_triggers = (
                "leaderboard",
                "spent the most", "spend the most",
                "pcp list", "pcp mailer",
                "top customers", "top customer"
            )

            looks_like_top_n = bool(re.search(r"\btop\s*\d+\s*customers?\b", lowered))
            looks_like_top_customers = ("top" in lowered and "customer" in lowered)

            #testing api call on leaderboard
            #if any(t in lowered for t in leaderboard_triggers) or looks_like_top_n or looks_like_top_customers:
            if intent_result.intent == "leaderboard":
                from crm_store import (
                    parse_top_n_from_text,
                    parse_time_filter_from_text,
                    get_top_customers,
                    format_leaderboard,
                )

                n = parse_top_n_from_text(msg, default=5, soft_cap=10, hard_cap=50)
                start_date, end_date = parse_time_filter_from_text(msg)

                # Title label (simple)
                period = "lifetime"
                if "this year" in lowered:
                    period = "this year"
                elif "this month" in lowered:
                    period = "this month"
                elif "this quarter" in lowered:
                    period = "this quarter"
                elif "last quarter" in lowered:
                    period = "last quarter"
                else:
                    import re
                    m = re.search(r"(last|past)\s+(\d+)\s+day", lowered)
                    if m:
                        period = f"{m.group(1)} {m.group(2)} days"

                title = f"Top {n} customers ({period})"
                if "pcp" in lowered:
                    title = f"PCP list starting point — Top {n} customers ({period})"

                with tx() as (conn, cur):
                    rows = get_top_customers(
                        cur,
                        consultant_id=consultant_id,
                        limit=n,
                        start_date=start_date,
                        end_date=end_date,
                    )

                return ChatReply(format_leaderboard(rows, title))
        
        # -------------------------
        # Follow-up trigger (2+2+2)
        # -------------------------
        if not pending:
            _followup_triggers = ("follow up", "followup", "follow-up", "any follow", "follow ups", "followups")
            _more_triggers = ("any more", "more follow", "next follow")
            _is_followup = any(t in lowered for t in _followup_triggers)
            _is_more = any(t in lowered for t in _more_triggers)
            if _is_followup or _is_more:
                from followup_store import get_pending_followups, get_pending_birthday_followups, render_followup_cards
                from db import tx
                _offset = 0
                if _is_more:
                    _offset = state.get("followup_offset") or 0
                from auth_core import get_consultant_full as _gcf
                _consultant_first = (_gcf(consultant_id) or {}).get("first_name") or ""
                _consultant_first = _consultant_first.strip()
                with tx() as (conn, cur):
                    _order_followups = get_pending_followups(cur, consultant_id=consultant_id, offset=_offset, limit=5)
                    _bday_followups = get_pending_birthday_followups(cur, consultant_id=consultant_id) if _offset == 0 else []
                _followups = _order_followups + _bday_followups
                state["followup_offset"] = _offset + len(_order_followups)
                save_session_state(state, session_id=sid)
                return ChatReply(render_followup_cards(_followups, _consultant_first))

        # -------------------------
        # Customer search by product
        # -------------------------
        if not pending and not _looks_like_full_customer_entry(msg) and not re.match(r'^\s*tags?\s*:', msg, re.IGNORECASE):
            import re as _re2
            _product_term = None

            # Pattern 1: "[product] customers" — e.g. "repair customers", "show my matte foundation customers"
            _m1 = _re2.search(r"(?:show\s+)?(?:my\s+)?(.+?)\s+customers\b", lowered)
            # Pattern 2: "customers who [use/ordered/buy/have] [product]" — e.g. "customers who use repair"
            _m2 = _re2.search(r"\bcustomers\s+who\s+(?:use|ordered|buy|have|bought|order)\s+(.+)", lowered)
            # Pattern 3: "who bought/ordered/uses [product]"
            _m3 = _re2.search(r"\bwho\s+(?:bought|ordered|uses|has|orders|buys|got)\s+(.+)", lowered)

            _prefix_filler = {"who", "are", "my", "show", "list", "which", "what", "any",
                              "the", "a", "all", "give", "me", "find", "get", "have", "do",
                              "i", "is", "of", "new", "other", "please"}

            if _m2:
                _product_term = _m2.group(1).strip()
            elif _m3:
                _product_term = _m3.group(1).strip()
            elif _m1:
                _candidate = _m1.group(1).strip()
                # Strip leading filler words (e.g. "who are my" from "who are my repair customers")
                _candidate_words = [w for w in _candidate.split() if w not in _prefix_filler]
                _candidate = " ".join(_candidate_words).strip()
                if _candidate:
                    _product_term = _candidate

            if _product_term:
                from crm_store import find_customers_by_product, format_customers_by_product
                from db import tx
                _filler = {"on", "the", "a", "an", "use", "using", "with", "for", "in", "of"}
                terms = [w for w in _product_term.lower().split() if len(w) > 1 and w not in _filler]
                if terms:
                    with tx() as (conn, cur):
                        results = find_customers_by_product(cur, consultant_id=consultant_id, terms=terms)
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(format_customers_by_product(results, _product_term))

        # -------------------------
        # CRM quick lookup: recent orders lookup (no LLM call)
        # -------------------------
        if not pending:
            if intent_result.intent == "recent_orders":
                    import re
                    from crm_store import format_recent_orders

                    m_clean = re.sub(r"[^\w\s']", " ", msg).strip()
                    stop_words = {
                        "last", "recent", "show", "lookup", "order", "orders", "history",
                        "for", "on", "info", "information", "what", "is", "whats", "what's",
                        "me", "please", "customer","was", "did", "do", "does",
                        "order", "orders", "ordered",
                        "last", "recent", "latest",
                        "buy", "bought", "purchase", "purchased"
                    }

                    tokens = []
                    for raw in m_clean.split():
                        t = raw.strip()
                        if t.lower().endswith("'s"):
                            t = t[:-2]

                        if not t:
                            continue

                        # ✅ ignore numbers like "3" in "last 3 orders"
                        if t.isdigit():
                            continue

                        # ✅ ignore common time/count words
                        if t.lower() in ("day", "days", "week", "weeks", "month", "months", "year", "years"):
                            continue

                        if t.lower() not in stop_words:
                            tokens.append(t)

                    guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
                    guess = _resolve_pronoun_guess(guess, state) or (state.get("last_ref_customer_name") or "").strip() or msg

                    import re
                    limit = 3
                    m = re.search(r"\blast\s+(\d+)\s+orders?\b", lowered)
                    if m:
                        limit = max(1, min(10, int(m.group(1))))
                    elif "last order" in lowered or "latest order" in lowered:
                        limit = 1

                    with tx() as (conn, cur):
                        matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)

                        if len(matches) == 0:
                            return ChatReply(ui["no_customer_found_yet"].format(name=guess))

                        if len(matches) > 1:
                            top = matches[:3]

                            state["pending"] = {
                                "kind": "pick_customer",
                                "candidates": top,
                                "action": "orders",
                                "orders_limit": limit
                            }
                            save_session_state(state, session_id=sid)

                            return ChatReply(render_customer_picker(top))

                        c = matches[0]
                        customer_id = int(c["id"])
                        customer_name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()

                        orders = get_recent_orders_for_customer(cur, customer_id=customer_id, limit=limit)

                    return ChatReply(format_recent_orders(customer_name, orders))
        
        # -------------------------
        # CRM quick lookup: customer spending (no LLM call)
        # -------------------------
        if not pending:
            if intent_result.intent == "customer_spend":
                import re
                from crm_store import get_customer_spending, parse_time_filter_from_text

                # Extract name-ish tokens (similar approach to other blocks)
                m_clean = re.sub(r"[^\w\s']", " ", msg).strip()
                stop_words = {
                    "how", "much", "did", "has", "have", "spent", "spend", "total", "in", "for", "on",
                    "this", "year", "month", "last", "days", "customer", "orders", "order", "history",
                    "what", "is", "whats", "what's", "me", "please"
                }

                tokens = []
                for raw in m_clean.split():
                    t = raw.strip()
                    if t.lower().endswith("'s"):
                        t = t[:-2]

                    if not t:
                        continue

                    # ✅ ignore numbers like "7", "30", etc.
                    if t.isdigit():
                        continue

                    # ✅ ignore common time unit words that might slip through
                    if t.lower() in ("day", "days", "week", "weeks", "month", "months", "year", "years"):
                        continue

                    if t.lower() not in stop_words:
                        tokens.append(t)

                guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else msg)
                guess = _resolve_pronoun_guess(guess, state)

                start_date, end_date = parse_time_filter_from_text(msg)

                with tx() as (conn, cur):
                    matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)

                    if len(matches) == 0:
                        return ChatReply(ui["no_customer_found_yet"].format(name=guess))

                    if len(matches) > 1:
                        top = matches[:3]

                        # friendly period label for later response
                        period_label = "lifetime"
                        if "this year" in lowered:
                            period_label = "this year"
                        elif "this month" in lowered:
                            period_label = "this month"
                        else:
                            m = re.search(r"(last|past)\s+(\d+)\s+day", lowered)
                            if m:
                                period_label = f"{m.group(1)} {m.group(2)} days"

                        state["pending"] = {
                            "kind": "pick_customer",
                            "candidates": top,
                            "action": "spend",
                            "start_date": start_date,
                            "end_date": end_date,
                            "period_label": period_label,
                        }
                        save_session_state(state, session_id=sid)

                        return ChatReply(render_customer_picker(top))

                    c = matches[0]
                    customer_id = int(c["id"])
                    customer_name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()

                    total_spent = get_customer_spending(
                        cur,
                        consultant_id=consultant_id,
                        customer_id=customer_id,
                        start_date=start_date,
                        end_date=end_date,
                    )

                # Friendly label for the time period
                import re

                period = "lifetime"
                if "this year" in lowered:
                    period = "this year"
                elif "this month" in lowered:
                    period = "this month"
                else:
                    m = re.search(r"(last|past)\s+(\d+)\s+day", lowered)
                    if m:
                        period = f"{m.group(1)} {m.group(2)} days"

                return ChatReply(ui["customer_spent"].format(name=customer_name, total=f"{total_spent:,.2f}", period=period))

        # Cancel command (intent-driven)
        if intent_result.intent == "cancel" and not (
            pending and pending.get("kind") == "delete_customer_confirm"
        ):
            state["pending"] = None
            state["last_ref_customer_id"] = None
            state["last_ref_customer_name"] = None
            state["last_customer"] = None
            save_session_state(state, session_id=sid)
            return ChatReply(ui["canceled"])
        
        # -------------------------
        # CRM quick lookup: customer info lookup (no LLM call)
        # -------------------------
        
        if not pending:
            if intent_result.intent == "customer_info":
                import re

                # Guard: if this looks like pasted full customer data, let normal parsing handle it
                if _looks_like_full_customer_entry(msg):
                    pass
                else:
                    m_clean = re.sub(r"[^\w\s']", " ", msg).strip()
        

                    stop_words = {
                        "what", "is", "whats", "what's", "info", "information", "for", "on",
                        "lookup", "show", "me", "please", "customer", "customers",
                        "email", "phone", "number", "address", "birthday", "bday"
                    }

                    tokens = []
                    for raw in m_clean.split():
                        t = raw.strip()
                        if t.lower().endswith("'s"):
                            t = t[:-2]
                        if not t:
                            continue
                        if t.isdigit():
                            continue
                        if t.lower() in ("day", "days", "week", "weeks", "month", "months", "year", "years", "quarter", "quarters"):
                            continue
                        if t.lower() not in stop_words:
                            tokens.append(t)

                    guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
                    guess = _resolve_pronoun_guess(guess, state)
                    if not guess:
                        return ChatReply(ui['who_is_customer'])

                    with tx() as (conn, cur):
                        matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)
                        last_order = None
                        if len(matches) == 1:
                            orders = get_recent_orders_for_customer(cur, matches[0]["id"], limit=1)
                            last_order = orders[0] if orders else None

                    if len(matches) == 0:
                        return ChatReply(ui["no_customer_found_yet"].format(name=guess))

                    if len(matches) == 1:
                        c = matches[0]
                        state["last_ref_customer_id"] = None
                        state["last_ref_customer_name"] = None
                        state["last_customer"] = None
                        save_session_state(state, session_id=sid)
                        return ChatReply(format_customer_card(c, last_order=last_order))

                    # Multiple matches → trigger picker
                    top = matches[:3]
                    state["pending"] = {"kind": "pick_customer", "candidates": top, "action": "info"}
                    save_session_state(state, session_id=sid)

                    return ChatReply(render_customer_picker(top))

        # -------------------------
        # Pending flows
        # -------------------------
        if pending:
            kind = pending.get("kind")

###

            if kind == "pick_customer":
                # user should reply 1/2/3
                choice = (msg or "").strip()

                if not choice.isdigit():
                    return ChatReply(ui["multiple_matches"])

                idx = int(choice)
                candidates = pending.get("candidates") or []
                if idx < 1 or idx > len(candidates):
                    return ChatReply(ui["multiple_matches"])

                c = candidates[idx - 1]
                customer_id = int(c["id"])
                customer_name = f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip()

                # Remember for follow-ups
                state["last_ref_customer_id"] = customer_id
                state["last_ref_customer_name"] = customer_name

                # Resume the original action
                action = pending.get("action")  # "info" | "orders" | "spend" | "delete"
                start_date = pending.get("start_date")
                end_date = pending.get("end_date")

                from db import tx
                from crm_store import format_recent_orders, get_customer_spending, count_orders_for_customer

                # Clear pending before doing work (prevents loops)
                state["pending"] = None
                save_session_state(state, session_id=sid)

                if action == "info":
                    with tx() as (conn, cur):
                        orders = get_recent_orders_for_customer(cur, c["id"], limit=1)
                    last_order = orders[0] if orders else None
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    state["last_customer"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(format_customer_card(c, last_order=last_order))

                if action == "orders":
                    with tx() as (conn, cur):
                        limit = int(pending.get("orders_limit") or 3)
                        orders = get_recent_orders_for_customer(cur, customer_id=customer_id, limit=limit)
                    return ChatReply(format_recent_orders(customer_name, orders))

                if action == "delete":
                    with tx() as (conn, cur):
                        order_count = count_orders_for_customer(cur, customer_id=customer_id)

                    state["pending"] = {
                        "kind": "delete_customer_confirm",
                        "customer_id": customer_id,
                        "customer_name": customer_name,
                        "order_count": order_count,
                    }
                    save_session_state(state, session_id=sid)

                    if order_count > 0:
                        return ChatReply(
                            f"This will delete {customer_name} from MyPinkAssistant and also remove "
                            f"{order_count} local order(s). Type DELETE to confirm, or `cancel`."
                        )
                    return ChatReply(
                        f"This will delete {customer_name} from MyPinkAssistant. "
                        f"Type DELETE to confirm, or `cancel`."
                    )

                if action == "spend":
                    with tx() as (conn, cur):
                        total_spent = get_customer_spending(
                            cur,
                            consultant_id=consultant_id,
                            customer_id=customer_id,
                            start_date=start_date,
                            end_date=end_date,
                        )

                    # period label (stored if we want; fall back)
                    period = pending.get("period_label") or "lifetime"
                    return ChatReply(ui["customer_spent"].format(name=customer_name, total=f"{total_spent:,.2f}", period=period))

                if action == "order_customer_pick":
                    order_draft = pending.get("order_draft") or {}
                    if not order_draft:
                        return ChatReply(ui["lost_order_draft"])

                    # Attach the exact chosen customer
                    order_draft["customer_id"] = customer_id
                    order_draft["customer"] = {
                        "First Name": (c.get("first_name") or "").strip(),
                        "Last Name": (c.get("last_name") or "").strip(),
                    }

                    save_session_state(state, session_id=sid)

                    # Try to auto-pick product matches first
                    for line in order_draft.get("lines", []):
                        if line.get("chosen") is None:
                            picked, _m = auto_pick_match(catalog, line["text"])
                            if picked:
                                line["chosen"] = picked

                    # If no items were provided yet, ask for them now
                    if not order_draft.get("lines"):
                        cust_first = (c.get("first_name") or "").strip()
                        cust_last = (c.get("last_name") or "").strip()
                        state["pending"] = {
                            "kind": "awaiting_order_items",
                            "customer_first": cust_first,
                            "customer_last": cust_last,
                            "customer_id": customer_id,
                            "fulfillment_method": order_draft.get("fulfillment_method", "inventory"),
                            "leave_pending": bool(order_draft.get("leave_pending", False)),
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(ui["got_it_ordering_for"].format(name=f"{cust_first} {cust_last}".strip()) + "\n" + ui["need_items"])

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
                        save_session_state(state, session_id=sid)
                        return ChatReply(propose_top(top, current_qty=order_draft["lines"][nxt]["qty"], ui=ui))

                    state["pending"] = {"kind": "order_confirm", "order": order_draft}
                    save_session_state(state, session_id=sid)

                    warning = self._get_order_warning_by_customer_id(consultant_id, order_draft.get("customer_id"))
                    extra = f"\n\n{warning}" if warning else ""

                    return ChatReply(
                        self._format_order_confirm(order_draft, ui)
                        + extra
                        + "\n\n"
                        + ui["order_adjust_hint"]
                    )

                return ChatReply(ui["what_to_do_customer"])

            if kind == "inventory_confirm_top":
                top = pending["top"]
                matches = pending.get("matches") or []
                action = pending.get("action")
                qty = int(pending.get("qty") or 0)

                if yes(msg):
                    sku = (top.get("sku") or "").strip()
                    product_name = (top.get("product_name") or "").strip()
                    with tx() as (conn, cur):
                        if action == "add":
                            upsert_inventory_quantity(cur, consultant_id=consultant_id, sku=sku, qty_delta=qty)
                        elif action == "remove":
                            upsert_inventory_quantity(cur, consultant_id=consultant_id, sku=sku, qty_delta=-qty)
                        else:
                            upsert_inventory_quantity(cur, consultant_id=consultant_id, sku=sku, set_qty=qty)
                        row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                        current_qty = int((row or {}).get("qty_on_hand") or 0)
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    if action == "add":
                        return ChatReply(ui["inventory_added"].format(qty=qty, product=product_name, current=current_qty))
                    elif action == "remove":
                        return ChatReply(ui["inventory_removed"].format(qty=qty, product=product_name, current=current_qty))
                    else:
                        return ChatReply(ui["inventory_set"].format(product=product_name, qty=qty, current=current_qty))

                if no(msg):
                    state["pending"] = {
                        "kind": "inventory_pick_top5",
                        "action": action,
                        "qty": qty,
                        "product_text": pending.get("product_text", ""),
                        "matches": matches,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches, show_scores=show_scores, ui=ui))

                return ChatReply(ui["reply_yes_no"])

            if kind == "inventory_pick_top5":
                choice = (msg or "").strip()
                matches = pending.get("matches") or []

                if not choice.isdigit():
                    return ChatReply(ui["pick_match_5"])

                idx = int(choice)
                if idx < 1 or idx > min(TOP5, len(matches)):
                    return ChatReply(ui["pick_match_5"])

                chosen = matches[idx - 1]
                action = pending.get("action")
                qty = int(pending.get("qty") or 0)

                sku = (chosen.get("sku") or "").strip()
                product_name = (chosen.get("product_name") or "").strip()

                with tx() as (conn, cur):
                    if action == "add":
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            qty_delta=int(qty),
                        )
                    elif action == "remove":
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            qty_delta=-int(qty),
                        )
                    else:
                        upsert_inventory_quantity(
                            cur,
                            consultant_id=consultant_id,
                            sku=sku,
                            set_qty=int(qty),
                        )

                    row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                    current_qty = int((row or {}).get("qty_on_hand") or 0)

                state["pending"] = None
                save_session_state(state, session_id=sid)

                if action == "add":
                    return ChatReply(ui["inventory_added"].format(qty=qty, product=product_name, current=current_qty))
                elif action == "remove":
                    return ChatReply(ui["inventory_removed"].format(qty=qty, product=product_name, current=current_qty))
                else:
                    return ChatReply(ui["inventory_set"].format(product=product_name, qty=qty, current=current_qty))

            if kind == "inventory_threshold_confirm_top":
                top = pending["top"]
                matches = pending.get("matches") or []
                qty = int(pending.get("qty") or 0)

                if yes(msg):
                    sku = (top.get("sku") or "").strip()
                    product_name = (top.get("product_name") or "").strip()
                    with tx() as (conn, cur):
                        upsert_inventory_quantity(cur, consultant_id=consultant_id, sku=sku, low_stock_threshold=qty)
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["low_stock_set"].format(product=product_name, qty=qty))

                if no(msg):
                    state["pending"] = {
                        "kind": "inventory_threshold_top5",
                        "qty": qty,
                        "product_text": pending.get("product_text", ""),
                        "matches": matches,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches, show_scores=show_scores, ui=ui))

                return ChatReply(ui["reply_yes_no"])

            if kind == "inventory_threshold_top5":
                choice = (msg or "").strip()
                matches = pending.get("matches") or []

                if not choice.isdigit():
                    return ChatReply(ui["pick_match_5"])

                idx = int(choice)
                if idx < 1 or idx > min(TOP5, len(matches)):
                    return ChatReply(ui["pick_match_5"])

                chosen = matches[idx - 1]
                qty = int(pending.get("qty") or 0)
                sku = (chosen.get("sku") or "").strip()
                product_name = (chosen.get("product_name") or "").strip()

                with tx() as (conn, cur):
                    upsert_inventory_quantity(
                        cur,
                        consultant_id=consultant_id,
                        sku=sku,
                        low_stock_threshold=qty,
                    )

                state["pending"] = None
                save_session_state(state, session_id=sid)

                return ChatReply(ui["low_stock_set"].format(product=product_name, qty=qty))

            if kind == "customer_confirm":
                if yes(msg):
                    customer = pending["customer"]

                    # 1) Save to CRM (permanent)
                    from crm_store import upsert_customer_from_pending
                    customer = pending["customer"]

                    state_val = (customer.get("State") or "").strip()

                    first = (customer.get("First Name") or "").strip()
                    last = (customer.get("Last Name") or "").strip()

                    if not first or not last:
                        return ChatReply(
                            "I need both a first and last name before MyCustomers can save this customer. "
                            "Please type `cancel` and re-enter the customer with the full name."
                        )

                    phone_digits = normalize_phone(customer.get("Phone") or "")
                    if len(phone_digits) == 11 and phone_digits.startswith("1"):
                        phone_digits = phone_digits[1:]
                        customer["Phone"] = phone_digits
                    if phone_digits and len(phone_digits) != 10:
                        return ChatReply(
                            f"The phone number I have ({phone_digits}) isn't 10 digits — MyCustomers requires a 10-digit US number. "
                            "Please type the correct number or say cancel."
                        )

                    street_val = (customer.get("Street") or "").strip()
                    city_val   = (customer.get("City") or "").strip()
                    zip_val    = (customer.get("Postal Code") or "").strip()
                    if street_val and not (city_val and state_val and zip_val):
                        return ChatReply(
                            "I only see a partial address. Please enter the full address (street, city, state, and zip) or type cancel to save without one."
                        )

                    valid_states = set(STATE_MAP.values())
                    state_ok = state_val in valid_states
                    if state_val and not state_ok:
                        return ChatReply(
                            f"I wasn't able to recognize \"{state_val}\" as a valid state. "
                            "Please re-enter the address with the full state name (e.g. Texas) or abbreviation (e.g. TX), or say cancel."
                        )

                    email_val = (customer.get("Email") or "").strip()
                    if email_val:
                        _at = email_val.find("@")
                        _dot = email_val.rfind(".")
                        _tld_len = len(email_val) - _dot - 1
                        if _at <= 0 or _dot <= _at or _tld_len < 2:
                            return ChatReply(
                                f"The email I have ({email_val}) doesn't look valid — please type the correct email or say cancel."
                            )

                    bday_val = (customer.get("Birthday") or "").strip()
                    if bday_val:
                        try:
                            parsed_bday = datetime.datetime.strptime(bday_val, "%Y-%m-%d").date()
                            if parsed_bday > datetime.date.today():
                                return ChatReply(
                                    f"The birthday I have ({birthday_display(bday_val)}) is in the future — please type the correct birthday or say cancel."
                                )
                        except ValueError:
                            pass

                    with tx() as (conn, cur):
                        upsert_customer_from_pending(cur, consultant_id=consultant_id, customer=customer)

                    # 2) Keep existing behavior: job for worker/playwright
                    insert_job("NEW_CUSTOMER", customer, consultant_id=consultant_id)

                    state["pending"] = None
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    state["last_customer"] = None
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

                if looks_like_command(msg):
                    return ChatReply(
                        ui["confirming_customer"] + "\n\n"
                        + self._format_customer_confirm(pending["customer"], ui)
                    )
                updated, notes = apply_customer_edits(pending["customer"], msg)
                pending["customer"] = updated
                state["pending"] = pending
                save_session_state(state, session_id=sid)

                note_line = ""
                if notes:
                    note_line = "Updated: " + ", ".join(notes[:3]) + ("…" if len(notes) > 3 else "") + "\n\n"

                return ChatReply(note_line + self._format_customer_confirm(updated, ui))

            if kind == "delete_customer_confirm":
                answer = (msg or "").strip()

                if answer.upper() == "DELETE":
                    cid = int(pending["customer_id"])
                    name = pending.get("customer_name") or "Customer"

                    from db import tx
                    from crm_store import delete_customer_local

                    with tx() as (conn, cur):
                        n = delete_customer_local(cur, consultant_id=consultant_id, customer_id=cid, delete_orders=True)

                    state["pending"] = None
                    save_session_state(state, session_id=sid)

                    if n:
                        return ChatReply(ui["deleted_customer"].format(name=name))
                    return ChatReply(ui["delete_failed"])

                if answer.lower() in ("cancel", "stop", "no"):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["canceled"])

                return ChatReply(ui["delete_confirm_prompt"])

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
                    return ChatReply(propose_top(top, current_qty=q_new, ui=ui))

                if yes(msg):
                    if not (top.get("sku") or "").strip():
                        # No match found — can't confirm a blank item
                        return ChatReply(
                            "I couldn't find that product in the catalog. "
                            "Try rewording it (brand, line, or shade helps), or say `cancel` to start over."
                        )
                    order["lines"][line_index]["chosen"] = top
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                if no(msg):
                    if not matches:
                        state["pending"] = {
                            "kind": "order_line_pick_top5_or_search",
                            "order": order,
                            "line_index": line_index,
                            "matches": [],
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(
                            "I couldn't find that product in the catalog. "
                            "Try typing a different description and I'll search again, or say cancel to start over."
                        )
                    state["pending"] = {
                        "kind": "order_line_pick_top5_or_search",
                        "order": order,
                        "line_index": line_index,
                        "matches": matches[:MATCH_LIMIT],
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches, show_scores=show_scores, ui=ui))

                if looks_like_command(msg):
                    return ChatReply(
                        ui["confirming_order"] + "\n\n"
                        + self._format_order_confirm(order, ui) + "\n\n"
                        + ui["order_adjust_hint"]
                    )

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
                return ChatReply(render_top5(new_matches, show_scores=show_scores, ui=ui))

            if kind == "awaiting_order_items":
                cust_first = pending["customer_first"]
                cust_last = pending["customer_last"]
                fulfillment_method = pending.get("fulfillment_method", "inventory")
                leave_pending = bool(pending.get("leave_pending", False))
                resolved_customer_id = pending.get("customer_id")

                if looks_like_command(msg):
                    return ChatReply(
                        f"I don't see an item I can add to {cust_first} {cust_last}'s order. "
                        f"You can type what you would like to add to the order or say cancel to start over."
                    )

                _parsed = {}
                try:
                    _parsed = parse_with_openai(self.client, f"order for {cust_first} {cust_last}: {msg.strip()}", last_customer)
                    items = (_parsed.get("order") or {}).get("items") or []
                except Exception:
                    items = []
                if not items:
                    qty, item_text = parse_qty_prefix(msg.strip())
                    items = [{"text": item_text, "qty": qty}] if item_text else []
                order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending)
                order_draft["customer_id"] = resolved_customer_id
                order_draft["order_date"] = ((_parsed.get("order") or {}).get("order_date") or "").strip()
                if not order_draft["lines"]:
                    return ChatReply(ui["no_items_caught"])
                for line in order_draft["lines"]:
                    picked, _m = auto_pick_match(catalog, line["text"])
                    if picked:
                        line["chosen"] = picked
                state["pending"] = None
                return self._continue_resolving_and_reply(state, order_draft, consultant_id, sid, catalog, ui)

            if kind == "order_confirm":
                order = pending["order"]

                # ✅ FIRST: handle add/remove (so they don't get blocked by looks_like_command)
                action, rest = parse_add_remove(msg)

                if action == "add":
                    if not rest:
                        return ChatReply(ui["add_hint"])
                    # Parse items through OpenAI same as initial order entry so multi-item
                    # text without commas works (e.g. "add cc cream timewise cleanser satin hands")
                    cust_first = order.get("customer", {}).get("First Name", "")
                    cust_last  = order.get("customer", {}).get("Last Name", "")
                    try:
                        _add_parsed = parse_with_openai(self.client, f"order for {cust_first} {cust_last}: {rest}", last_customer)
                    except Exception:
                        _add_parsed = {}
                    _add_items = (_add_parsed.get("order") or {}).get("items") or []
                    if not _add_items:
                        # Fallback: treat whole rest as single item
                        qty, item_text = parse_qty_prefix(rest)
                        _add_items = [{"text": item_text, "qty": qty}] if item_text else []
                    if not _add_items:
                        return ChatReply(ui["add_hint"])
                    for it in _add_items:
                        item_text = (it.get("text") or "").strip()
                        qty = int(it.get("qty") or 1)
                        if item_text:
                            order["lines"].append({"text": item_text, "qty": qty, "chosen": None})
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                if action == "remove":
                    target = (rest or "").strip()
                    if not target:
                        return ChatReply(
                            ui["remove_hint"] + "\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )
                    if re.search(r'\band\b|,', target, re.IGNORECASE):
                        return ChatReply(
                            "I can only remove one item at a time. Which one would you like to remove first?\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )
                    removed = self._remove_line(order, target)
                    if not removed:
                        return ChatReply(
                            ui["remove_not_found"] + "\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )
                    state["pending"] = {"kind": "order_confirm", "order": order}
                    save_session_state(state, session_id=sid)
                    return ChatReply(self._format_order_confirm(order, ui) + "\n\n" + ui["order_adjust_hint"])

                # ✅ THEN: guardrail for random commands (but not add/remove)
                if looks_like_command(msg) and not yes(msg) and not no(msg):
                    return ChatReply(
                        ui["confirming_order"] + "\n\n"
                        + self._format_order_confirm(order, ui) + "\n\n"
                        + ui["order_adjust_hint"]
                    )

                # ... keep your existing yes/no handling below ...

                if yes(msg):
                    cust_first = order["customer"]["First Name"]
                    cust_last = order["customer"]["Last Name"]

                    # 1) Save order + items to CRM (permanent, even if Playwright fails)
                    from crm_store import get_customer_id_by_name, create_order_from_confirmed, upsert_customer_from_pending

                    with tx() as (conn, cur):
                        # 1) Prefer the customer_id attached to THIS order flow
                        customer_id = order.get("customer_id")

                        # 2) If not available, fall back to name matching
                        if not customer_id:
                            customer_id = get_customer_id_by_name(cur, consultant_id, cust_first, cust_last)

                        # 3) If still not found, create a minimal customer record
                        if customer_id is None:
                            customer_id = upsert_customer_from_pending(
                                cur,
                                consultant_id=consultant_id,
                                customer={"First Name": cust_first, "Last Name": cust_last},
                            )

                        customer_id = int(customer_id)

                        create_order_from_confirmed(
                            cur,
                            consultant_id=consultant_id,
                            customer_id=customer_id,
                            order_lines=order["lines"],
                            source="chat",
                            order_date=(order.get("order_date") or None),
                        )

                    # 2) Queue jobs for worker/playwright
                    _fulfillment = order.get("fulfillment_method", "inventory")
                    _leave_pending = bool(order.get("leave_pending", False))
                    _order_date = (order.get("order_date") or "").strip() or None
                    for line in order["lines"]:
                        sku = line["chosen"]["sku"]
                        qty = int(line["qty"])
                        for _ in range(max(1, qty)):
                            insert_job(
                                "NEW_ORDER_ROW",
                                {
                                    "First Name": cust_first,
                                    "Last Name": cust_last,
                                    "SKU": sku,
                                    "fulfillment_method": _fulfillment,
                                    "leave_pending": _leave_pending,
                                    "order_date": _order_date,
                                },
                                consultant_id=consultant_id,
                            )

                    # 3) Decrement personal inventory for each ordered item (skip for CDS)
                    if _fulfillment != "cds":
                        with tx() as (conn, cur):
                            for line in order["lines"]:
                                sku = line["chosen"]["sku"]
                                qty = int(line["qty"])
                                upsert_inventory_quantity(
                                    cur,
                                    consultant_id=consultant_id,
                                    sku=sku,
                                    qty_delta=-qty,
                                )

                    state["pending"] = None
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    state["last_customer"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["order_confirmed"].format(first=cust_first, last=cust_last))

                if no(msg):
                    state["pending"] = None
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(ui["order_reject"])

                return ChatReply(ui["reply_yes_no_adjust"])

        # -------------------------
        # Normal parse
        # -------------------------

        # Strip tag/tags value from message before sending to OpenAI so tag
        # content can't bleed into customer fields (e.g. "tag: 2026 Customers")
        import re as _re
        _tag_match = _re.search(r'\btags?\s*:\s*(.+?)(?=\s+\w+\s*:|$)', msg, flags=_re.IGNORECASE | _re.DOTALL)
        _extracted_tag = _tag_match.group(1).strip() if _tag_match else None
        msg_for_parse = _re.sub(r'\btags?\s*:\s*.+?(?=\s+\w+\s*:|$)', '', msg, flags=_re.IGNORECASE | _re.DOTALL).strip() if _extracted_tag else msg

        # Fix doubled street-type/city-prefix ambiguity so OpenAI can split correctly:
        # "555 5th st st paul" → "555 5th st, st paul"
        # "555 5th st. st paul" → "555 5th st., st paul"
        # "123 Oak dr dr phillips" → "123 Oak dr, dr phillips"
        # "1 College ave ave maria" → "1 College ave, ave maria"
        msg_for_parse = _re.sub(r'\b(st|dr|ave)(\.?)\s+(st|dr|ave)\b', r'\1\2, \3', msg_for_parse, flags=_re.IGNORECASE)

        # For "new order for X item1, item2" inline syntax, pre-process into the
        # clean "order for NAME: items" format that entries 2 & 3 use, so OpenAI
        # doesn't confuse product names (charcoal, poppy) with the customer's last name.
        _mfp_lower = msg_for_parse.lower()
        if _mfp_lower.startswith("new order for ") or _mfp_lower.startswith("order for "):
            _pre_cust, _pre_items = _split_order_for_prefix(msg_for_parse)
            if _pre_cust and _pre_items:
                msg_for_parse = f"order for {_pre_cust}: {_pre_items}"

        try:
            parsed = parse_with_openai(self.client, msg_for_parse, last_customer)
        except Exception:
            return ChatReply(ui["trouble"])

        if parsed.get("type") == "customer":
            customer = parsed.get("customer") or {}

            # If no name was parsed, ask for it before showing the card
            _first = (customer.get("First Name") or "").strip()
            _last = (customer.get("Last Name") or "").strip()
            if not _first and not _last:
                return ChatReply("What's the customer's name?")

            # Tags: always use our pre-extracted value (authoritative).
            # If we found tag: keyword → use that. If no tag: keyword → clear
            # whatever OpenAI guessed (it tends to pull random words into Tags).
            if _extracted_tag:
                customer["Tags"] = _extracted_tag
            else:
                customer["Tags"] = ""
            customer["State"] = normalize_state(customer.get("State", ""))
            customer["Phone"] = normalize_phone(customer.get("Phone", ""))
            customer["Birthday"] = normalize_birthday(customer.get("Birthday", ""))
            customer["City"] = normalize_city(customer.get("City", ""))

            state["pending"] = {"kind": "customer_confirm", "customer": customer}
            save_session_state(state, session_id=sid)
            return ChatReply(self._format_customer_confirm(customer, ui))

        if parsed.get("type") == "order":
            order = parsed.get("order") or {}
            cust_first = (order.get("customer_first") or "").strip()
            cust_last = (order.get("customer_last") or "").strip()
            fulfillment_method = "cds" if (order.get("fulfillment_method") or "").lower() == "cds" else "inventory"
            leave_pending = bool(order.get("leave_pending")) or fulfillment_method == "cds"

            # Promote flag words that the AI mistakenly put in the items list
            _FLAG_WORDS = {"cds", "pending", "customer delivery", "customer delivery service"}
            cleaned_items = []
            for it in (order.get("items") or []):
                item_text = (it.get("text") or "").strip().lower()
                if item_text in _FLAG_WORDS:
                    if item_text in ("cds", "customer delivery", "customer delivery service"):
                        fulfillment_method = "cds"
                        leave_pending = True
                    elif item_text == "pending":
                        leave_pending = True
                else:
                    cleaned_items.append(it)
            if cleaned_items != (order.get("items") or []):
                order["items"] = cleaned_items

            explicit_customer_hint = ""
            explicit_item_hint = ""

            starts_explicit_order = (
                lowered.startswith("new order for") or lowered.startswith("order for")
            )

            if starts_explicit_order:
                explicit_customer_hint, explicit_item_hint = _split_order_for_prefix(msg)

            # If parser missed the customer name but raw text clearly contains one,
            # use the raw hint instead of falling back to last_customer.
            if not cust_first and not cust_last and explicit_customer_hint:
                hinted_parts = explicit_customer_hint.split()
                cust_first = hinted_parts[0].strip() if len(hinted_parts) >= 1 else ""
                cust_last = hinted_parts[1].strip() if len(hinted_parts) >= 2 else ""

            has_explicit_name = bool(cust_first or cust_last or explicit_customer_hint)

            bad_pronoun_parse = (
                cust_first.lower() in ("she", "he", "they", "her", "him", "them")
                or cust_last.lower() == "ordered"
            )

            # ONLY fallback if NO real name was provided,
            # and this is NOT an explicit "new order for ..." style message.
            if (not has_explicit_name or bad_pronoun_parse) and last_customer and not starts_explicit_order:
                cust_first = (last_customer.get("First Name") or "").strip()
                cust_last = (last_customer.get("Last Name") or "").strip()

            customer_name_for_lookup = " ".join([p for p in [cust_first, cust_last] if p]).strip()

            # If the user explicitly started a new order for someone,
            # do not fall back to the previous customer.
            if starts_explicit_order and not customer_name_for_lookup:
                return ChatReply(ui["need_customer_for_order"])

            if not customer_name_for_lookup:
                return ChatReply(ui["need_customer_for_order"])

            # Resolve CRM customer match once and carry it through the order flow
            resolved_customer_id = None

            with tx() as (conn, cur):
                matches = find_customers_by_name(
                    cur,
                    consultant_id=consultant_id,
                    name=customer_name_for_lookup,
                    limit=3,
                )

            full_name_typed = bool(cust_first and cust_last)

            if len(matches) == 0:
                # No match at all — hard stop regardless of how name was typed
                unresolved_name = customer_name_for_lookup or explicit_customer_hint
                if full_name_typed:
                    return ChatReply(ui["customer_not_in_mc"].format(name=unresolved_name))
                return ChatReply(ui["no_customer_found"].format(name=unresolved_name))

            if len(matches) == 1:
                matched_first = (matches[0].get("first_name") or "").strip()
                matched_last = (matches[0].get("last_name") or "").strip()

                typed_full = " ".join([p for p in [cust_first, cust_last] if p]).strip().lower()
                matched_full = f"{matched_first} {matched_last}".strip().lower()

                strong_enough_match = (
                    typed_full == matched_full
                    or fuzz.WRatio(typed_full, matched_full) >= 90
                )

                if (not full_name_typed) or strong_enough_match:
                    resolved_customer_id = int(matches[0]["id"])
                    cust_first = matched_first
                    cust_last = matched_last

                    state["last_ref_customer_id"] = int(matches[0]["id"])
                    state["last_ref_customer_name"] = f"{cust_first} {cust_last}".strip()
                    save_session_state(state, session_id=sid)
                else:
                    # Full name typed but weak match — show picker instead of sliding through
                    items = order.get("items") or []
                    if not items and explicit_item_hint:
                        items = [{"text": explicit_item_hint, "qty": 1}]
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3]))

            elif len(matches) > 1:
                strong_local_match = any(
                    ((m.get("first_name") or "").strip().lower() == cust_first.lower())
                    and ((m.get("last_name") or "").strip().lower() == cust_last.lower())
                    for m in matches
                )

                if not full_name_typed or strong_local_match:
                    items = order.get("items") or []
                    if not items and explicit_item_hint:
                        items = [{"text": explicit_item_hint, "qty": 1}]
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3]))

                else:
                    # Full name typed, multiple fuzzy matches, none exact — show picker
                    items = order.get("items") or []
                    if not items and explicit_item_hint:
                        items = [{"text": explicit_item_hint, "qty": 1}]
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3]))

            items = order.get("items") or []

            # If parser missed items but raw text clearly had an item tail, recover it.
            if not items and explicit_item_hint:
                items = [{"text": explicit_item_hint, "qty": 1}]

            customer_line = f"{cust_first} {cust_last}".strip()

            if not items:
                state["pending"] = {
                    "kind": "awaiting_order_items",
                    "customer_first": cust_first,
                    "customer_last": cust_last,
                    "customer_id": resolved_customer_id,
                    "fulfillment_method": fulfillment_method,
                    "leave_pending": leave_pending,
                }
                save_session_state(state, session_id=sid)
                prefix = ui["got_it_ordering_for"].format(name=customer_line)
                return ChatReply(f"{prefix}\n{ui['need_items']}")

            order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending)
            order_draft["customer_id"] = resolved_customer_id
            order_draft["order_date"] = (order.get("order_date") or "").strip()
            if not order_draft["lines"]:
                return ChatReply(ui["no_items_caught"])

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

                save_session_state(state, session_id=sid)
                prefix = ui["got_it_ordering_for"].format(name=customer_line)
                return ChatReply(f"{prefix}\n{propose_top(top, current_qty=order_draft['lines'][nxt]['qty'], ui=ui)}")

            # CDS orders require an address — hard block before showing confirm
            if fulfillment_method == "cds" and not self._customer_has_address(consultant_id, order_draft.get("customer_id")):
                cust_name = f"{cust_first} {cust_last}".strip()
                return ChatReply(
                    f"CDS orders ship directly to the customer, so {cust_name} needs an address on file in MyCustomers before this order can be placed. "
                    "Please add her address there and try again."
                )

            state["pending"] = {"kind": "order_confirm", "order": order_draft}

            save_session_state(state, session_id=sid)

            warning = self._get_order_warning_by_customer_id(consultant_id, order_draft.get("customer_id"))
            extra = f"\n\n{warning}" if warning else ""

            return ChatReply(
                self._format_order_confirm(order_draft, ui)
                + extra
                + "\n\n"
                + ui["order_adjust_hint"]
            )

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
                save_session_state(state, session_id=sid)

                warning = self._get_order_warning_by_customer_id(consultant_id, order.get("customer_id"))
                extra = f"\n\n{warning}" if warning else ""

                return ChatReply(
                    self._format_order_confirm(order, ui)
                    + extra
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
            return ChatReply(propose_top(top, current_qty=order["lines"][nxt]["qty"], ui=ui))

    ## format_customer_confirm
    def _format_customer_confirm(self, customer: dict, ui: dict) -> str:
        street_base = (customer.get("Street") or "").strip()
        street2 = (customer.get("Street2") or "").strip()
        street = f"{street_base} {street2}".strip() if street2 else street_base
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

        #warning = ""
        #if not street:
        #    warning = "\n⚠ No address added yet. Mary Kay now requires an address before personal inventory orders can be submitted.\n"

        tags_raw = (customer.get("Tags") or "").strip()
        tags = ", ".join(t.strip() for t in tags_raw.split(",") if t.strip())
        if tags:
            customer["Tags"] = tags  # normalize in-place for storage/payload
        tags_line = f"• Tags: {tags}\n" if tags else ""

        # Show one warning at a time (phone → partial address → email).
        # All three also block confirmation in the yes-handler.
        phone_digits = normalize_phone(customer.get("Phone") or "")
        if len(phone_digits) == 11 and phone_digits.startswith("1"):
            phone_digits = phone_digits[1:]
        email_val = (customer.get("Email") or "").strip()

        warning = ""
        if phone_digits and len(phone_digits) != 10:
            warning = f"⚠️ Phone number looks incomplete ({phone_digits}) — please correct it before confirming.\n\n"
        elif street_base and not (city and st and postal):
            warning = "⚠️ I only see a partial address — please enter the full address (street, city, state, and zip) or type cancel to save without one.\n\n"
        elif email_val:
            _at = email_val.find("@")
            _dot = email_val.rfind(".")
            _tld_len = len(email_val) - _dot - 1
            if _at <= 0 or _dot <= _at or _tld_len < 2:
                warning = f"⚠️ Email looks incomplete: {email_val} — please correct it before confirming.\n\n"

        return (
            f"{warning}{ui['cust_submit_intro']}\n"
            f"• {ui['name']}: {customer.get('First Name','').strip()} {customer.get('Last Name','').strip()}\n"
            f"• {ui['email']}: {(customer.get('Email','') or '').strip() or ui['none']}\n"
            f"• {ui['phone']}: {phone_disp or ui['none']}\n"
            f"• {ui['address']}: {addr}\n"
            f"• {ui['birthday']}: {birthday_disp or ui['none']}\n"
            f"{tags_line}"
            f"{ui['cust_confirm_q']}\n"
            f"{ui['cust_edit_hint']}"
            + _QR_YN
        )


    def _make_order_draft(self, cust_first: str, cust_last: str, items: List[dict], fulfillment_method: str = "inventory", leave_pending: bool = False) -> dict:
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
        return {
            "customer": {"First Name": cust_first, "Last Name": cust_last},
            "lines": lines,
            "fulfillment_method": fulfillment_method,
            "leave_pending": leave_pending,
        }

    def _aggregate_lines_for_preview(self, order: dict) -> List[dict]:
        """
        Aggregates identical items for DISPLAY ONLY.
        Does NOT change order["lines"] (so Playwright/job creation stays 1-row-per-unit).
        Group key is SKU when available (best), else product_name, else raw text.
        Returns list of dicts: {"name": str, "price": float|None, "qty": int}
        """
        groups: Dict[str, dict] = {}

        for line in (order.get("lines") or []):
            qty = int(line.get("qty") or 1)
            if qty < 1:
                qty = 1

            chosen = line.get("chosen") or {}
            sku = (chosen.get("sku") or "").strip()
            name = (chosen.get("product_name") or "").strip() or (line.get("text") or "").strip()
            price = chosen.get("price")

            # Prefer SKU grouping; fallback to name/text
            key = sku or name.lower()

            if key not in groups:
                groups[key] = {"name": name, "price": price, "qty": 0}

            groups[key]["qty"] += qty

            # If price was missing before and we see it now, keep it
            if groups[key].get("price") is None and isinstance(price, (int, float)):
                groups[key]["price"] = price

        return list(groups.values())

    def _customer_has_address(self, consultant_id: int, customer_id: int | None) -> bool:
        if not customer_id:
            return False
        conn = db_connect()
        cur = conn.cursor()
        try:
            cur.execute(
                f"SELECT street FROM customers WHERE consultant_id={PH} AND id={PH} LIMIT 1",
                (int(consultant_id), int(customer_id)),
            )
            row = cur.fetchone()
            if not row:
                return False
            street = (row["street"] if isinstance(row, dict) else row[0]) or ""
            return bool(street.strip())
        finally:
            try:
                cur.close()
            except Exception:
                pass
            conn.close()

    def _get_order_readiness_warning(self, customer_row: dict | None) -> str:
        if not customer_row:
            return ""

        is_ready = customer_row.get("is_order_ready")
        if is_ready in (1, True, "1", "true", "True"):
            return ""

        return (
            "⚠️ This customer may be missing address or name information in MyCustomers. "
            "If the order fails, please open the customer in MyCustomers, confirm the name and address details, and try again."
        )

    def _get_order_warning_by_customer_id(self, consultant_id: int, customer_id: int | None) -> str:
        if not customer_id:
            return ""

        conn = db_connect()
        cur = conn.cursor()
        try:
            if is_postgres():
                cur.execute(
                    f"""
                    SELECT is_order_ready, missing_order_fields
                    FROM customers
                    WHERE consultant_id={PH} AND id={PH}
                    LIMIT 1
                    """,
                    (int(consultant_id), int(customer_id)),
                )
            else:
                cur.execute(
                    f"""
                    SELECT is_order_ready, missing_order_fields
                    FROM customers
                    WHERE consultant_id={PH} AND id={PH}
                    LIMIT 1
                    """,
                    (int(consultant_id), int(customer_id)),
                )

            row = cur.fetchone()
            if not row:
                return ""

            if isinstance(row, dict):
                customer_row = row
            else:
                customer_row = {
                    "is_order_ready": row[0],
                    "missing_order_fields": row[1],
                }

            return self._get_order_readiness_warning(customer_row)
        finally:
            try:
                cur.close()
            except Exception:
                pass
            conn.close()

    def _format_order_confirm(self, order: dict, ui: dict) -> str:
        from datetime import date as _date
        cust = order["customer"]
        fulfillment = order.get("fulfillment_method", "inventory")
        leave_pending = bool(order.get("leave_pending", False))
        if fulfillment == "cds":
            label = " (CDS)"
        elif leave_pending:
            label = " (PENDING)"
        else:
            label = ""
        intro = ui["order_intro"].format(first=cust["First Name"], last=cust["Last Name"])
        out = [intro.replace(":", f"{label}:")]

        # Order date display + warning
        order_date_str = (order.get("order_date") or "").strip()
        if order_date_str:
            try:
                od = _date.fromisoformat(order_date_str)
                today = _date.today()
                formatted = od.strftime("%-m/%-d/%Y")
                out.append(f"Order date: {formatted}")
                if od > today:
                    out.append("⚠️ This date is in the future. Please double-check before confirming.")
                elif (today - od).days > 730:
                    out.append("⚠️ This date is over 2 years ago. Please double-check before confirming.")
            except Exception:
                pass

        total = 0.0
        any_prices = False

        preview_lines = self._aggregate_lines_for_preview(order)

        for pl in preview_lines:
            qty = int(pl["qty"])
            price = pl.get("price")

            if isinstance(price, (int, float)):
                any_prices = True
                total += float(price) * qty

            out.append(f"• {pl['name']} {fmt_price(price)} x{qty}")

        if any_prices:
            out.append(ui["estimated_total"].format(total=f"${total:.2f}"))

        if fulfillment == "cds":
            out.append("\nReminder: you will need to finalize this CDS order on InTouch by navigating to Orders and completing the order.")

        out.append(ui["order_confirm_q"])
        return "\n".join(out) + _QR_YN


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
