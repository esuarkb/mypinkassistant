"""Order-message parsing: the OpenAI order/customer parser and the
deterministic order-text helpers (add/remove, dates, discounts, qty).
"""
import calendar
import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from rapidfuzz import fuzz, process

from .catalog import fmt_price
from .config import MATCH_LIMIT, MODEL


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
        '    "Tags": "",\n'
        '    "Referred By": ""\n'
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
        "- Extract the referring person's name from phrases like 'referred by', 'referral from', 'ref by', 'sent by' into Referred By. The Referred By value is a person's name only (1-3 words) — it ends at the next field (a phone number, email, 'tag:'/'tags:', or end of message). Leave empty if not mentioned.\n"
        "- Birthday may be provided as MM/DD, Month Day, or YYYY-MM-DD. Output as YYYY-MM-DD. If year missing, use 2000.\n"
        "- Each word or phrase separated by 'and' or a comma is a separate item unless it is clearly a shade/variant of the immediately adjacent product (e.g. 'Normal/Dry', 'Ivory 1', 'Berry Kissable', 'Pearl & Gold', 'Navy & Nude'). Color or finish pairs joined by 'and' or '&' are a single shade name, not two items. When in doubt, treat it as a separate product.\n"
        "- For shades/colors/variants (Normal/Dry, Combination/Oily), include them in item text if present.\n"
        "- If the user says a variant applies to multiple items (e.g., 'normal/dry both'), append that variant phrase to each affected item.\n"
        "- Do NOT treat numbers OR product descriptor words that are part of a product name as quantity (examples: '4-in-1 cleanser', '2-in-1', '3D', 'Duo Stick', 'Trio Set'). These are product names, not user-specified quantities.\n"
        "- For foundation products, the shade number is always part of the product name, never a quantity (e.g., 'medium 2 foundation' → qty 1, item text 'medium 2 foundation'; 'light 1 foundation' → qty 1, item text 'light 1 foundation').\n"
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


def _parse_order_date_cmd(message: str):
    """
    Detects 'date <text>' commands. Returns the date text portion or None if not a date command.
    """
    low = (message or "").strip().lower()
    for kw in ("change the date to ", "change date to ", "change the date ", "change date ",
                "update date to ", "update date ", "order date ", "date "):
        if low.startswith(kw):
            return message[len(kw):].strip()
    return None


def _parse_date_value(text: str):
    """Parse natural language date text into YYYY-MM-DD. Returns None if unparseable."""
    import re
    from datetime import date, timedelta
    t = (text or "").strip().lower()
    today = date.today()
    if t in ("today", "hoy"):
        return today.isoformat()
    if t in ("yesterday", "ayer"):
        return (today - timedelta(days=1)).isoformat()
    # ISO: 2026-05-04
    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            pass
    # US: M/D, M/D/YY, M/D/YYYY
    m = re.fullmatch(r'(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?', t)
    if m:
        month, day = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    # Written: "May 4", "May 4 2026", "May 4, 2026"
    _months = {
        "january":1,"jan":1,"february":2,"feb":2,"march":3,"mar":3,
        "april":4,"apr":4,"may":5,"june":6,"jun":6,"july":7,"jul":7,
        "august":8,"aug":8,"september":9,"sep":9,"sept":9,"october":10,"oct":10,
        "november":11,"nov":11,"december":12,"dec":12,
        "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
        "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
    }
    m = re.fullmatch(r'([a-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?', t)
    if m:
        month = _months.get(m[1])
        day = int(m[2])
        year = int(m[3]) if m[3] else today.year
        if month:
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                pass
    return None


def _parse_discount(message: str, order: dict) -> dict | None:
    """
    Tries to parse a discount from the user message.

    Supported patterns:
      "$X off [product]"      — dollar amount off specific item or whole order
      "X% off [product]"      — percent off specific item or whole order
      "$X discount"           — dollar amount off whole order

    Returns a dict:
      {
        "amount": float,          # dollar value of discount (always positive)
        "line_idx": int | None,   # index into order["lines"] or None for order-level
        "label": str,             # display label e.g. "$10.00 off charcoal mask"
      }
    or None if no discount is found.
    """
    msg = (message or "").strip()

    # ---- extract amount + optional product target ----
    amount: float | None = None
    is_percent = False
    target_text: str = ""

    # "$X off [product]" or "$X.XX off [product]"
    m = re.match(r'^\$\s*(\d+(?:\.\d+)?)\s+off\s*(.*)', msg, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        target_text = m.group(2).strip()

    # "X% off [product]"
    if amount is None:
        m = re.match(r'^(\d+(?:\.\d+)?)\s*%\s+off\s*(.*)', msg, re.IGNORECASE)
        if m:
            is_percent = True
            amount = float(m.group(1))
            target_text = m.group(2).strip()

    # "$X discount" or "X discount"
    if amount is None:
        m = re.match(r'^\$?\s*(\d+(?:\.\d+)?)\s+discount\b', msg, re.IGNORECASE)
        if m:
            amount = float(m.group(1))
            target_text = ""

    # bare "X off [product]" (no $ sign) — must be a whole number or decimal, not a word
    if amount is None:
        m = re.match(r'^(\d+(?:\.\d+)?)\s+off\s+(.*)', msg, re.IGNORECASE)
        if m:
            amount = float(m.group(1))
            target_text = m.group(2).strip()

    if amount is None or amount <= 0:
        return None

    # ---- resolve to order line (if product mentioned) ----
    lines = order.get("lines") or []
    line_idx: int | None = None

    if target_text:
        # Build names for fuzzy matching
        names = []
        for ln in lines:
            chosen = ln.get("chosen") or {}
            names.append(chosen.get("product_name") or ln.get("text") or "")

        if names:
            lower_names = [n.lower() for n in names]
            lower_target = target_text.lower()
            results = process.extract(lower_target, lower_names, scorer=fuzz.token_set_ratio, limit=2)
            if results and results[0][1] >= 80:
                best_score = results[0][1]
                best_idx = results[0][2]
                # Only assign to a specific line if it clearly outscores the next best match
                if len(results) < 2 or (best_score - results[1][1]) >= 10:
                    line_idx = best_idx
                # else: ambiguous (two items too similar) — fall through to order-level

    # ---- compute dollar amount ----
    if is_percent:
        if line_idx is not None:
            chosen = lines[line_idx].get("chosen") or {}
            unit_price = float(chosen.get("price") or 0) * int(lines[line_idx].get("qty") or 1)
            dollar_amount = round(unit_price * (amount / 100), 2)
        else:
            subtotal = sum(
                float((ln.get("chosen") or {}).get("price") or 0) * int(ln.get("qty") or 1)
                for ln in lines
            )
            dollar_amount = round(subtotal * (amount / 100), 2)
    else:
        dollar_amount = round(amount, 2)

    if dollar_amount <= 0:
        return None

    # ---- build label ----
    if line_idx is not None:
        chosen = lines[line_idx].get("chosen") or {}
        pname = chosen.get("product_name") or lines[line_idx].get("text") or ""
        label = f"${dollar_amount:.2f} off {pname}"
    else:
        label = f"${dollar_amount:.2f} off order"

    return {"amount": dollar_amount, "line_idx": line_idx, "label": label}


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
