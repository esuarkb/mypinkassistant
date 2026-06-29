from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from openai import OpenAI
import json

@dataclass
class IntentResult:
    intent: str
    confidence: float = 0.0
    slots: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


SUPPORTED_INTENTS = {
    "app_help",
    "chat_help",
    "cancel",
    "customer_info",
    "customers_by_city",
    "data_query",
    "recent_orders",
    "customer_spend",
    "leaderboard",
    "lapsed_customers",
    "edit_request",
    "new_customer",
    "new_order",
    "order_add",
    "order_remove",
    "product_lookup",
    "top_sellers",
    "unit_query",
    "car_program",
    "unknown",
}

MODEL = "gpt-4.1-mini"

load_dotenv()
_client = OpenAI()

def should_use_openai_intent_fallback(message: str) -> bool:
    msg = (message or "").strip()
    lowered = msg.lower()

    if not msg:
        return False

    # Never spend an API call on tiny / obvious reply tokens
    if lowered.isdigit():
        return False

    if lowered in ("y", "yes", "yeah", "yep", "ok", "okay", "n", "no", "nope", "nah"):
        return False

    # Too short to be worth an intent call
    if len(msg) < 4:
        return False

    # Must contain at least one letter
    if not re.search(r"[a-zA-Z]", msg):
        return False

    return True

def parse_intent(message: str, state: Optional[dict] = None) -> IntentResult:
    msg = (message or "").strip()
    msg = msg.replace('’', "'").replace('‘', "'")  # normalize iOS curly apostrophes
    lowered = msg.lower()

    if not msg:
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)

    # chat help — what can I do / commands list
    if lowered in ("help", "commands", "what can you do", "what can i do") or any(t in lowered for t in (
        "what can you do", "what can i ask", "what can i say", "how do i use",
        "show me what you can do", "list of commands", "what do you do",
    )):
        return IntentResult(intent="chat_help", confidence=1.0, raw_text=msg)

    # app installation help
    _app_word = bool(re.search(r'\bapp\b', lowered))
    _app_context = any(t in lowered for t in ("phone", "home screen", "home scrn", "ipad", "tablet", "device", "install", "download", "add to home"))
    if lowered in ("app", "install", "the app", "app help", "help app") or _app_context or (_app_word and any(t in lowered for t in ("add", "save", "put", "get", "help", "screen", "phone", "install", "download"))):
        return IntentResult(intent="app_help", confidence=1.0, raw_text=msg)

    # cancel
    if lowered in ("cancel", "stop", "nevermind", "never mind", "start over", "startover"):
        return IntentResult(intent="cancel", confidence=1.0, raw_text=msg)

    # unit_query — activity status code pattern (i3, t6, "who is i3", "show t6", etc.)
    # Must run early — bare codes like "i3" are only 2 chars and skip the OpenAI fallback
    if re.search(r'\b[aAiItTnN]\s?[1-7]\b', msg):
        return IntentResult(intent="unit_query", confidence=0.95, raw_text=msg)

    # unit_query — questions about the consultant's team/unit members
    # Must come before customer_info and lapsed_customers to avoid misrouting
    _unit_triggers = (
        "my team", "my unit", "my consultants", "my downline",
        "my personal team", "personal team", "my personal recruits", "personal recruits",
        "team member", "unit member",
        "great start", "star consultant", "star tracking", "star status",
        "myshop", "my shop",
        "who is inactive", "who are inactive", "inactive consultant",
        "who is active", "who are active", "active consultant",
        "who is on track", "who are on track",
        "rise and radiate", "rise & radiate",
        "who needs", "who still needs",
        "who hasn't set up", "who haven't set up",
        "activity status", "career level", "consultant number",
        "new consultant", "new consultants",
        "who is terminating", "terminating consultant",
        "power of pink", "diq", "red jacket",
        "rise and radiate", "rise + radiate", "rise radiate", "radiate",
        "seminar", "registered for", "registration", "who is registered",
        "who has registered", "who signed up",
        "hasn't hit star", "haven't hit star", "hasn't made star", "haven't made star",
        "what consultants", "which consultants", "consultants have ordered", "consultants ordered",
        "consultants who ordered", "consultants who have ordered", "consultants in my unit",
        "who in my unit", "ordered this month", "ordered last month",
    )
    if any(t in lowered for t in _unit_triggers):
        return IntentResult(intent="unit_query", confidence=0.95, raw_text=msg)

    # car program questions (director-only feature)
    # Only use terms that are unambiguous — avoid "how close to" / "production" alone
    # since those also appear in star/great-start unit_query phrases (which run earlier)
    _car_triggers = (
        "car program", "career car", "car qualification", "car award",
        "premier club", "grand achiever", "cadillac",
        "co-pay", "copay", "co pay",
        "car maintenance", "car qualify", "car qualifying",
        "car production", "car data",
        "earn a car", "get a car", "earn the car",
    )
    if any(t in lowered for t in _car_triggers):
        return IntentResult(intent="car_program", confidence=0.95, raw_text=msg)

    # Star Consultant level names (Ruby, Diamond, Emerald, Pearl) in a unit context
    _STAR_LEVELS = ("ruby", "diamond", "emerald", "pearl")
    if any(level in lowered for level in _STAR_LEVELS):
        _star_context = ("consultant", "star", "who", "show", "made", "hit",
                         "at", "is", "are", "earned", "reached", "level", "status", "close")
        if any(t in lowered for t in _star_context):
            return IntentResult(intent="unit_query", confidence=0.9, raw_text=msg)

    # lapsed customers
    _lapsed_triggers = (
        "haven't ordered", "has not ordered", "hasn't ordered", "have not ordered",
        "not ordered", "gone quiet", "lapsed", "haven't heard from", "hasn't bought",
        "haven't bought", "not buying", "not ordering", "who hasn't", "who haven't",
    )
    if any(t in lowered for t in _lapsed_triggers):
        return IntentResult(intent="lapsed_customers", confidence=0.95, raw_text=msg)

    # leaderboard
    if (
        "leaderboard" in lowered
        or "vip" in lowered
        or "spent the most" in lowered
        or "spend the most" in lowered
        or "ordered the most" in lowered
        or "order the most" in lowered
        or "bought the most" in lowered
        or "buy the most" in lowered
        or "pcp" in lowered
        or ("top" in lowered and "customer" in lowered)
    ):
        return IntentResult(intent="leaderboard", confidence=0.95, raw_text=msg)

    # Per-customer possessive order history ("Jeannie's orders in 2024") must be caught
    # before the broad "orders in " data_query trigger grabs it.
    if re.search(r"\b\w+'s orders\b", lowered):
        return IntentResult(intent="recent_orders", confidence=0.92, raw_text=msg)

    # data_query — cross-customer/aggregate queries; must run before recent_orders
    # so "who ordered in May" doesn't get stolen by the broad recent_orders keyword match
    _data_query_triggers = (
        "who ordered in",
        "who ordered the",
        "who ordered a ",
        "who has ordered",
        "how many orders",
        "total orders",
        "total revenue",
        "total sales",
        "how many customers",
        "how much revenue",
        "how much did i make",
        "how much have i made",
        "orders in ",
        "orders last ",
        "orders this ",
        # customers who have never placed any order
        "never ordered",
        "never actually ordered",
        "never purchased",
        "never bought",
        "never placed an order",
        # customers who have placed exactly one order
        "only ordered once",
        "ordered only once",
        "ordered just once",
        "ordered exactly once",
        "only bought once",
        "only purchased once",
        "only placed one order",
        # online / myshop order queries
        "online order",
        "myshop order",
        "my shop order",
        "online orders",
        "myshop orders",
        "most recent online",
        "latest online",
        "recent online",
        "online sale",
        "online sales",
    )
    if any(t in lowered for t in _data_query_triggers):
        return IntentResult(intent="data_query", confidence=0.95, raw_text=msg)
    # "who ordered/buys/purchases X" — cross-customer product query
    if re.search(r'\bwho\s+(ordered|buys|buy|purchases|purchase|gets|orders)\b', lowered):
        return IntentResult(intent="data_query", confidence=0.95, raw_text=msg)

    # recent orders
    if (
        ("order" in lowered or "orders" in lowered or "ordered" in lowered)
        and any(
            k in lowered
            for k in (
                "last", "recent", "show", "lookup", "history",
                "what did", "what has", "what have",
                "ordered", "buy", "bought", "purchase", "purchased",
            )
        )
    ):
        return IntentResult(intent="recent_orders", confidence=0.9, raw_text=msg)

    # customer spend
    if (
        ("spent" in lowered or "spend" in lowered or "total" in lowered)
        and any(k in lowered for k in ("how much", "total", "spent", "spend"))
        and not ("add" in lowered and "order" in lowered)
    ):
        return IntentResult(intent="customer_spend", confidence=0.9, raw_text=msg)

    # top sellers — must come before customer_info since "what's" triggers that rule
    _top_seller_triggers = (
        "top seller", "top selling", "best seller", "best selling",
        "most popular", "sell the most", "sells the most", "sold the most",
        "most sold", "what do i sell", "what am i selling", "what's my top",
        "what is my top", "my best selling", "my top selling",
    )
    if any(t in lowered for t in _top_seller_triggers):
        timeframe = None
        if any(t in lowered for t in ("this month", "last month", "monthly")):
            timeframe = "month"
        elif any(t in lowered for t in ("this quarter", "last quarter", "quarterly")):
            timeframe = "quarter"
        elif any(t in lowered for t in ("this year", "last year", "yearly", "annually")):
            timeframe = "year"
        elif any(t in lowered for t in ("all time", "all-time", "ever", "overall", "since")):
            timeframe = "all_time"
        return IntentResult(intent="top_sellers", confidence=0.95,
                            slots={"timeframe": timeframe}, raw_text=msg)

    # customer info
    looks_like_possessive_info = bool(
        re.search(r"\b\w+'\s*s?\s*(info|email|phone|address|birthday)\b", lowered)
    )
    looks_like_name_info = bool(
        re.search(r"\b\w+\s+(info|email|phone|address|birthday)\b", lowered)
        or re.search(r"\b(info|email|phone|address|birthday)\s+for\s+[a-z][a-z'-]+(?:\s+[a-z][a-z'-]+)?\s*$", lowered)
    )
    # Single word (or two words) that looks like a name — treat as lookup
    # e.g. "ruby" or "ruby perez" with no other context
    _words = msg.strip().split()
    looks_like_bare_name = (
        1 <= len(_words) <= 2
        and all(re.match(r"^[a-zA-Z'-]+$", w) for w in _words)
        and not any(t in lowered for t in ("new", "order", "add", "cancel", "tag", "note"))
    )

    # customers by city — check before customer_info to avoid bare-name collision
    # Pattern 1: "customers in/from [city]" — unambiguous, no exclusions needed
    # Skip if this looks like a new customer entry
    _is_new_customer_entry = bool(re.match(r"^(new|add|create)\s+customer", lowered))
    _city_m1 = None if _is_new_customer_entry else re.search(r"\bcustomers?\s+(?:in|from)\s+([A-Za-z][A-Za-z\s.'-]+?)(?:\s*\??\s*$)", lowered)
    if _city_m1:
        return IntentResult(intent="customers_by_city", confidence=0.95,
                            slots={"city": _city_m1.group(1).strip().title()}, raw_text=msg)
    # Pattern 3: "customers who live/living/lives in [city]"
    _city_m3 = re.search(r"\bliv(?:e|es|ing)\s+in\s+([A-Za-z][A-Za-z\s.',\-]+?)(?:\s*\??\s*$)", lowered) if "customer" in lowered and not _is_new_customer_entry else None
    if _city_m3:
        return IntentResult(intent="customers_by_city", confidence=0.95,
                            slots={"city": _city_m3.group(1).strip().title()}, raw_text=msg)
    # Pattern 2: "[city] customers" reverse order — require plural, exclude state-adjectives
    # Allow multi-word cities starting with "new" (New York, New Orleans, etc.)
    _CITY_ADJECTIVES = {"active", "inactive", "lapsed", "top", "best", "recent", "other",
                        "show", "find", "list", "get", "all", "any", "some",
                        "who", "are", "have", "has", "which"}
    _city_m2 = re.match(r"^(?:my\s+)?([A-Za-z][A-Za-z\s.'-]+?)\s+customers\b", lowered)
    if _city_m2:
        _city = _city_m2.group(1).strip()
        _first_word = _city.lower().split()[0]
        _is_adjective = _first_word in _CITY_ADJECTIVES
        _is_bare_new = _city.lower() == "new"  # "new customers" alone, not "New York"
        if not _is_adjective and not _is_bare_new:
            return IntentResult(intent="customers_by_city", confidence=0.95,
                                slots={"city": _city.title()}, raw_text=msg)

    # "add this address/phone/email/birthday to [name]" → edit_request
    # Must come before the general edit_request and customer_info checks
    if re.search(r'\badd\s+(?:this\s+)?(address|phone|email|birthday|birthdate)\b', lowered):
        return IntentResult(intent="edit_request", confidence=0.95, raw_text=msg)

    # edit_request — someone trying to update customer info or an order
    # Must come before customer_info; exclude "set up/new" to avoid catching new_customer phrases
    _has_edit_verb  = bool(re.search(r"\b(update|change|edit|fix|correct|set|modify)\b", lowered))
    _has_edit_field = bool(re.search(r"\b(address|phone|email|birthday|birthdate|name|order)\b", lowered))
    _is_setup_phrase = bool(re.search(r"\b(set\s+up|new|add|an\s+order)\b", lowered))
    if _has_edit_verb and _has_edit_field and not _is_setup_phrase:
        return IntentResult(intent="edit_request", confidence=0.95, raw_text=msg)

    # "ingredients in X" → always product_lookup (must come before customer_info catch-all)
    if re.search(r"\bingredients?\b", lowered):
        return IntentResult(intent="product_lookup", confidence=0.95, raw_text=msg)

    # "new/add/place/start order for X" or bare "order for X" → new_order (must check before new_customer)
    if re.search(r'\badd\s+an?\s+order\b', lowered):
        return IntentResult(intent="new_order", confidence=0.95, raw_text=msg)
    if re.match(r'^(new\s+|add\s+|place\s+|start\s+(?:an?\s+)?)?order\s+for\b', lowered):
        return IntentResult(intent="new_order", confidence=0.95, raw_text=msg)

    # "create X" without "order" → new customer (e.g. "create nichole giveaway")
    if lowered.startswith("create ") and "order" not in lowered:
        return IntentResult(intent="new_customer", confidence=0.9, raw_text=msg)

    if (
        any(t in lowered for t in ("what's", "whats", "what is", "lookup", "show", "info on", "information for"))
        or looks_like_possessive_info
        or looks_like_name_info
        or looks_like_bare_name
    ) and "order" not in lowered:
        return IntentResult(intent="customer_info", confidence=0.85, raw_text=msg)

    # fallback to OpenAI only if the message is worth checking
    if not should_use_openai_intent_fallback(msg):
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)

    return parse_intent_with_openai(msg, state)

def parse_intent_with_openai(message: str, state: Optional[dict] = None) -> IntentResult:
    msg = (message or "").strip()
    if not msg:
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)

    last_ref_name = ""
    if state:
        last_ref_name = (state.get("last_ref_customer_name") or "").strip()

    system = (
        "You classify user messages for a Mary Kay CRM assistant.\n"
        "Return ONLY valid JSON.\n"
        "Allowed intents are:\n"
        "- cancel\n"
        "- customer_info\n"
        "- customers_by_city\n"
        "- data_query\n"
        "- recent_orders\n"
        "- customer_spend\n"
        "- leaderboard\n"
        "- lapsed_customers\n"
        "- new_customer\n"
        "- new_order\n"
        "- order_add\n"
        "- order_remove\n"
        "- product_lookup\n"
        "- top_sellers\n"
        "- unit_query\n"
        "- unknown\n\n"
        "Return JSON like:\n"
        '{"intent":"customer_info","confidence":0.92}\n\n'
        "Rules:\n"
        "- Choose exactly one allowed intent.\n"
        "- If unsure, return unknown.\n"
        "- If the user is asking about customer details, use customer_info.\n"
        "- If the user is asking for customers in or from a specific city or location, use customers_by_city.\n"
        "- If the user is asking what someone (a specific named person) ordered, use recent_orders.\n"
        "- If the user is asking how much a specific person spent, use customer_spend.\n"
        "- If the user is asking for top customers / PCP / who spent the most, use leaderboard.\n"
        "- If the user is asking who hasn't ordered recently or in a given timeframe, use lapsed_customers.\n"
        "- If the user is creating a customer, use new_customer.\n"
        "- If the user is creating an order, use new_order.\n"
        "- If the user is adding an item to an existing order, use order_add.\n"
        "- If the user is removing an item from an existing order, use order_remove.\n"
        "- If the user is asking for the price or cost of a Mary Kay product (with no customer or order context), use product_lookup.\n"
        "- If the user is asking what products they sell the most, their top sellers, or best selling items, use top_sellers.\n"
        "- If the user is asking about their team members, unit consultants, who has MyShop set up, Great Start bundles, Star Consultant progress, star levels (Ruby, Diamond, Emerald, Pearl), or any question about their downline, use unit_query.\n"
        "- If the user is asking an aggregate or cross-customer question about orders or customers "
        "(e.g., who ordered in a given month or year, how many orders in a timeframe, "
        "total revenue or sales, who ordered a specific product, customers in a specific state, "
        "how many customers they have), use data_query.\n"
    )

    user = f"Message: {msg}\nLast referenced customer: {last_ref_name or '(none)'}"

    try:
        resp = _client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=30,
        )

        txt = ""
        try:
            parts = []
            for out in (resp.output or []):
                for c in (getattr(out, "content", None) or []):
                    t = getattr(c, "text", None)
                    if t:
                        parts.append(t)
            txt = "\n".join(parts).strip()
        except Exception:
            try:
                txt = (resp.output[0].content[0].text or "").strip()
            except Exception:
                txt = ""

        data = {}
        try:
            data = json.loads(txt)
        except Exception:
            return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)

        intent = (data.get("intent") or "unknown").strip()
        confidence = float(data.get("confidence") or 0.0)

        if intent not in SUPPORTED_INTENTS:
            intent = "unknown"

        return IntentResult(
            intent=intent,
            confidence=confidence,
            raw_text=msg,
        )

    except Exception:
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)