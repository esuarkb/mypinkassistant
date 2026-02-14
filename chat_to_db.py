import os
import re
import json
#import sqlite3
from pathlib import Path
from typing import List, Optional, Any, Tuple
from db import connect

from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from openai import OpenAI


# -------------------------
# Paths / Settings
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"
CATALOG_PATH = BASE_DIR / "catalog" / "catalog 2-6-26.csv"
MODEL = "gpt-4.1-mini"

# Matching UX controls
MATCH_LIMIT = 25   # keep this many candidates behind the scenes
PAGE_SIZE = 5      # show this many at a time in the list UI


# -------------------------
# DB Helpers
# -------------------------
def db_connect():
    if not DB_PATH.exists():
        raise FileNotFoundError("Database not found. Run db_setup.py first.")
    return connect()
    #return sqlite3.connect(DB_PATH)


def insert_job(job_type: str, payload: dict) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO jobs (type, payload_json, status) VALUES (?, ?, 'queued')",
        (job_type, json.dumps(payload)),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


# -------------------------
# Catalog
# -------------------------
def load_catalog(path: Path) -> List[dict]:
    """
    Loads catalog CSV with headers: sku (lowercase), product_name, price

    Also filters out likely "samples" / collateral rows to improve matching.
    (Conservative filters — you can expand later.)
    """
    import csv

    if not path.exists():
        raise FileNotFoundError(f"Catalog not found at: {path}")

    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()  # lowercase sku
            name = (row.get("product_name") or "").strip()
            price = row.get("price")

            if not sku or not name:
                continue

            # ---- Filter out samples / collateral-ish rows (tune as needed) ----
            name_l = name.lower()

            # very common sample indicators
            if "sample" in name_l:
                continue

            # brochure/look/booklet/pack language often not ordered as products
            if "the look" in name_l or "look (" in name_l or "booklet" in name_l:
                continue

            # pack-of language often represents collateral or bulk literature
            # (You can remove this if you actually do order packs as SKUs.)
            if "pk./" in name_l or "pk/" in name_l or "pack/" in name_l:
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
    """
    Fuzzy match with a small "anchor filter" to reduce drifting when phrases overlap
    (ex: 'normal to dry' appears in multiple product families).
    """
    q = (query or "").lower().strip()
    q_compact = re.sub(r"\s+", " ", q)

    anchors = [
        "4-in-1",
        "4 in 1",
        "cc cream",
        "miracle set",
        "ultimate timewise miracle set",
        "timewise miracle set",
        "satin hands",
        "satin lips",
        "foundation primer",
        "foundation brush",
        "liquid foundation brush",
        "shimmer eye shadow stick",
        "undereye corrector",
        "eye cream",
        "roll-up bag",
        "great heights",
        "sheer illusion",
        "primer",
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
        filtered = []
        for c in catalog:
            name_l = c["product_name"].lower()
            if a_l in name_l:
                filtered.append(c)
        if filtered:
            candidates = filtered

    names = [c["product_name"] for c in candidates]
    results = process.extract(q, names, scorer=fuzz.WRatio, limit=limit)

    matches = []
    for name, score, idx in results:
        c = candidates[idx]
        matches.append(
            {
                "sku": c["sku"],
                "product_name": c["product_name"],
                "price": c["price"],
                "score": score,
            }
        )
    return matches


def auto_pick_match(catalog: List[dict], query: str) -> Tuple[Optional[dict], List[dict]]:
    matches = best_matches(catalog, query, limit=MATCH_LIMIT)
    if not matches:
        return None, matches

    top = matches[0]
    second = matches[1] if len(matches) > 1 else {"score": 0}

    # Confidence rule: only auto-pick when pretty sure
    if top["score"] >= 88 and (top["score"] - second["score"]) >= 6:
        return top, matches

    return None, matches


def print_matches(matches: List[dict], offset: int = 0, page_size: int = 5):
    """
    Hides SKU in UI; shows price.
    Displays a page of results.
    """
    page = matches[offset : offset + page_size]
    for i, m in enumerate(page, start=1):
        print(f"  {i}) {m['product_name']} {fmt_price(m['price'])}")


# -------------------------
# OpenAI Parsing
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
        '    "Postal Code": ""\n'
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
        "- If an order does not include a customer name, reuse the last customer if provided.\n"
        "- For shades/colors, include them in item text if present.\n"
        "- Do NOT treat numbers that are part of a product name as quantity (examples: '4-in-1 cleanser', '2-in-1', '3D').\n"
        "- Only set qty > 1 if the user explicitly indicates quantity (two, x2, qty 2, three of them, etc.). Otherwise qty must be 1.\n"
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
# Helpers
# -------------------------
def normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def yes(s: str) -> bool:
    return s.strip().lower() in (
        "y",
        "yes",
        "yeah",
        "yep",
        "confirm",
        "ok",
        "okay",
        "correct",
        "right",
    )


def no(s: str) -> bool:
    return s.strip().lower() in ("n", "no", "nope", "nah", "wrong", "incorrect")


def wants_options(s: str) -> bool:
    return s.strip().lower() in ("options", "show", "show options", "list", "choices")


def fix_qty_if_number_is_part_of_name(text: str, qty: int) -> int:
    """
    Prevent accidental qty extraction from product names like '4-in-1 cleanser', '2-in-1', etc.
    If the text looks like X-in-1 at the start, force qty=1.
    """
    t = (text or "").strip().lower()

    # Examples:
    # "4 in 1 cleanser", "4-in-1 cleanser", "4in1 cleanser"
    looks_like_x_in_1 = bool(re.match(r"^\d+\s*[-]?\s*in\s*[-]?\s*\d+", t)) or "in1" in t.replace(" ", "")[:10]

    if looks_like_x_in_1:
        return 1

    return qty


# -------------------------
# Pending State Objects
# -------------------------
class PendingCustomerConfirm:
    def __init__(self, customer: dict):
        self.customer = customer


class PendingOrderSelectConfirmTop:
    """
    Confirm the top guess for one line (no list shown yet).
    """
    def __init__(self, order: dict, line_index: int, top: dict, matches: List[dict]):
        self.order = order
        self.line_index = line_index
        self.top = top
        self.matches = matches


class PendingOrderSelectFromList:
    """
    Choose 1-5 for one line (list shown in pages).
    Supports:
      - 'more' to page forward
      - 'search: ...' to rerun matching
    """
    def __init__(self, order: dict, line_index: int, matches: List[dict], offset: int = 0, base_query: str = ""):
        self.order = order
        self.line_index = line_index
        self.matches = matches
        self.offset = offset
        self.base_query = base_query


class PendingOrderConfirm:
    def __init__(self, order: dict):
        self.order = order


class PendingOrderEditPickLine:
    def __init__(self, order: dict):
        self.order = order


# -------------------------
# Order draft structure
# -------------------------
def make_order_draft(cust_first: str, cust_last: str, items: List[dict]) -> dict:
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


def format_customer_confirm(customer: dict) -> str:
    return (
        "Okay — here’s the customer I’m about to submit:\n"
        f"• Name: {customer.get('First Name','').strip()} {customer.get('Last Name','').strip()}\n"
        f"• Email: {customer.get('Email','').strip() or '(none)'}\n"
        f"• Phone: {customer.get('Phone','').strip() or '(none)'}\n"
        f"• Address: {customer.get('Street','').strip()}, {customer.get('City','').strip()}, "
        f"{customer.get('State','').strip()} {customer.get('Postal Code','').strip()}\n"
        "Does that look right? (yes/no)"
    )


def format_order_confirm(order: dict) -> str:
    cust = order["customer"]
    lines = order["lines"]

    out = []
    out.append(f"Okay — I have this order for {cust['First Name']} {cust['Last Name']}:")

    total = 0.0
    any_prices = False

    for i, line in enumerate(lines, start=1):
        chosen = line["chosen"]
        qty = int(line["qty"])
        price = chosen.get("price")
        price_str = fmt_price(price)

        if isinstance(price, (int, float)):
            any_prices = True
            total += price * qty

        out.append(f"• {i}) {chosen['product_name']} {price_str} x{qty}")

    if any_prices:
        out.append(f"Estimated retail total: ${total:.2f}")

    out.append("Does that sound right? (yes/no)")
    return "\n".join(out)


def next_unresolved_index(order: dict) -> Optional[int]:
    for i, line in enumerate(order["lines"]):
        if line["chosen"] is None:
            return i
    return None


def start_line_resolution(catalog: List[dict], order: dict, line_index: int):
    line = order["lines"][line_index]
    matches = best_matches(catalog, line["text"], limit=MATCH_LIMIT)
    if not matches:
        return None, None, None
    top = matches[0]
    return top, matches, line["text"]


def propose_top(top: dict) -> str:
    # Hide SKU; show price
    return f"I think you mean: {top['product_name']} {fmt_price(top['price'])}. Is that right? (yes/no/options)"


def show_list_help():
    print("Reply with 1-5, or type 'more', or 'search: <words>'")


# -------------------------
# Main CLI
# -------------------------
def main():
    load_dotenv()
    client = OpenAI()

    # Optional debug line - you can remove later
    print("OPENAI_API_KEY loaded:", bool(os.getenv("OPENAI_API_KEY")))

    catalog = load_catalog(CATALOG_PATH)
    print(f"✅ Loaded catalog items: {len(catalog)}")
    print("💄 MK Chat → SQLite (type quit / exit / q to stop)\n")

    last_customer: Optional[dict] = None

    pending_customer_confirm: Optional[PendingCustomerConfirm] = None
    pending_order_select_confirm_top: Optional[PendingOrderSelectConfirmTop] = None
    pending_order_select_from_list: Optional[PendingOrderSelectFromList] = None
    pending_order_confirm: Optional[PendingOrderConfirm] = None
    pending_order_edit_pick_line: Optional[PendingOrderEditPickLine] = None

    while True:
        user_text = input("> ").strip()

        if user_text.lower() in ("quit", "exit", "q"):
            break

        # -------------------------
        # CUSTOMER CONFIRMATION
        # -------------------------
        if pending_customer_confirm:
            if yes(user_text):
                customer = pending_customer_confirm.customer
                job_id = insert_job("NEW_CUSTOMER", customer)
                last_customer = customer
                print(f"✅ Saved. Queued NEW_CUSTOMER job_id={job_id} for {customer['First Name']} {customer['Last Name']}")
                pending_customer_confirm = None
                continue

            if no(user_text):
                print("No problem — paste the corrected customer info and I’ll try again.")
                pending_customer_confirm = None
                continue

            print("Please reply yes or no.")
            continue

        # -------------------------
        # ORDER EDIT: PICK WHICH LINE TO CHANGE
        # -------------------------
        if pending_order_edit_pick_line:
            order = pending_order_edit_pick_line.order
            if user_text.strip().lower() in ("cancel", "stop"):
                print("Okay — canceled that order draft.")
                pending_order_edit_pick_line = None
                continue

            if user_text.isdigit():
                idx = int(user_text)
                if 1 <= idx <= len(order["lines"]):
                    line_index = idx - 1
                    top, matches, _text = start_line_resolution(catalog, order, line_index)
                    if not matches:
                        print("I couldn't find matches for that item. Try rephrasing it.")
                        continue

                    print(propose_top(top))
                    pending_order_select_confirm_top = PendingOrderSelectConfirmTop(order, line_index, top, matches)
                    pending_order_edit_pick_line = None
                    continue

            print("Reply with the line number you want to change (example: 1), or type 'cancel'.")
            continue

        # -------------------------
        # ORDER LINE: CONFIRM TOP GUESS (no list shown)
        # -------------------------
        if pending_order_select_confirm_top:
            order = pending_order_select_confirm_top.order
            line_index = pending_order_select_confirm_top.line_index
            top = pending_order_select_confirm_top.top
            matches = pending_order_select_confirm_top.matches

            if yes(user_text):
                order["lines"][line_index]["chosen"] = top
                pending_order_select_confirm_top = None

                while True:
                    nxt = next_unresolved_index(order)
                    if nxt is None:
                        pending_order_confirm = PendingOrderConfirm(order)
                        print(format_order_confirm(order))
                        break

                    picked, _m = auto_pick_match(catalog, order["lines"][nxt]["text"])
                    if picked:
                        order["lines"][nxt]["chosen"] = picked
                        continue

                    top2, matches2, _text2 = start_line_resolution(catalog, order, nxt)
                    if not matches2:
                        print("I couldn’t find a close match for one item. Try rephrasing it.")
                        break

                    print(propose_top(top2))
                    pending_order_select_confirm_top = PendingOrderSelectConfirmTop(order, nxt, top2, matches2)
                    break

                continue

            if no(user_text) or wants_options(user_text):
                print("Got it — here are the closest matches:")
                print_matches(matches, offset=0, page_size=PAGE_SIZE)
                show_list_help()
                pending_order_select_from_list = PendingOrderSelectFromList(
                    order=order,
                    line_index=line_index,
                    matches=matches,
                    offset=0,
                    base_query=order["lines"][line_index]["text"],
                )
                pending_order_select_confirm_top = None
                continue

            print("Please reply yes, no, or options.")
            continue

        # -------------------------
        # ORDER LINE: CHOOSE FROM LIST (paged + search)
        # -------------------------
        if pending_order_select_from_list:
            order = pending_order_select_from_list.order
            matches = pending_order_select_from_list.matches
            line_index = pending_order_select_from_list.line_index

            t = user_text.strip()

            # paging
            if t.lower() == "more":
                pending_order_select_from_list.offset += PAGE_SIZE
                if pending_order_select_from_list.offset >= len(matches):
                    pending_order_select_from_list.offset = 0
                print_matches(matches, pending_order_select_from_list.offset, PAGE_SIZE)
                show_list_help()
                continue

            # explicit re-search
            if t.lower().startswith("search:"):
                new_q = t.split(":", 1)[1].strip()
                if not new_q:
                    new_q = pending_order_select_from_list.base_query

                new_matches = best_matches(catalog, new_q, limit=MATCH_LIMIT)
                if not new_matches:
                    print("No matches found. Try a different search phrase (example: search: 4-in-1 cleanser).")
                    continue

                pending_order_select_from_list.matches = new_matches
                pending_order_select_from_list.offset = 0
                print("Here are the closest matches:")
                print_matches(new_matches, 0, PAGE_SIZE)
                show_list_help()
                continue

            # choose 1-5 within current page
            picked = None
            if t.isdigit():
                i = int(t)
                if 1 <= i <= PAGE_SIZE:
                    absolute_index = pending_order_select_from_list.offset + (i - 1)
                    if 0 <= absolute_index < len(matches):
                        picked = matches[absolute_index]
            else:
                # allow direct SKU paste (still supported even though not shown)
                sku_try = re.sub(r"\s+", "", t)
                for m in matches:
                    if m["sku"] == sku_try:
                        picked = m
                        break

            if not picked:
                print("⚠️ Choose 1-5, or type 'more', or 'search: <words>'.")
                print_matches(matches, pending_order_select_from_list.offset, PAGE_SIZE)
                show_list_help()
                continue

            order["lines"][line_index]["chosen"] = picked
            pending_order_select_from_list = None

            # continue resolving remaining items
            while True:
                nxt = next_unresolved_index(order)
                if nxt is None:
                    pending_order_confirm = PendingOrderConfirm(order)
                    print(format_order_confirm(order))
                    break

                picked2, _m2 = auto_pick_match(catalog, order["lines"][nxt]["text"])
                if picked2:
                    order["lines"][nxt]["chosen"] = picked2
                    continue

                top2, matches2, _text2 = start_line_resolution(catalog, order, nxt)
                if not matches2:
                    print("I couldn’t find a close match for one item. Try rephrasing it.")
                    break

                print(propose_top(top2))
                pending_order_select_confirm_top = PendingOrderSelectConfirmTop(order, nxt, top2, matches2)
                break

            continue

        # -------------------------
        # ORDER CONFIRMATION (final)
        # -------------------------
        if pending_order_confirm:
            order = pending_order_confirm.order
            if yes(user_text):
                cust_first = order["customer"]["First Name"]
                cust_last = order["customer"]["Last Name"]

                total_rows = 0
                for line in order["lines"]:
                    sku = line["chosen"]["sku"]  # store SKU internally
                    qty = int(line["qty"])
                    for _ in range(max(1, qty)):
                        insert_job("NEW_ORDER_ROW", {"First Name": cust_first, "Last Name": cust_last, "SKU": sku})
                        total_rows += 1

                print(f"✅ Saved. Queued {total_rows} order row(s) for {cust_first} {cust_last}.")
                last_customer = {"First Name": cust_first, "Last Name": cust_last}
                pending_order_confirm = None
                continue

            if no(user_text):
                print("Okay — which line number do you want to change? (example: 1)  (or type 'cancel')")
                pending_order_edit_pick_line = PendingOrderEditPickLine(order)
                pending_order_confirm = None
                continue

            print("Please reply yes or no.")
            continue

        # -------------------------
        # NORMAL PARSE
        # -------------------------
        try:
            parsed = parse_with_openai(client, user_text, last_customer)
        except Exception as e:
            print(f"❌ Parse error: {e}")
            continue

        # -------------------------
        # NEW CUSTOMER -> confirm then commit
        # -------------------------
        if parsed.get("type") == "customer":
            customer = parsed.get("customer") or {}
            customer["Phone"] = normalize_phone(customer.get("Phone", ""))

            pending_customer_confirm = PendingCustomerConfirm(customer)
            print(format_customer_confirm(customer))
            continue

        # -------------------------
        # ORDER -> resolve, hide list unless needed
        # -------------------------
        if parsed.get("type") == "order":
            order = parsed.get("order") or {}
            cust_first = (order.get("customer_first") or "").strip()
            cust_last = (order.get("customer_last") or "").strip()

            if (not cust_first or not cust_last) and last_customer:
                cust_first = last_customer.get("First Name", "").strip()
                cust_last = last_customer.get("Last Name", "").strip()

            if not cust_first or not cust_last:
                print("❓ Who is this order for? Please provide first and last name.")
                continue

            items = order.get("items") or []
            if not items:
                print("❓ What items should I add to the order?")
                continue

            order_draft = make_order_draft(cust_first, cust_last, items)
            if not order_draft["lines"]:
                print("❓ I didn’t catch any items. Try again.")
                continue

            # Try to auto-resolve as much as possible
            for line in order_draft["lines"]:
                picked, _matches = auto_pick_match(catalog, line["text"])
                if picked:
                    line["chosen"] = picked

            nxt = next_unresolved_index(order_draft)
            if nxt is not None:
                top, matches, _text = start_line_resolution(catalog, order_draft, nxt)
                if not matches:
                    print("I couldn’t find a close match for that item. Try rephrasing it.")
                    continue

                print(propose_top(top))
                pending_order_select_confirm_top = PendingOrderSelectConfirmTop(order_draft, nxt, top, matches)
                continue

            # Fully resolved -> final confirmation
            pending_order_confirm = PendingOrderConfirm(order_draft)
            print(format_order_confirm(order_draft))
            continue

        print("⚠️ I couldn't tell if that was a new customer or an order. Try rephrasing.")


if __name__ == "__main__":
    main()
