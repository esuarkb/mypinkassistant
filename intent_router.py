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
    "cancel",
    "customer_info",
    "recent_orders",
    "customer_spend",
    "leaderboard",
    "new_customer",
    "new_order",
    "order_add",
    "order_remove",
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
    lowered = msg.lower()

    if not msg:
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)

    # cancel
    if lowered in ("cancel", "stop", "nevermind", "never mind"):
        return IntentResult(intent="cancel", confidence=1.0, raw_text=msg)

    # leaderboard
    if (
        "leaderboard" in lowered
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
        "- recent_orders\n"
        "- customer_spend\n"
        "- leaderboard\n"
        "- new_customer\n"
        "- new_order\n"
        "- order_add\n"
        "- order_remove\n"
        "- unknown\n\n"
        "Return JSON like:\n"
        '{"intent":"customer_info","confidence":0.92}\n\n'
        "Rules:\n"
        "- Choose exactly one allowed intent.\n"
        "- If unsure, return unknown.\n"
        "- If the user is asking about customer details, use customer_info.\n"
        "- If the user is asking what someone ordered, use recent_orders.\n"
        "- If the user is asking how much someone spent, use customer_spend.\n"
        "- If the user is asking for top customers / PCP / who spent the most, use leaderboard.\n"
        "- If the user is creating a customer, use new_customer.\n"
        "- If the user is creating an order, use new_order.\n"
        "- If the user is adding an item to an existing order, use order_add.\n"
        "- If the user is removing an item from an existing order, use order_remove.\n"
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