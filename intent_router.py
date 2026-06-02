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
    "recent_orders",
    "customer_spend",
    "leaderboard",
    "lapsed_customers",
    "new_customer",
    "new_order",
    "order_add",
    "order_remove",
    "product_lookup",
    "top_sellers",
    "unit_query",
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
    if lowered in ("app", "install app", "install", "the app", "app help", "help app") or any(t in lowered for t in (
        "help with app", "app help", "help app", "install app", "add to home", "home screen",
        "add the app", "download the app", "make the app", "get the app",
        "add to my phone", "save to phone", "put on my phone",
    )):
        return IntentResult(intent="app_help", confidence=1.0, raw_text=msg)

    # cancel
    if lowered in ("cancel", "stop", "nevermind", "never mind"):
        return IntentResult(intent="cancel", confidence=1.0, raw_text=msg)

    # unit_query — activity status code pattern (i3, t6, "who is i3", "show t6", etc.)
    # Must run early — bare codes like "i3" are only 2 chars and skip the OpenAI fallback
    if re.search(r'\b[aAiItTnN][1-7]\b', msg):
        return IntentResult(intent="unit_query", confidence=0.95, raw_text=msg)

    # unit_query — questions about the consultant's team/unit members
    # Must come before customer_info and lapsed_customers to avoid misrouting
    _unit_triggers = (
        "my team", "my unit", "my consultants", "my downline",
        "team member", "unit member",
        "great start", "star consultant", "star tracking",
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
    )
    if any(t in lowered for t in _unit_triggers):
        return IntentResult(intent="unit_query", confidence=0.95, raw_text=msg)

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
    # Pattern 2: "[city] customers" reverse order — require plural, exclude state-adjectives
    # Allow multi-word cities starting with "new" (New York, New Orleans, etc.)
    _CITY_ADJECTIVES = {"active", "inactive", "lapsed", "top", "best", "recent", "other",
                        "show", "find", "list", "get", "all", "any", "some"}
    _city_m2 = re.match(r"^(?:my\s+)?([A-Za-z][A-Za-z\s.'-]+?)\s+customers\b", lowered)
    if _city_m2:
        _city = _city_m2.group(1).strip()
        _first_word = _city.lower().split()[0]
        _is_adjective = _first_word in _CITY_ADJECTIVES
        _is_bare_new = _city.lower() == "new"  # "new customers" alone, not "New York"
        if not _is_adjective and not _is_bare_new:
            return IntentResult(intent="customers_by_city", confidence=0.95,
                                slots={"city": _city.title()}, raw_text=msg)

    # "new order for X" or "order for X" → new_order (must check before new_customer)
    if re.match(r'^(new\s+)?order\s+for\b', lowered):
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
        "- recent_orders\n"
        "- customer_spend\n"
        "- leaderboard\n"
        "- lapsed_customers\n"
        "- new_customer\n"
        "- new_order\n"
        "- order_add\n"
        "- order_remove\n"
        "- product_lookup\n"
        "- unit_query\n"
        "- unknown\n\n"
        "Return JSON like:\n"
        '{"intent":"customer_info","confidence":0.92}\n\n'
        "Rules:\n"
        "- Choose exactly one allowed intent.\n"
        "- If unsure, return unknown.\n"
        "- If the user is asking about customer details, use customer_info.\n"
        "- If the user is asking for customers in or from a specific city or location, use customers_by_city.\n"
        "- If the user is asking what someone ordered, use recent_orders.\n"
        "- If the user is asking how much someone spent, use customer_spend.\n"
        "- If the user is asking for top customers / PCP / who spent the most, use leaderboard.\n"
        "- If the user is asking who hasn't ordered recently or in a given timeframe, use lapsed_customers.\n"
        "- If the user is creating a customer, use new_customer.\n"
        "- If the user is creating an order, use new_order.\n"
        "- If the user is adding an item to an existing order, use order_add.\n"
        "- If the user is removing an item from an existing order, use order_remove.\n"
        "- If the user is asking for the price or cost of a Mary Kay product (with no customer or order context), use product_lookup.\n"
        "- If the user is asking what products they sell the most, their top sellers, or best selling items, use top_sellers.\n"
        "- If the user is asking about their team members, unit consultants, who has MyShop set up, Great Start bundles, Star Consultant progress, or any question about their downline, use unit_query.\n"
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