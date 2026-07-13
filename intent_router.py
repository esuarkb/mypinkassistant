"""
intent_router.py — THE single source of truth for message routing.

Every consultant chat message is classified here, in one documented order.
mk_chat_core.MKChatEngine.handle_message calls route() and dispatches on the
returned intent; it makes no routing decisions of its own.

PLAIN-ENGLISH OVERVIEW (start here)
===================================
When a consultant types a message, exactly three things happen:

    1. intent_router.route(message, state, catalog) decides WHICH feature
       should answer, and returns an IntentResult:
         .intent   — the feature's name, e.g. "inventory_count"
         .slots    — parsed details, e.g. {"product_text": "charcoal mask"}
         .raw_text — the cleaned-up message text handlers should use
    2. handle_message writes one row to intent_logs (the analytics table).
    3. handle_message looks the intent up in its dispatch table
       (_INTENT_DISPATCH in mk_chat_core/engine.py) and runs that one
       handler method. Handlers only fetch data and build the reply — they
       never decide whether they should run. That decision was already made
       in step 1 (and by the interrupts_pending policy, see below).

So: if a message goes to the WRONG feature, fix it in THIS file.
If the RIGHT feature gives a wrong answer, fix its handler method in
mk_chat_core/engine.py.

TO ADD A NEW INTENT (recipe)
============================
Say you want a new chat feature "team_birthdays":
    1. Add an entry to INTENT_REGISTRY below:
         "team_birthdays": {"llm_allowed": False, "interrupts_pending": False,
                            "description": "..."}
       (llm_allowed=False means the OpenAI fallback never returns it — use
       False for anything a keyword/regex rule will always catch.
       interrupts_pending=False means it politely waits while the consultant
       is mid-flow — order confirm, picker, etc. Use False unless you have a
       reason; True is for utility commands like "look book".)
    2. Add a rule inside route() that returns
         _claim("team_birthdays", {...slots...})
       Put it at the right spot in the chain — rules higher up win. Read the
       precedence list below and the comments around each rule.
    3. In mk_chat_core/engine.py, add a handler method on MKChatEngine:
         def _intent_team_birthdays(self, ctx) -> Optional[ChatReply]:
             ...fetch data, return ChatReply(...)
       and wire it into the _INTENT_DISPATCH table at the bottom of the
       class:  "team_birthdays": "_intent_team_birthdays",
       (Copy any existing small handler, e.g. _intent_referral, as a
       template — the first lines unpack what you need from ctx.)
    4. Add cases to test_intent_golden.py (ROUTE_CASES for route() rules)
       and run:  python test_intent_golden.py
       It must pass before deploying. That's the whole process.

ROUTING PRECEDENCE (route() evaluates in exactly this order)
=============================================================
 1. Normalize        — strip, replace standalone 8-digit SKUs with product names
 2. Hard command     — "show all <product term>" (UI "+N more" tap)
 3. Classify         — parse_intent(): ordered keyword rules, then the OpenAI
                       fallback for messages nothing deterministic matched
 4. Override         — recent_orders phrasings that are really NEW order entry
 5. Hijack chain     — deterministic feature heuristics that claim the message
                       regardless of what step 3 said, in this order:
                       look book, bare-inventory-write guardrail, inventory
                       print, exact catalog name match, price query / bare
                       product message, inventory count / show / low stock /
                       threshold / write / help, delete customer, referral
                       link, edit-request redirect, PCP list
 6. Handler claims   — leaderboard, top sellers, then more text rules
                       interleaved exactly where their handlers sit in
                       mk_chat_core: birthday period lookup, lapsed customers
                       (with product-phrase override), customers by city,
                       product lookup, follow-ups, customer search by product
 7. Fallthrough      — the step-3/4 intent stands (recent_orders,
                       customer_info, data_query, new_order, unknown, ...);
                       handle_message dispatches it or lets the pending flow
                       or the normal LLM order/customer parse consume it

PENDING-FLOW INTERACTION
========================
Two layers decide what happens to a message while a pending flow (order
confirm, customer picker, ...) is active:
    1. route() applies each rule's pending guard exactly as the old inline
       code did: rules marked "not pending" below do not claim a message
       mid-flow, so the base intent (often from the LLM) flows through.
    2. The engine then consults the intent's interrupts_pending flag in
       INTENT_REGISTRY: True = the handler answers even mid-flow (look book,
       inventory commands, cancel, help); False = the handler yields and the
       pending flow consumes the message.
Both layers were copied 1:1 from the pre-consolidation behavior. To change
whether an intent can interrupt, flip its interrupts_pending flag AND check
the route() rule's guard — then golden suite + a mid-flow smoke test.

Regression gate: python test_intent_golden.py  (run before every deploy)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz, process
import json

@dataclass
class IntentResult:
    intent: str
    confidence: float = 0.0
    slots: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


# =====================================================================
# Intent registry — the ONE place intents are declared.
# SUPPORTED_INTENTS and the LLM prompt's allowed-intents list are both
# generated from this, so they can never drift apart again.
# llm_allowed: whether the OpenAI fallback may return this intent
# (deterministic-only intents are always claimed by rules before the
# LLM is consulted, so the LLM never needs their names).
# interrupts_pending: whether the ENGINE may run this intent's handler
# while a mid-conversation flow ("pending" state — order confirm,
# pickers, inventory confirms) is open. False = the handler yields and
# the pending flow consumes the message instead. This is the engine's
# dispatch policy; route() ALSO declines to claim many intents mid-flow
# (see the per-rule pending guards in route()), so an intent only truly
# interrupts when both layers allow it. Flags were copied 1:1 from the
# engine's old inline `if not pending` guards — change one only with a
# golden-suite run and a mid-flow smoke test.
# NOTE: registry order defines the order of the LLM prompt's allowed
# list — keep the llm_allowed entries in this order (prompt is pinned
# byte-identical to the pre-registry version).
# =====================================================================
INTENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    # --- LLM-allowed classification intents (order matters — see NOTE) ---
    "cancel":            {"llm_allowed": True,  "interrupts_pending": True,  "description": "cancel / start over"},  # handler itself defers when a delete-customer confirm is pending
    "customer_info":     {"llm_allowed": True,  "interrupts_pending": False, "description": "look up one customer's card (email, phone, address, birthday)"},
    "customers_by_city": {"llm_allowed": True,  "interrupts_pending": False, "description": "customers in/from a city or state"},
    "data_query":        {"llm_allowed": True,  "interrupts_pending": False, "description": "aggregate / cross-customer question (text-to-SQL)"},
    "recent_orders":     {"llm_allowed": True,  "interrupts_pending": False, "description": "a named customer's order history"},
    "customer_spend":    {"llm_allowed": True,  "interrupts_pending": False, "description": "how much a named customer spent"},
    "leaderboard":       {"llm_allowed": True,  "interrupts_pending": False, "description": "top customers / PCP / who spent the most"},
    "lapsed_customers":  {"llm_allowed": True,  "interrupts_pending": False, "description": "who hasn't ordered lately"},
    "new_customer":      {"llm_allowed": True,  "interrupts_pending": False, "description": "create a customer"},
    "new_order":         {"llm_allowed": True,  "interrupts_pending": False, "description": "create an order"},
    "order_add":         {"llm_allowed": True,  "interrupts_pending": False, "description": "add an item to the order being built"},
    "order_remove":      {"llm_allowed": True,  "interrupts_pending": False, "description": "remove an item from the order being built"},
    "product_lookup":    {"llm_allowed": True,  "interrupts_pending": True,  "description": "price/info for a catalog product"},  # source="intent" additionally requires no pending (guard inside the handler)
    "top_sellers":       {"llm_allowed": True,  "interrupts_pending": True,  "description": "consultant's best-selling products"},
    "unit_query":        {"llm_allowed": True,  "interrupts_pending": False, "description": "team/unit member question (director text-to-SQL)"},
    "unknown":           {"llm_allowed": True,  "interrupts_pending": False, "description": "could not classify"},
    # --- keyword-only classification intents ---
    "app_help":          {"llm_allowed": False, "interrupts_pending": True,  "description": "how to install / add the app to a device"},
    "chat_help":         {"llm_allowed": False, "interrupts_pending": True,  "description": "what can I say — chat cheat sheet"},
    "edit_request":      {"llm_allowed": False, "interrupts_pending": True,  "description": "customer info edit — redirected to MyCustomers"},
    "inventory":         {"llm_allowed": False, "interrupts_pending": False, "description": "generic inventory mention (always refined to a specific inventory_* intent by the hijack chain)"},
    "car_program":       {"llm_allowed": False, "interrupts_pending": False, "description": "career car / co-pay questions (director feature)"},
    # --- heuristic-claimed intents (hijack chain / handler-position rules) ---
    "show_all_products":     {"llm_allowed": False, "interrupts_pending": True,  "description": "'show all <term>' product list expansion (UI tap)"},  # answered before intent logging — special-cased in handle_message, not dispatched
    "look_book":             {"llm_allowed": False, "interrupts_pending": True,  "description": "current Look Book PDF link"},
    "inventory_guardrail":   {"llm_allowed": False, "interrupts_pending": True,  "description": "inventory-style write missing the word 'inventory' — coach the phrasing"},
    "inventory_print":       {"llm_allowed": False, "interrupts_pending": True,  "description": "inventory print / PDF report link"},
    "inventory_count":       {"llm_allowed": False, "interrupts_pending": True,  "description": "how many X do I have on hand"},
    "inventory_show":        {"llm_allowed": False, "interrupts_pending": True,  "description": "show the full inventory list"},
    "inventory_low_stock":   {"llm_allowed": False, "interrupts_pending": True,  "description": "what am I low on / need to reorder"},
    "inventory_threshold":   {"llm_allowed": False, "interrupts_pending": True,  "description": "set desired on-hand level (par/minimum)"},
    "inventory_write":       {"llm_allowed": False, "interrupts_pending": True,  "description": "add/remove/set inventory quantity"},
    "inventory_help":        {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking HOW the inventory feature works or how to use it (not performing an inventory action) — show the inventory cheat sheet"},  # llm_allowed since 2026-07-06 (feature-help long tail); also the hijack-chain fallback for inventory mentions with no parsed command
    "delete_customer":       {"llm_allowed": False, "interrupts_pending": True,  "description": "delete a customer (local only, confirm flow)"},  # route() never claims this mid-flow, so in practice it can't interrupt; True mirrors the old engine dispatch exactly
    "submitted_order_edit":  {"llm_allowed": False, "interrupts_pending": True,  "description": "add/remove against an already-submitted order — educate: change it in MyCustomers, syncs back"},
    "referral":              {"llm_allowed": False, "interrupts_pending": True,  "description": "consultant's referral link"},
    "pcp_list":              {"llm_allowed": False, "interrupts_pending": True,  "description": "PCP enrolled customer list"},
    "birthday_lookup":       {"llm_allowed": False, "interrupts_pending": True,  "description": "birthdays today/this week/this month/..."},
    "followup":              {"llm_allowed": False, "interrupts_pending": True,  "description": "2+2+2 follow-up cards"},
    "customers_by_product":  {"llm_allowed": False, "interrupts_pending": True,  "description": "customers who bought/use a product"},
    # --- feature-help bubbles (2026-07-06) — "how does X work" explanations;
    # deterministic gate in route() (_feature_help_intent) + LLM long tail ---
    "order_help":            {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking HOW ordering works or how to place/CDS an order (an explanation, not placing one)"},
    "followup_help":         {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking what follow-ups are or how they work (not asking to see their followup cards)"},
    "sync_help":             {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking how/when data syncs with MyCustomers or why data looks out of date"},
    "billing_help":          {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking about price, subscription, how to cancel, or the referral program"},
    "privacy_help":          {"llm_allowed": True,  "interrupts_pending": True,  "description": "asking whether their data is safe/private or what the AI can see"},
    "notes_educate":         {"llm_allowed": False, "interrupts_pending": False, "description": "'add a note to X' — notes aren't supported yet, redirect to MyCustomers"},
    "mycustomers_link":      {"llm_allowed": False, "interrupts_pending": True,  "description": "'link to mycustomers' — the clickable MyCustomers link"},
    "bulk_text_educate":     {"llm_allowed": False, "interrupts_pending": False, "description": "'text/remind several customers' — not supported, point at follow-up/lapsed lists' tap-to-text buttons"},
}

SUPPORTED_INTENTS = set(INTENT_REGISTRY)

_LLM_ALLOWED_INTENTS = [name for name, meta in INTENT_REGISTRY.items() if meta["llm_allowed"]]

# Model choice lives in llm_config.py — one place for the whole app.
from llm_config import OPENAI_MODEL as MODEL, model_kwargs  # noqa: F401

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


# =====================================================================
# Product matching (moved verbatim from mk_chat_core 2026-07-02;
# mk_chat_core re-imports best_matches for its handler bodies)
# =====================================================================
_SEARCH_STOP_WORDS = {"mary", "kay"}

# Query-side word-form fixes: consultants write these differently than the
# official catalog names, which breaks the whole-word pre-filter below.
# All harvested from production intent_logs (2026-07). Applied to the query
# only, so every search path (lookup, order lines, inventory) benefits.
_COMPOUND_WORD_FIXES = [
    (re.compile(r"\blipgloss\b"), "lip gloss"),
    (re.compile(r"\blipglosses\b"), "lip glosses"),
    (re.compile(r"\beyeshadow\b"), "eye shadow"),
    (re.compile(r"\beye liner\b"), "eyeliner"),
    (re.compile(r"\btime wise\b"), "timewise"),
    (re.compile(r"\bnight time\b"), "nighttime"),
    (re.compile(r"\bclearproof\b"), "clear proof"),
]

def best_matches(catalog: List[dict], query: str, limit: int = 5, min_score: int = 30,
                 prefilter_fallback: bool = True) -> List[dict]:
    q = (query or "").lower().strip()
    q = re.sub(r"\+", " ", q)  # treat + as a space so "ha+ceramide" splits correctly before pre-filter
    for pat, repl in _COMPOUND_WORD_FIXES:
        q = pat.sub(repl, q)
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
        filtered = [
            c for c in candidates
            if re.search(rf"\b(?:{pattern})\b", c["search_string"], re.IGNORECASE)
        ]
        # A typo in every significant word ("ha ceremide") zeroes the pool;
        # fall back to unfiltered fuzzy rather than returning no matches at all.
        # Callers deciding whether a message is about a product AT ALL (the
        # bare-message product_lookup claim in route()) must pass
        # prefilter_fallback=False: with the fallback, non-product words like
        # "yes" or half-typed customer names fuzz above 70 and would hijack
        # routing. Handlers already inside a product context keep the default.
        if filtered:
            candidates = filtered
        elif not prefilter_fallback:
            return []

    # Normalize conjunctions/symbols to a space so "berry and vanilla" scores the
    # same as "berry & vanilla", and "serum c plus e" matches "Serum C+E".
    def _norm_plus(s: str) -> str:
        s = re.sub(r"\bplus\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"\band\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"[+&]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    # Score the product name and each search_terms alias separately and keep
    # the best. Concatenating aliases into one string inflated scores for
    # unrelated queries (a "travel set" alias made every Go Set outrank the
    # one the consultant actually named). Rows without aliases score exactly
    # as before.
    texts: List[str] = []
    owners: List[int] = []
    for i, c in enumerate(candidates):
        variants = [c["product_name"]]
        raw_terms = (c.get("search_terms") or "").strip()
        if raw_terms:
            variants.extend(t.strip() for t in raw_terms.split("|") if t.strip())
        for v in variants:
            texts.append(_norm_plus(v))
            owners.append(i)

    q_for_score = _norm_plus(q)
    results = process.extract(q_for_score, texts, scorer=fuzz.WRatio, limit=None)

    best_by_owner: dict = {}
    for _text, score, ti in results:
        oi = owners[ti]
        if score > best_by_owner.get(oi, -1):
            best_by_owner[oi] = score

    # Exact-phrase override: a multi-word query that appears verbatim in a
    # product NAME names that product — it must outrank short search_terms
    # aliases ("hydrating cleanser" lost 82→90 to the bare "cleanser" alias on
    # Clear Proof; weed-garden 2026-07-09, regression of the 2026-07-04 alias
    # fix). Gated to ≥2 significant words so single-word queries ("cleanser")
    # keep the alias behavior that fix intended.
    if len([w for w in q_for_score.split() if len(w) >= 3]) >= 2:
        for _oi in best_by_owner:
            if q_for_score in _norm_plus(candidates[_oi]["product_name"]).lower():
                best_by_owner[_oi] = max(best_by_owner[_oi], 96)

    q_words = {w for w in re.split(r"\s+", q) if len(w) >= 3}

    matches: List[dict] = []
    for idx, score in best_by_owner.items():
        if score < min_score:
            continue
        c = candidates[idx]
        name_l = c["product_name"].lower()
        word_hits = sum(1 for w in q_words if re.search(rf"\b{re.escape(w)}\b", name_l))
        on_the_go = 1 if "the go set" in name_l else 0
        matches.append(
            {"sku": c["sku"], "product_name": c["product_name"], "price": c["price"],
             "previous_price": c.get("previous_price"), "score": score,
             "fact_sheet_url": c.get("fact_sheet_url", ""), "order_of_application_url": c.get("order_of_application_url", ""),
             "use_up_rate_months": c.get("use_up_rate_months", ""),
             "_hits": word_hits, "_otg": on_the_go,
             # Final tie-break: newest catalog row wins — re-released products
             # share a name across old/new SKUs and the current one should be
             # proposed (backlog item, built 2026-07-11). "" sorts last.
             "_added": c.get("date_added", "") or ""}
        )

    matches.sort(key=lambda m: (m["score"], m["_hits"], -m["_otg"], m["_added"]), reverse=True)
    matches = matches[:limit]
    for m in matches:
        del m["_hits"]
        del m["_otg"]
        del m["_added"]
    return matches


# =====================================================================
# Routing predicates & parsers (moved verbatim from mk_chat_core
# 2026-07-02; several are re-imported by handler bodies)
# =====================================================================
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


# "<name> ordered/wants/needs [:] <products>" is order ENTRY, not an order-history
# lookup — but the score-based heuristic below missed it two ways (weed-garden
# 2026-07-07, c39 fought this ~15x across 3 customers, repeated cancels): the verb
# check keyed on "ordered " with a trailing space, so "ordered:" scored 0, and
# single-item orders ("Ellie ordered makeup remover") never reached the 2-signal
# threshold. This strong-shape shortcut catches the active-verb statement form
# directly; the lookup guard keeps genuine history phrasings ("recent orders",
# "what did X order", "order history") in recent_orders.
_ORDER_ENTRY_SHAPE_RE = re.compile(
    r"^\s*(?:new\s+order\s+for\s+|order\s+for\s+)?"        # optional lead-in
    r"[a-z][\w.'-]*(?:\s+[a-z][\w.'-]*){0,3}?"             # subject / name, 1-4 tokens
    r"\s+(?:ordered|wants?|wanted|needs?|needed)\s*:?\s+"  # active order verb (+ optional colon)
    r"\S",                                                 # content follows the verb
    re.IGNORECASE,
)
_ORDER_LOOKUP_RE = re.compile(
    r"\b(recent\s+orders?|order\s+history|last\s+orders?|past\s+orders?|"
    r"previous\s+orders?|pending\s+orders?|how\s+many\s+orders?|orders?\s+for\b|"
    r"what\s+did\s+.*\border\b)\b",
    re.IGNORECASE,
)
# A real order-entry statement never opens with an interrogative — those are
# cross-customer/history lookups ("who last ordered X", "what was the last
# foundation ordered by Y", "which customers ordered Z"). Guards both the
# strong-shape shortcut and the score path below.
_ORDER_QUESTION_RE = re.compile(r"^\s*(?:who|what|which|whose|when|where|why|how)\b", re.IGNORECASE)


def _looks_like_new_order_entry(text: str) -> bool:
    t = (text or "").strip().lower()

    # Questions are lookups, not order entry — never flip them to new_order.
    if _ORDER_QUESTION_RE.match(t):
        return False

    # Strong shape: "<name> ordered/wants/needs <products>" as a statement (not a
    # history lookup). Covers single items and colon lists the scorer below missed.
    if _ORDER_ENTRY_SHAPE_RE.search(t) and not _ORDER_LOOKUP_RE.search(t):
        return True

    has_order_verb = any(x in t for x in ("order ", "ordered ", "wants ", "want ", "needs ", "need "))
    has_item_connector = any(x in t for x in (" and ", ","))
    has_quantity = bool(re.search(r"\b(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\b", t))
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


# "add a note to Meghan Froemke" / "note for X: ..." — notes aren't supported
# yet (notes_educate intent). Must yield when the message also carries real
# order signal, e.g. "Misty Cameron add a note, wants pink prism shimmer eye
# stick, barrier restore 1-1-3, foundation primer" — that's an order with
# "add a note" as filler, not a notes request. Reuses _looks_like_new_order_entry's
# scoring so the two guards stay in sync.
# "make" added 2026-07-11 — "Make a note Elspeth…" fell to the LLM and
# word-salad'd as a customer search (weed-garden 2026-07-10, c114).
_NOTE_PHRASE_RE = re.compile(r"\b(?:add|leave|put|write|make)\s+(?:a\s+)?note\b|\bnotes?\s+for\b", re.IGNORECASE)

def _looks_like_notes_request(text: str) -> bool:
    t = (text or "").strip()
    if not _NOTE_PHRASE_RE.search(t):
        return False
    # Yield to order parsing when the message also has REAL order signal — an
    # order verb or a comma/"and" item list ("Misty Cameron add a note, wants
    # pink prism shimmer eye stick, …" is an order with note-filler). Quantity+
    # product-hint alone isn't enough: "Make a note Elspeth Barnes light for
    # luminous 3-D foundation" scored as an order via the "3" in 3-D +
    # "foundation" and skipped the educate bubble (weed-garden 2026-07-10).
    t_l = t.lower()
    _has_order_verb = any(x in t_l for x in ("order ", "ordered ", "wants ", "want ", "needs ", "need "))
    _has_item_list = ("," in t_l) or (" and " in t_l)
    if _looks_like_new_order_entry(t) and (_has_order_verb or _has_item_list):
        return False
    return True


def _looks_like_full_customer_entry(text: str) -> bool:
    t = (text or "").strip()

    has_zip = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", t))
    has_phone = bool(re.search(r"(?:\+?1[\s\-\.]?)?(?:\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4})", t))
    has_email = bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", t))
    has_birthday_word = any(x in t.lower() for x in ("birthday", "bday", "dob"))
    has_month_name = bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b", t, re.IGNORECASE))
    has_address_word = any(x in t.lower() for x in ("address", "street", "st ", "road", "rd ", "avenue", "ave ", "drive", "dr ", "lane", "ln ", "court", "ct ", "circle", "cir ", "way", "blvd", "boulevard", "unit", "apt", "apartment", "lot"))
    has_referred_by = bool(re.search(r'\breferred\s+by\b', t, re.IGNORECASE))

    score = sum([
        has_zip or has_address_word,
        has_phone,
        has_email,
        has_birthday_word or has_month_name,
        has_referred_by,
    ])

    # if it looks like a bundle of customer fields, treat it as a customer entry
    return score >= 2


# "Can you send a reminder text to Liz Mayo, ..." — MPA can't send texts to
# customers. What we do instead (owner decisions 2026-07-03):
#   • ONE recognizable name  -> show that customer's card (it has the phone
#     number to text from) by routing to customer_info with the name as raw_text
#   • 2+ names, or "my customers"/"everyone" -> bulk_text_educate reply
# Lowercase names are fine when they follow "to" ("send a text to jane doe" —
# live local-test miss 2026-07-03: it fell through to the customer parser and
# proposed CREATING Jane Doe). Without a "to" tail we require a capitalized
# First Last pair so ordinary sentences never claim. Non-outreach messages
# don't match the verb pattern at all.
_BULK_TEXT_VERB_RE = re.compile(
    r"\b(?:send|text|message)\b.{0,20}\b(?:text|message|reminder)\b"
    r"|\b(?:text|message)\s+(?:a\s+)?reminder\b"
    r"|\bremind\b.{0,20}\bcustomers?\b",
    re.IGNORECASE,
)

_SEND_TEXT_STOP = {
    "my", "the", "a", "an", "all", "each", "every", "our", "please",
    "her", "him", "them", "me", "us", "can", "you",
    "text", "texts", "message", "messages", "reminder", "reminders",
    "send", "remind", "about", "previous", "order", "orders", "list",
    "today", "tomorrow", "now",
}

_CAP_WORD_RE = re.compile(r"^[A-Z][a-zA-Z'\-]*$")

def _cap_name_pairs(words: List[str]) -> List[str]:
    """Consecutive Capitalized-Word pairs ("Liz Mayo", "Dana Smith") — one
    name each, tolerant of missing commas between pasted names."""
    pairs, i = [], 0
    while i < len(words) - 1:
        if _CAP_WORD_RE.match(words[i]) and _CAP_WORD_RE.match(words[i + 1]):
            pairs.append(f"{words[i]} {words[i + 1]}")
            i += 2
        else:
            i += 1
    return pairs

def _parse_send_text_target(text: str) -> Optional[tuple]:
    """For a send-a-text ask, return (name_count, first_name); else None.
    name_count 0 means "their whole list" (customers/everyone)."""
    t = (text or "").strip()
    if not t or not _BULK_TEXT_VERB_RE.search(t):
        return None

    m = re.search(r"\bto\b\s+(.*)$", t, re.IGNORECASE)
    if m:
        tail = m.group(1)
        if re.search(r"\b(?:customers|clients|everyone|everybody)\b", tail, re.IGNORECASE):
            return (0, "")
        # "…to jane doe about her order" — the recipient ends at "about"
        tail = re.split(r"\babout\b", tail, flags=re.IGNORECASE)[0]
        groups = []
        for g in re.split(r",\s*|\s+and\s+", tail):
            toks = [w for w in re.findall(r"[A-Za-z'\-]+", g) if w.lower() not in _SEND_TEXT_STOP]
            if toks:
                groups.append(" ".join(toks[:4]))
        if not groups:
            return None
        count = max(len(groups), len(_cap_name_pairs([w for w in re.split(r"[,\s]+", tail) if w])))
        return (count, groups[0])

    # No "to" tail — conservative: only capitalized First Last pairs count
    pairs = _cap_name_pairs([w for w in re.split(r"[,\s]+", t) if w])
    if not pairs:
        return None
    return (len(pairs), pairs[0])


# Feature-help topic table: topic words → help intent, FIRST MATCH WINS (so
# "how do i cancel this order" hits order_help, not billing_help). Adding a
# help bubble for a new feature = one ui_text pair + one row here + golden
# cases. Matching is word-boundary ("ai" must not match inside "email").
_HELP_TOPICS = [
    (("inventory",), "inventory_help"),
    (("follow up", "follow ups", "follow-up", "followup", "followups"), "followup_help"),
    (("order", "orders", "ordering"), "order_help"),
    (("sync", "syncing", "synced"), "sync_help"),
    (("billing", "subscription", "subscribe", "cancel", "pricing", "price", "membership"), "billing_help"),
    (("privacy", "private", "safe", "secure", "security", "openai", "ai", "data"), "privacy_help"),
]

def _feature_help_intent(text: str) -> Optional[str]:
    """Return a <topic>_help intent when the message asks HOW a feature works
    rather than asking to USE it ("how does inventory work", "how do I add
    inventory?", "what are follow ups", "is my data safe"). None when it's an
    action — the guards keep counting/commands/data-questions with the action
    rules."""
    t = (text or "").strip().lower()
    if not t:
        return None
    # Actions/data-questions in question clothing stay where they belong:
    if re.search(r"\bhow many\b", t):                     # counting
        return None
    if re.search(r"\b(add|remove|set)\s+\d", t):          # command with a qty
        return None
    if re.search(r"\bneed to (re)?order\b", t):           # low-stock query
        return None
    if re.search(r"\bwhat\s+(?:is|are)\s+my\b", t):       # "what are MY orders" = her data
        return None
    _q = (
        re.search(
            r"^(?:hey |hi |ok(?:ay)? )?(?:how\s+do(?:es)?\s+(?:i|it|you|the|this|my)?|how\s+can\s+i|how\s+to\b|what\s+(?:can|does|is|are)|when\s+do(?:es)?\b|tell\s+me\s+about|explain)\b",
            t,
        )
        or re.search(r"\bhow\b.{0,40}\bworks?\b", t)
        or re.search(r"\b(?:is|are)\s+(?:my|our|it|this)\b.{0,40}\b(?:safe|secure|private)\b", t)
    )
    if not _q:
        return None
    for words, help_intent in _HELP_TOPICS:
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                return help_intent
    # Help-question shape but NO specific feature named — a general "how does
    # this work" → the standard cheat sheet, not a dead-end ("How does chat
    # work" got "I couldn't tell if that was a customer or an order" live
    # 2026-07-06). Gated on generic app/chat words so it can't hijack a
    # specific request that merely starts with a question word.
    if re.search(r"\b(chat|app|this|it|everything|get(?:ting)?\s+started)\b", t):
        return "chat_help"
    return None


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
    from rapidfuzz.distance import Levenshtein
    s = (msg or "").strip().lower()
    if s.startswith(("add ", "remove ", "set ")):
        return False
    if s in ("show my inventory", "show inventory", "my inventory", "inventory"):
        return True
    return any(Levenshtein.distance(w, "inventory") <= 2 for w in s.split())

# Common search terms that differ from MK's official product naming
_PRODUCT_QUERY_SYNONYMS: dict = {
    "eyeshadow": "eye shadow",
    "eye liner": "eyeliner",
    "lip color": "lipstick",
    "lip colour": "lipstick",
    "lip colors": "lipstick",
    "lip colours": "lipstick",
    "deluxe mini": "Unlimited Lip Gloss Set Deluxe Mini",
    "deluxe minis": "Unlimited Lip Gloss Set Deluxe Mini",
    "c+e": "serum c+e",
    "c + e": "serum c+e",
}

def _looks_like_product_price_query(msg: str) -> bool:
    s = (msg or "").strip().lower()
    # "what does " alone is NOT a price signal — it claimed "What does par mean
    # on the inventory spreadsheet" at conf 1.0 (live 2026-07-03); require "cost"
    if any(s.startswith(p) for p in ("how much is ", "how much does ", "price of ", "price check ", "what's the price", "what is the price")):
        return True
    if re.search(r"^what does\b.{0,60}\bcost\b", s):
        return True
    if re.search(r"\bhow much\b.{0,30}\bcost\b", s):
        return True
    if re.search(r"\bprice\b.{0,30}\bfor\b", s) and "order" not in s:
        return True
    # part number / sku queries (weed-garden 2026-07-09) — must route through the
    # same extraction path as "price of X"/"ingredients in X" below, otherwise the
    # bare-message (<=4 word) hijack a few lines down fuzzy-matches the RAW message
    # ("sku for lifting serum" as one string) instead of stripping "sku for" first,
    # which sent consultants a wrong product on the very card meant to fix this.
    # Order-context guard like the price rule above: "New order for Jane sku
    # 10233551" / "add sku … to the order" are order ENTRY — never hijack them.
    if (re.search(r"\b(?:part\s*(?:number|no\.?|#)|item\s+number|sku)\b", s)
            and not re.search(r"\b(?:order|add|remove)\b", s)):
        return True
    return False


def _parse_product_price_query_text(msg: str) -> str:
    s = (msg or "").strip()
    for pattern in (
        r"(?i)^how much (?:is|does)\s+(?:the\s+)?(.+?)(?:\s+cost)?\s*\??$",
        r"(?i)^price (?:of|check|for)\s+(?:the\s+)?(.+?)\s*\??$",
        r"(?i)^what(?:'s| is) the price (?:of|for)\s+(?:the\s+)?(.+?)\s*\??$",
        r"(?i)^what does\s+(?:the\s+)?(.+?)\s+cost\s*\??$",
        r"(?i)^what(?:'s| are)? (?:the\s+)?ingredients? (?:in|of|for)\s+(?:the\s+)?(.+?)\s*\??$",
        r"(?i)^ingredients? (?:in|of|for)\s+(?:the\s+)?(.+?)\s*\??$",
        # weed-garden 2026-07-09: part-number/sku queries route to product_lookup
        # via the new rule in parse_intent(), but route()'s "product_lookup by
        # classified intent" branch always resets raw_text back to the full
        # message — same as the ingredients patterns above, the actual product
        # name has to be pulled back out here at render time.
        r"(?i)^(?:what(?:'s| is)?\s+)?(?:the\s+)?(?:part\s*(?:number|no\.?|#)|item\s+number|sku)\b\s*(?:of|for|on)?\s*(?:the\s+)?(.+?)\s*\??$",
        r"(?i)^(?:can you\s+)?tell me about\s+(?:the\s+)?(.+?)\s*\??$",
        r"(?i)^(.+?)\s+ingredients?\s*\??$",
    ):
        m = re.match(pattern, s)
        if m:
            return m.group(1).strip()
    return s


def _looks_like_inventory_count(msg: str) -> bool:
    s = (msg or "").strip().lower()
    _NOT_INVENTORY = ("order", "customer", "followup", "client", "people", "consultant", "team", "member")
    if "how many" in s and " do i have" in s and not any(w in s for w in _NOT_INVENTORY):
        return True
    if s.endswith(" in inventory"):
        return True
    if "how many" in s and "inventory" in s:
        return True
    if s.startswith("how many ") and not any(w in s for w in _NOT_INVENTORY):
        return True
    if "on hand" in s and "do i have" in s:
        return True
    if "do i have" in s and "inventory" in s:
        return True
    if "in my inventory" in s:
        return True
    # "what foundations do I have in stock" (live 2026-07-03: answered with a
    # catalog price list instead of her inventory)
    if "in stock" in s and "do i have" in s and not any(w in s for w in _NOT_INVENTORY):
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

    m = re.match(r"^\s*add\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        parts = rest.split(None, 1)
        qty = _parse_small_number(parts[0]) if parts else None
        if qty is not None and len(parts) > 1:
            return ("add", qty, parts[1].strip())
        return ("add", 1, rest)

    m = re.match(r"^\s*remove\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        parts = rest.split(None, 1)
        qty = _parse_small_number(parts[0]) if parts else None
        if qty is not None and len(parts) > 1:
            return ("remove", qty, parts[1].strip())
        return ("remove", 1, rest)

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

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+do\s+i\s+have\s+on\s+hand\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+on\s+hand\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+do\s+i\s+have\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # "what foundations do I have in stock" (live 2026-07-03)
    m = re.match(r"^\s*(?:what|which|how\s+many)\s+(.+?)\s+do\s+i\s+have\s+in\s+stock\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s+(?:in\s+)?inventory\s*\??\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*(.+?)\s+in\s+inventory\s*\??\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*do\s+i\s+have\s+(.+?)\s+on\s+hand\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*do\s+i\s+have\s+(.+?)\s+in\s+(?:my\s+)?inventory\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*is\s+(?:the\s+)?(.+?)\s+in\s+(?:my\s+)?inventory\s*\??$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.match(r"^\s*how\s+many\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


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
        "out of stock",
        "what am i out of",
        "what items am i out of",
        "need to reorder",
    ))


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
    # Only unambiguous install phrasing stands alone; device words (phone, ipad,
    # tablet) require the word "app" too — bare "phone" appears in customer
    # lookups and new-customer entries far more often than app questions.
    _app_word = bool(re.search(r'\bapp\b', lowered))
    _app_context = any(t in lowered for t in ("home screen", "home scrn", "add to home", "install"))
    if lowered in ("app", "install", "the app", "app help", "help app") or _app_context or (_app_word and any(t in lowered for t in ("add", "save", "put", "get", "help", "screen", "phone", "ipad", "tablet", "device", "install", "download"))):
        return IntentResult(intent="app_help", confidence=1.0, raw_text=msg)

    # inventory
    if "inventory" in lowered or lowered in ("show my inventory", "show inventory", "my inventory"):
        return IntentResult(intent="inventory", confidence=1.0, raw_text=msg)

    # cancel — Spanish included: four UI_ES strings literally instruct
    # "escribe cancelar" but only English words matched, so Spanish users
    # following our own instructions couldn't cancel (flagged 2026-07-03,
    # fixed 2026-07-11). "sí"/"si" already work via normalize.yes().
    if lowered in ("cancel", "stop", "nevermind", "never mind", "start over", "startover",
                   "cancelar", "cancela", "cancelalo", "cancélalo", "empezar de nuevo", "empieza de nuevo"):
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
        "great start", "gsq", "star consultant", "star tracking", "star status",
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
        "who in my unit",
        # "ordered this/last month" moved to data_query triggers 2026-07-11
        # (Brian's call): "who ordered <time>" defaults to CUSTOMERS for
        # everyone — live evidence weed-garden 2026-07-10: a director asked it
        # meaning customers and dead-ended. Unit views keep their explicit
        # phrasings ("which consultants ordered…", "team…").
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

    # Star Consultant level names (Ruby, Diamond, Emerald, Pearl) in a unit context.
    # Whole-word matching on BOTH halves — substring matching stole a
    # new-customer paste ("Pearlwood Dr" + the "at" in "State", c48 5x) AND two
    # real orders of pearl-named products (the "is" inside "blemish" was the
    # context hit) — weed-garden 2026-07-10 + collateral scan 2026-07-11.
    # Order/add context always wins: pearl products get ordered, star levels don't.
    if (re.search(r"\b(ruby|diamond|emerald|pearl)s?\b", lowered)
            and not re.search(r"\b(order|orders|ordered|add|remove)\b", lowered)):
        if re.search(r"\b(consultants?|stars?|who|show|made|hit|at|is|are|earned|reached|levels?|status|close)\b", lowered):
            return IntentResult(intent="unit_query", confidence=0.9, raw_text=msg)

    # lapsed customers
    _lapsed_triggers = (
        "haven't ordered", "has not ordered", "hasn't ordered", "have not ordered",
        "not ordered", "gone quiet", "lapsed", "haven't heard from", "hasn't bought",
        "haven't bought", "not buying", "not ordering", "who hasn't", "who haven't",
    )
    if any(t in lowered for t in _lapsed_triggers):
        return IntentResult(intent="lapsed_customers", confidence=0.95, raw_text=msg)

    # 2+2+2 follow-ups — deterministic keyword claim (after lapsed so genuine
    # lapsed phrasings keep precedence). Without this, "do i have any followups"
    # reached the LLM, and an LLM answer of "lapsed_customers" won in route()
    # (its lapsed claim runs before its followup heuristic) — a coin flip on a
    # phrase our own bulk-text educate copy tells consultants to type.
    _followup_kw = ("follow up", "follow-up", "followup", "follow ups", "followups")
    if any(t in lowered for t in _followup_kw):
        return IntentResult(intent="followup", confidence=0.95, raw_text=msg)

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
        # moved from _unit_triggers 2026-07-11: "who ordered <time>" defaults
        # to customers (see comment there); bare forms land here so they get
        # a customer answer instead of recent_orders' "Who is the customer?"
        "ordered this month",
        "ordered last month",
        "ordered this week",
        "ordered last week",
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

    # "what [product] does [name] use/wear/buy" → that customer's order history.
    # Seen live 2026-07-02: the LLM split two near-identical phrasings between
    # product_lookup and recent_orders; this makes it deterministic.
    if re.search(r"\b(?:what|which)\b.*\bdoes\s+\w+(?:\s+\w+)?\s+(?:use|wear|buy|order)\b", lowered):
        return IntentResult(intent="recent_orders", confidence=0.95, raw_text=msg)

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
    # Stray "yes"/"ok"/"thanks" with NO pending open used to pass as a bare
    # name and fuzzy-match a random customer's card ("Yes" → Yessica Manzo —
    # weed-garden 2026-07-08, c114). MID-FLOW these must stay on the bare-name
    # path (customer_info kw → handler declines → pending layer consumes;
    # 1,360x/30d, deliberately never LLM — see the pinned golden cases). With
    # no pending there's nothing to confirm: return unknown deterministically
    # so the fallback bubble answers instead of a random card (and instead of
    # an LLM classifier coin-flip). Exact-word check, NOT substring — adding
    # "no" to the substring tuple below would kill real names like Nora.
    _CHITCHAT_WORDS = {"yes", "no", "ok", "okay", "yep", "nope", "yeah",
                       "nah", "sure", "thanks", "thank", "you"}
    if (_words and len(_words) <= 2
            and all(w.lower() in _CHITCHAT_WORDS for w in _words)
            and not (state or {}).get("pending")):
        return IntentResult(intent="unknown", confidence=0.9, raw_text=msg)
    looks_like_bare_name = (
        1 <= len(_words) <= 2
        and all(re.match(r"^[a-zA-Z'-]+$", w) for w in _words)
        and not any(t in lowered for t in ("new", "order", "add", "cancel", "tag", "note"))
    )

    # "customers named X" / "customers with the name X" — a NAME-list search,
    # not a city lookup. Must run BEFORE the city rules: the LLM sent these to
    # customers_by_city (conf 0.02) and echoed "No customers found in Who Are
    # My." (live 2026-07-03, 10-message struggle). Routes to customer_info with
    # the extracted name as raw_text — the existing fuzzy picker shows all
    # matches, same UX as typing the bare name.
    _named_m = re.search(r"customers?\s+(?:with\s+the\s+name,?\s+|named\s+|by\s+the\s+name\s+of\s+|called\s+)(.+)$", lowered)
    if _named_m:
        _name = _named_m.group(1).strip().rstrip(" ?.!,")
        if _name:
            return IntentResult(intent="customer_info", confidence=0.95, raw_text=_name)

    # customers by city — check before customer_info to avoid bare-name collision
    # Pattern 1: "customers in/from [city]" — unambiguous, no exclusions needed
    # Skip if this looks like a new customer entry
    _is_new_customer_entry = bool(re.match(r"^(new|add|create)\s+customer", lowered))
    # "customers in/from <City[, State]>" — allow a trailing ", State" and any
    # trailing qualifier ("with name and phone number", "please") so the comma+state
    # and polite/verbose forms extract the city instead of dead-ending. The old
    # pattern was end-anchored and comma-less, so "customers in Cleburne, Texas" and
    # "I need a list of customers from Cleburne, Texas with name and phone number"
    # both failed (weed-garden 2026-07-07).
    _city_m1 = None if _is_new_customer_entry else re.search(
        r"\bcustomers?\s+(?:in|from)\s+"
        r"([a-z][a-z.'\- ]*?)"                         # city (lazy, multi-word)
        r"(?:\s*,\s*([a-z]{2,}))?"                     # optional ", State"
        r"(?=\s+(?:with|and|w/|that|who|please|for|to|listed)\b|[?.!,]|\s*$)",
        lowered,
    )
    if _city_m1:
        _city1 = _city_m1.group(1).strip()
        if _city_m1.group(2):
            _city1 = f"{_city1}, {_city_m1.group(2).strip()}"
        return IntentResult(intent="customers_by_city", confidence=0.95,
                            slots={"city": _city1.title()}, raw_text=msg)
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
        _city_words = _city.lower().split()
        _first_word = _city_words[0]
        _is_adjective = _first_word in _CITY_ADJECTIVES
        _is_bare_new = _city.lower() == "new"  # "new customers" alone, not "New York"
        # Guard the CAPTURE, not just the first word (weed-garden 2026-07-11,
        # 2nd victim of this catch-all): real cities are 1-3 words, and none
        # contain question/verb/pronoun words. "Can you tell me which one of
        # my" was claimed as a city (c78); "Add Deb Gonzales to my" (c114,
        # 7/07). Rejected messages fall through to the LLM instead of
        # dead-ending on the city re-prompt.
        _CITY_STOP_WORDS = {"can", "you", "tell", "me", "which", "who", "what",
                            "do", "does", "did", "add", "my", "any", "have",
                            "one", "of", "to", "is", "was", "i", "we"}
        _capture_ok = (len(_city_words) <= 3
                       and not any(w in _CITY_STOP_WORDS for w in _city_words))
        if not _is_adjective and not _is_bare_new and _capture_ok:
            return IntentResult(intent="customers_by_city", confidence=0.95,
                                slots={"city": _city.title()}, raw_text=msg)

    # "add this address/phone/email/birthday to [name]" → edit_request
    # Must come before the general edit_request and customer_info checks
    if re.search(r'\badd\s+(?:this\s+)?(address|phone|email|birthday|birthdate)\b', lowered):
        return IntentResult(intent="edit_request", confidence=0.95, raw_text=msg)

    # "new/add/place/start order for X" or bare "order for X" → new_order
    # Must run BEFORE edit_request: product names like "repair set" contain the
    # edit verb "set", which was misrouting real orders to edit_request.
    # (Also must check before new_customer.)
    if re.search(r'\badd\s+an?\s+order\b', lowered):
        return IntentResult(intent="new_order", confidence=0.95, raw_text=msg)
    if re.match(r'^(new\s+|add\s+|place\s+|start\s+(?:an?\s+)?)?order\s+for\b', lowered):
        return IntentResult(intent="new_order", confidence=0.95, raw_text=msg)

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

    # "part number/item number/sku of X" → always product_lookup (must come before
    # customer_info catch-all). weed-garden 2026-07-09: consultant c29 asked "what is
    # the part number of natural lipstick" twice and gave up — the customer_info
    # catch-all below claims any "what is ..." message and dead-ended on "couldn't
    # find natural lipstick in your saved customers". Regex is deliberately scoped to
    # part/item/sku so "phone number" does NOT trigger this (must stay customer_info).
    # Order-context guard: "New order for Jane sku 10233551" / mid-flow "add sku …"
    # are order entry, not lookups — leave them to the order rules/pending flow.
    if (re.search(r"\b(?:part\s*(?:number|no\.?|#)|item\s+number|sku)\b", lowered)
            and not re.search(r"\b(?:order|add|remove)\b", lowered)):
        _part_tail_m = re.search(
            r"\b(?:part\s*(?:number|no\.?|#)|item\s+number|sku)\b\s*(?:of|for|on)?\s*(.+)$",
            lowered,
        )
        _part_tail = _part_tail_m.group(1).strip().rstrip(" ?.!,") if _part_tail_m else ""
        return IntentResult(intent="product_lookup", confidence=0.95,
                            raw_text=_part_tail if _part_tail else msg)

    # "create X" without "order" → new customer (e.g. "create nichole giveaway").
    # "create a list/report of …" is an analytics ask, not a person — it
    # prompted a new-customer form for "what I sold this week" (weed-garden
    # 2026-07-10, c110); let those fall through to the LLM/data_query.
    if (lowered.startswith("create ") and "order" not in lowered
            and not re.match(r"create\s+(?:a\s+|an\s+)?(?:list|report|summary)\b", lowered)):
        return IntentResult(intent="new_customer", confidence=0.9, raw_text=msg)

    # "show" narrowed 2026-07-11 (decided 2026-06-20): bare "show" claimed
    # product/team asks for customer lookup ("show me pink lipsticks" → a
    # customer-name fuzzy search) and forced every new feature to defensively
    # out-trigger this catch-all. Now "show" only claims when the message also
    # carries a person signal: a possessive ('s) or a contact-info word.
    # "show me robyn's contact information" stays; "show me pink lipsticks"
    # falls through to the LLM/product rules.
    # Singular "customer" is a person signal ("show customer marion vale");
    # plural "customers" is NOT — "show me timewise customers" is a
    # product-buyers list, and \bcustomer\b won't match the plural.
    _show_person = bool(
        re.search(r"\bshow\b", lowered)
        and (re.search(r"\w's\b", lowered)
             or re.search(r"\b(customer|client|clienta|contact|info|information|details?|email|phone|address|birthday)\b", lowered))
    )
    if (
        any(t in lowered for t in ("what's", "whats", "what is", "lookup", "info on", "information for"))
        or _show_person
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
        + "".join(f"- {name}\n" for name in _LLM_ALLOWED_INTENTS)
        + "\n"
        "Return JSON like:\n"
        '{"intent":"customer_info","confidence":0.92}\n\n'
        "If the intent is product_lookup, also include a \"product_query\" field containing "
        "ONLY the product name or phrase, with everything else stripped out — both conversational "
        "wrapper words (e.g. \"can you tell me about\", \"what's the\", \"info on\") AND words about "
        "what the user wants to know (e.g. \"price\", \"cost\", \"ingredients\"). Those words describe "
        "the question, not the product, and must not appear in product_query.\n"
        'Example: {"intent":"product_lookup","confidence":0.95,"product_query":"lifting serum"}\n'
        'Example: "ingredients in the lifting serum" -> {"intent":"product_lookup","confidence":0.95,"product_query":"lifting serum"}\n\n'
        "Rules:\n"
        "- Choose exactly one allowed intent.\n"
        "- If unsure, return unknown.\n"
        "- If the user is asking HOW a feature works or how to use it (an explanation, not performing the action), use the matching help intent: inventory_help, order_help, followup_help, sync_help, billing_help, or privacy_help.\n"
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
            **model_kwargs(),
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

        slots = {}
        if intent == "product_lookup":
            product_query = (data.get("product_query") or "").strip()
            if product_query:
                slots["product_query"] = product_query

        return IntentResult(
            intent=intent,
            confidence=confidence,
            slots=slots,
            raw_text=msg,
        )

    except Exception:
        return IntentResult(intent="unknown", confidence=0.0, raw_text=msg)


# =====================================================================
# route() — the full routing pipeline (see module docstring for the
# precedence overview). Conditions below were moved verbatim from
# MKChatEngine.handle_message on 2026-07-02; behavior is intentionally
# identical, including each rule's pending guard.
# =====================================================================

# "show all <term>" is only a product-list expansion when the term is not
# a CRM concept ("show all lapsed 3 days", "show all birthdays", ...)
_SHOW_ALL_CRM_TERMS = {"customer", "customers", "order", "orders", "inventory", "follow", "followup", "followups", "lapsed",
                       "team", "consultants", "consultant", "unit", "members", "member"}

# Intents that block the bare-message product lookup (a short message already
# claimed by one of these should not be treated as a product name)
_BARE_MSG_BLOCKING_INTENTS = {
    "recent_orders", "new_order", "leaderboard",
    "customers_by_city", "followup", "pcp", "top_sellers",
    "unit_query", "data_query",
}


_CATALOG_VOCAB_CACHE: dict = {}

def _catalog_vocab(catalog: Optional[List[dict]]) -> set:
    """Set of every 3+char whole word appearing in any product search_string.
    Cached per catalog object (id+len key — the catalog is a startup singleton)."""
    if not catalog:
        return set()
    key = (id(catalog), len(catalog))
    v = _CATALOG_VOCAB_CACHE.get(key)
    if v is None:
        v = set()
        for c in catalog:
            for w in re.findall(r"[a-z0-9]+", (c.get("search_string") or "").lower()):
                if len(w) >= 3:
                    v.add(w)
        _CATALOG_VOCAB_CACHE.clear()  # only ever one live catalog; don't leak
        _CATALOG_VOCAB_CACHE[key] = v
    return v


def _phrase_is_all_product_words(phrase: str, catalog: Optional[List[dict]]) -> bool:
    """True when EVERY significant word of `phrase` is a catalog word — the
    discriminator that separates "satin hands"/"repair" (all catalog words)
    from cities like "Eau Claire"/"Grand Island" (share a coincidental word
    like eau/island but not all). Used to yield the city reverse-pattern to
    the customers_by_product block (weed-garden 2026-07-12)."""
    vocab = _catalog_vocab(catalog)
    if not vocab:
        return False
    toks = [w for w in re.findall(r"[a-z0-9]+", (phrase or "").lower()) if len(w) >= 3]
    return bool(toks) and all(t in vocab for t in toks)


def route(message: str, state: Optional[dict] = None, catalog: Optional[List[dict]] = None) -> IntentResult:
    """
    Classify a chat message into the intent that will handle it.

    - state: session state dict; state["pending"] gates rules exactly like the
      old inline code did, state["last_ref_customer_name"] feeds the LLM.
    - catalog: language-specific product catalog (list of dicts); required for
      the SKU/product rules — without it those rules simply never claim.

    Returns an IntentResult whose raw_text is the normalized message text
    (stripped, SKUs replaced) that handlers should use instead of the original.
    """
    state = state or {}
    pending = state.get("pending")
    catalog = catalog or []

    msg = (message or "").strip()

    # ---- 1. Normalize: replace standalone 8-digit SKUs with product names ----
    if catalog:
        _sku_map = {str(item["sku"]).strip(): item["product_name"] for item in catalog if item.get("sku")}
        msg = re.sub(r'\b(\d{8})\b', lambda m: _sku_map.get(m.group(1), m.group(1)), msg)

    def _claim(name: str, slots: Optional[dict] = None) -> IntentResult:
        return IntentResult(intent=name, confidence=1.0, slots=slots or {}, raw_text=msg)

    # ---- 2. "show all <term>" — client sends this when consultant taps "+N more" ----
    if msg.lower().startswith("show all "):
        _more_term = msg[len("show all "):].strip()
        _more_words = set(_more_term.lower().split())
        if not (_more_words & _SHOW_ALL_CRM_TERMS):
            return _claim("show_all_products", {"term": _more_term})

    # ---- 3. Classify: keyword rules, then LLM fallback ----
    base = parse_intent(msg, state)
    intent = base.intent

    # ---- 4. Override: some "recent_orders" phrasings are actually NEW order entry ----
    if intent == "recent_orders" and _looks_like_new_order_entry(msg):
        base = IntentResult(intent="new_order", confidence=base.confidence, slots=base.slots, raw_text=msg)
        intent = "new_order"

    if not msg:
        return IntentResult(intent=base.intent, confidence=base.confidence, slots=base.slots, raw_text=msg)

    lowered = msg.lower()

    # ---- 5. Hijack chain (deterministic feature heuristics) ----

    # Look Book — claims even mid-flow so it works during an order
    if "look book" in lowered or "lookbook" in lowered:
        return _claim("look_book")

    # Inventory-style write without the word "inventory" — coach phrasing (not pending)
    if not pending and _looks_like_bare_inventory_write(msg):
        return _claim("inventory_guardrail")

    # Inventory print / PDF report (claims even mid-flow)
    if _looks_like_inventory_print(msg):
        return _claim("inventory_print")

    # "what does par mean ..." — a question about the inventory report's par
    # column (live 2026-07-03: claimed as a PRICE lookup at conf 1.0, answered
    # with Go Sets). Tight phrase match → the inventory cheat sheet.
    if "what does par mean" in lowered:
        return _claim("inventory_help")

    # Exact product name match — handles data-send clicks from multi-result lists (not pending)
    if not pending:
        _exact = next((c for c in catalog if c['product_name'].lower() == lowered.strip()), None)
        if _exact:
            return _claim("product_lookup", {"source": "exact", "match": _exact})

    # Product price lookup — "how much is X", "price of X" (even mid-flow),
    # or a bare 1-4 word message with a catalog match (not pending)
    def _all_words_in_product(query: str, product_name: str) -> bool:
        words = [w for w in query.lower().split() if len(w) >= 2]
        name_l = product_name.lower()
        return bool(words) and all(re.search(rf"\b{re.escape(w)}\b", name_l) for w in words)

    _is_bare_msg = (
        not pending
        and len(msg.split()) <= 4
        and re.match(r"^[\w\s\+\-]+$", msg)
        and intent not in _BARE_MSG_BLOCKING_INTENTS
    )
    _is_top_n_customers = bool(re.search(r"\btop\s+\d+\s+customers?\b", lowered))
    if not _is_top_n_customers and (_looks_like_product_price_query(msg) or _is_bare_msg):
        product_text = _parse_product_price_query_text(msg) if _looks_like_product_price_query(msg) else msg
        if product_text:
            product_text = _PRODUCT_QUERY_SYNONYMS.get(product_text.lower().strip(), product_text)
            if _is_bare_msg:
                # Bare message only claims when the catalog actually matches;
                # otherwise it falls through to the rules below
                word_matches = [c for c in catalog if _all_words_in_product(product_text, c["product_name"])]
                if word_matches:
                    return _claim("product_lookup", {"source": "bare", "product_text": product_text})
                if best_matches(catalog, product_text, limit=3, min_score=70, prefilter_fallback=False):
                    return _claim("product_lookup", {"source": "bare", "product_text": product_text})
            else:
                # Explicit price query always claims (handler replies "not found" on a miss)
                return _claim("product_lookup", {"source": "price", "product_text": product_text})

    # Inventory: quantity count — "how many X do I have" (even mid-flow)
    # Feature-help questions — "how does inventory work?" is a request for an
    # EXPLANATION, not an action. Without this gate the show/write rules claim
    # it and dump the whole inventory list (live 2026-07-04/05: "How do I add
    # inventory?" ×2 went unknown; weed-garden find). Runs BEFORE the inventory
    # action rules; extend _HELP_TOPICS one row per new topic bubble.
    _fh = _feature_help_intent(msg)
    if _fh:
        return _claim(_fh)

    if _looks_like_inventory_count(msg):
        _count_text = _parse_inventory_lookup_text(msg)
        if _count_text:
            return _claim("inventory_count", {"product_text": _count_text})

    # Inventory: show full list (even mid-flow)
    if _looks_like_inventory_show(msg):
        return _claim("inventory_show")

    # Inventory: low stock / what should I order (even mid-flow)
    if _looks_like_low_stock_query(msg):
        return _claim("inventory_low_stock")

    # Inventory: set desired on-hand threshold (even mid-flow)
    if _looks_like_inventory_threshold(msg):
        _thr_qty, _thr_text = _parse_inventory_threshold(msg)
        if _thr_qty is not None and _thr_text:
            return _claim("inventory_threshold", {"qty": int(_thr_qty), "product_text": _thr_text})

    # Inventory: add/remove/set commands; anything else mentioning inventory gets help
    if "inventory" in lowered:
        _inv_action, _inv_qty, _inv_text = _parse_inventory_write(msg)
        if _inv_action and _inv_qty is not None and _inv_text:
            return _claim("inventory_write", {"action": _inv_action, "qty": int(_inv_qty), "product_text": _inv_text})
        return _claim("inventory_help")

    # Add/remove against an ALREADY-SUBMITTED order (not pending). Chat can only
    # edit an order draft still being built; with no draft open, "add X to
    # jane's order" / "remove jane's order" refer to an order already sent to
    # MyCustomers, which chat can't change. Claim and educate instead of falling
    # into the normal parse — which used to start a phantom new order (live
    # incident 2026-07-02, and the add-path silently created a separate
    # one-item order). Must run BEFORE delete_customer ("delete judy's order"
    # would otherwise start the delete-customer flow).
    if not pending:
        if re.search(r"\b(?:remove|delete|cancel|void|take\s+(?:\w+\s+)?off)\b.*\borders?\b", lowered):
            return _claim("submitted_order_edit", {"action": "remove"})
        # possessive accepts straight AND iOS curly apostrophes ("judy pasko’s order")
        if re.search(r"\b(?:add|put|include)\b.*\b(?:to|on|onto|into|in)\s+(?:(?:her|his|their|the|that|my)\s+)?(?:[a-z][\w'’‘-]*(?:\s+[a-z][\w'’‘-]*)?['’‘]s\s+)?(?:last\s+|previous\s+|existing\s+|recent\s+|submitted\s+)?orders?\b", lowered):
            return _claim("submitted_order_edit", {"action": "add"})

    # Delete customer (not pending)
    if not pending:
        _del_m = re.match(r"^\s*delete\s+(customer\s+)?(.+?)\s*$", msg, re.IGNORECASE)
        if _del_m:
            return _claim("delete_customer", {"target": (_del_m.group(2) or "").strip()})

    # Referral link (not pending)
    if not pending and any(t in lowered for t in ("referral code", "referral link", "my referral", "refer a friend", "refer someone")):
        return _claim("referral")

    # MyCustomers link (not pending) — "link to mycustomers", "mycustomers link",
    # "link to intouch", "open mycustomers". Requires link-ish context, not just
    # the word "mycustomers": messages like "add a note to X in mycustomers" or
    # "update her address in mycustomers" must keep falling through to the more
    # helpful notes_educate / edit_request replies below (which include the same
    # link anyway).
    _LINKISH_RE = r"\b(?:link|open|log\s*in|login|url|website|go\s+to|take\s+me)\b"
    if not pending and (
        ("mycustomers" in lowered and re.search(_LINKISH_RE, lowered))
        or re.search(r"\blink\s+to\s+intouch\b", lowered)
    ) and not re.search(r"\bnew\s+customer\b", lowered):
        return _claim("mycustomers_link")

    # Notes — not supported yet (not pending). Must run before the general
    # edit_request check below and yield to real order entry (see
    # _looks_like_notes_request's guard against order signal, e.g. "Misty
    # Cameron add a note, wants pink prism shimmer eye stick, ...").
    if not pending and _looks_like_notes_request(msg):
        return _claim("notes_educate")

    # Send-a-text asks — MPA can't text customers (not pending). One name →
    # show that customer's card (it has the phone number to text from);
    # several names or the whole list → bulk_text_educate reply.
    if not pending:
        _stt = _parse_send_text_target(msg)
        if _stt is not None:
            _n_names, _first_name = _stt
            if _n_names == 1 and _first_name:
                return IntentResult(intent="customer_info", confidence=1.0,
                                    slots={"source": "send_text"}, raw_text=_first_name)
            return _claim("bulk_text_educate")

    # Customer edit requests — not supported, redirect to InTouch (not pending)
    _EDIT_FIELD_RE = r"\b(address|phone|email|birthday|birthdate|city|state|zip|postal)\b"
    # Bare edit phrasings with no field named ("edit this customer", "edit her
    # info", "update this customer") — conservative: requires an edit verb +
    # a customer-ish object word, and must not steal order-edit phrasings
    # (those belong to submitted_order_edit, handled earlier in the chain).
    _EDIT_BARE_OBJECT_RE = r"\b(this\s+customer|her\s+info|his\s+info|their\s+info|this\s+client|that\s+customer|customer\s+info)\b"
    _edit_bare = (
        any(lowered.startswith(p) for p in ("update ", "change ", "edit ", "modify "))
        and re.search(_EDIT_BARE_OBJECT_RE, lowered)
        and "order" not in lowered
    )
    _edit_not_supported = (
        not pending
        and (
            # "update/change/edit/modify [name] [field] ..."
            (
                any(lowered.startswith(p) for p in ("update ", "change ", "edit ", "modify "))
                and re.search(_EDIT_FIELD_RE, lowered)
                and "order" not in lowered
                and "inventor" not in lowered
            )
            # "add [field] for/to [name]" — e.g. "add address for Jane"
            or bool(re.match(
                r"^add\s+(an?\s+)?(address|phone|email|birthday|birthdate|phone\s+number|email\s+address)\b",
                lowered,
            ))
            # bare "edit this customer" / "edit her info" (owner-approved
            # 2026-07-03) — same educate reply as field-named edits; becomes
            # the entry point for the real customer-edit feature when built
            or _edit_bare
        )
    )
    if _edit_not_supported:
        return _claim("edit_request", {"source": "text"})

    # PCP enrolled list (not pending)
    if not pending:
        _pcp_show = (
            "pcp" in lowered and
            any(t in lowered for t in ("list", "who", "show", "enrolled", "my pcp", "customers", "mailer")) and
            not any(t in lowered for t in ("should", "candidate", "score", "add", "drop", "remove"))
        )
        if _pcp_show:
            return _claim("pcp_list")

    # ---- 6. Handler-position rules — text rules interleaved exactly where
    #         their handlers sit in mk_chat_core, so they cannot steal a
    #         message an earlier handler would have claimed ----

    # leaderboard (not pending) and top_sellers (even mid-flow) claim their base intent here
    if not pending and intent == "leaderboard":
        return IntentResult(intent=intent, confidence=base.confidence, slots=base.slots, raw_text=msg)
    if intent == "top_sellers":
        return IntentResult(intent=intent, confidence=base.confidence, slots=base.slots, raw_text=msg)

    # Birthday period lookup (not pending)
    if not pending:
        _bday_period = None
        _bday_triggers = ("birthday", "birthdays", "bday", "bdays")
        if any(t in lowered for t in _bday_triggers):
            if "today" in lowered:
                _bday_period = "today"
            elif "tomorrow" in lowered:
                _bday_period = "tomorrow"
            elif any(x in lowered for x in ("this month", "this mo")):
                _bday_period = "month"
            elif "next month" in lowered:
                _bday_period = "next_month"
            elif "next week" in lowered:
                _bday_period = "next_week"
            elif any(x in lowered for x in ("this week", "this wk")):
                _bday_period = "week"
            elif any(x in lowered for x in ("this quarter", "quarter")):
                _bday_period = "quarter"
            elif any(x in lowered for x in ("upcoming", "coming up", "soon", "next 30")):
                _bday_period = "upcoming"
            # Named months → "month:N" (weed-garden 2026-07-11: c78 asked for
            # July birthdays 4 natural ways and every one word-saladed — the
            # rule only knew relative periods). GUARDS: entry/edit messages
            # ("New customer Dana birthday July 4 1980") must not be stolen —
            # skip on entry/edit verbs or month followed by a day number.
            # "may" is also a modal verb: require a month-ish context for it.
            if _bday_period is None and not re.search(
                    r"\b(new|add|create|order|edit|update|change|set)\b", lowered):
                _MONTH_NUMS = {"january": 1, "february": 2, "march": 3, "april": 4,
                               "may": 5, "june": 6, "july": 7, "august": 8,
                               "september": 9, "october": 10, "november": 11, "december": 12}
                for _mn, _mi in _MONTH_NUMS.items():
                    if _mn == "may":
                        _hit = re.search(r"\b(?:in|during|of)\s+may\b(?!\s+\d)|\bmay\s+(?:customer\s+)?birthdays?\b", lowered)
                    else:
                        _hit = re.search(rf"\b{_mn}\b(?!\s+\d)", lowered)
                    if _hit:
                        _bday_period = f"month:{_mi}"
                        break
        if _bday_period:
            return _claim("birthday_lookup", {"period": _bday_period})

    # Guard: "who are my retinol customers" type messages get misclassified as
    # lapsed_customers by the LLM. Detect product-search phrasing so the message
    # falls through to the customer-search-by-product rule below.
    _lapsed_product_override = False
    _lapsed_guard_m = re.search(r"\bwho\s+are\s+(?:my\s+)?(.+?)\s+customers\b", lowered)
    if _lapsed_guard_m:
        _lapsed_non_product = {"lapsed", "inactive", "active", "top", "best", "new",
                               "recent", "who", "are", "my", "show", "all", "following"}
        _lapsed_product_words = [w for w in _lapsed_guard_m.group(1).strip().lower().split()
                                 if w not in _lapsed_non_product]
        if _lapsed_product_words:
            _lapsed_product_override = True

    # Lapsed customers (not pending) — "show all lapsed N days" is the overflow tap
    if not pending and not _lapsed_product_override and (
        intent == "lapsed_customers"
        or re.match(r"show all lapsed \d+ days", lowered)
    ):
        return IntentResult(intent="lapsed_customers", confidence=base.confidence if intent == "lapsed_customers" else 1.0,
                            slots=base.slots if intent == "lapsed_customers" else {}, raw_text=msg)

    # Customers by city (not pending) — "customers in X all" is the overflow tap
    if not pending and (
        intent == "customers_by_city"
        or re.match(r"customers\s+in\s+\S.+\s+all$", lowered)
    ):
        # "repair customers" / "timewise customers": parse_intent's reverse
        # "[X] customers" pattern grabbed a PRODUCT word as a city. When the
        # captured city is entirely catalog words, it's a product-buyers query
        # — fall through to the customers_by_product block below (weed-garden
        # 2026-07-12). Real cities (Madison, Eau Claire) aren't all catalog words.
        _city_slot = (base.slots or {}).get("city", "") if intent == "customers_by_city" else ""
        if not (_city_slot and _phrase_is_all_product_words(_city_slot, catalog)):
            return IntentResult(intent="customers_by_city", confidence=base.confidence if intent == "customers_by_city" else 1.0,
                                slots=base.slots if intent == "customers_by_city" else {}, raw_text=msg)

    # Product lookup by classified intent (not pending)
    if not pending and intent == "product_lookup":
        _pl_slots = dict(base.slots)
        _pl_slots["source"] = "intent"
        return IntentResult(intent="product_lookup", confidence=base.confidence, slots=_pl_slots, raw_text=msg)

    # Follow-up trigger — 2+2+2 (not pending)
    if not pending:
        _followup_triggers = ("follow up", "followup", "follow-up", "any follow", "follow ups", "followups")
        _more_triggers = ("any more", "more follow", "next follow")
        _is_followup = any(t in lowered for t in _followup_triggers)
        _is_more = any(t in lowered for t in _more_triggers)
        if _is_followup or _is_more:
            return _claim("followup", {"more": bool(_is_more)})

    # Customer search by product — "repair customers", "customers who use X",
    # "who bought X" (not pending; skips pasted customer entries and tag edits)
    if not pending and not _looks_like_full_customer_entry(msg) and not re.match(r'^\s*tags?\s*:', msg, re.IGNORECASE) and not re.match(r'^\s*(new|add|create)\s+customer\b', msg, re.IGNORECASE):
        _product_term = None
        _or_terms = None

        # Pattern 1: "[product] customers" — e.g. "repair customers", "show my matte foundation customers"
        _m1 = re.search(r"(?:show\s+)?(?:my\s+)?(.+?)\s+customers\b", lowered)
        # Pattern 2: "customers who [use/ordered/buy/have] [product]" — e.g. "customers who use repair"
        _m2 = re.search(r"\bcustomers\s+who\s+(?:(?:has|have|had)\s+)?(?:use|ordered|buy|have|bought|order|used|purchased)\s+(.+)", lowered)
        # Pattern 3: "who bought/ordered/uses [product]" — "has/have" auxiliary handled explicitly
        _m3 = re.search(r"\bwho\s+(?:(?:has|have|had)\s+)?(?:bought|ordered|uses|orders|buys|got|used|purchased|purchase)\s+(.+)", lowered)

        _prefix_filler = {"who", "are", "my", "show", "list", "which", "what", "any",
                          "the", "a", "all", "give", "me", "find", "get", "have", "do",
                          "i", "is", "of", "new", "other", "please",
                          "how", "many", "much", "more", "most"}

        if _m2:
            _product_term = _m2.group(1).strip()
        elif _m3:
            _product_term = _m3.group(1).strip()
        elif _m1:
            _candidate = _m1.group(1).strip()
            # Strip leading filler words (e.g. "who are my" from "who are my repair customers")
            _candidate_words = [w for w in _candidate.split() if w not in _prefix_filler]
            _candidate = " ".join(_candidate_words).strip()
            # Capture guard, twin of the city reverse-pattern's (weed-garden
            # 2026-07-11): leftover verbs/question words mean this isn't a
            # product phrase. Without this, messages the city guard rejects
            # relocate HERE ("did my customers sync" → product term "did" →
            # word-salad "No customers found who bought did") — the exact
            # relocation trap the 2026-07-08 report deferred F2a over.
            _PRODUCT_STOP = {"did", "does", "can", "you", "tell", "add", "to",
                             "was", "were", "she", "he", "they", "we", "one",
                             "sync", "synced"}
            if _candidate and not any(w in _PRODUCT_STOP for w in _candidate_words):
                _product_term = _candidate

        if _product_term:
            # Strip trailing time qualifiers so "repair the last 6 months" → "repair"
            _product_term = re.sub(
                r'\s+(?:in\s+)?(?:the\s+)?(?:(?:last|past|this|next)\s+\d*\s*(?:day|week|month|year|quarter)s?'
                r'|(?:january|february|march|april|may|june|july|august|september|october|november|december)'
                r'|\d{4})$',
                '',
                _product_term,
                flags=re.IGNORECASE,
            ).strip()
            _filler = {"on", "the", "a", "an", "use", "using", "with", "for", "in", "of"}
            _singular = {"sets": "set", "kits": "kit", "creams": "cream", "serums": "serum",
                         "masks": "mask", "sticks": "stick", "glosses": "gloss", "liners": "liner",
                         "primers": "primer", "powders": "powder", "products": "product"}
            # Strip trailing punctuation per term — "who ordered last quarter?"
            # kept "quarter?" which dodged the time-word guard below and
            # word-salad'd as a product search (weed-garden 2026-07-10, c39
            # fought it 7x with cancels).
            terms = [_singular.get(w, w) for w in
                     (t.strip("?!.,;:") for t in _product_term.lower().split())
                     if len(w) > 1 and w not in _filler]

            # Skip for time-period queries ("this quarter", "last month", etc.) — let data_query handle those
            _TIME_WORDS = {
                # Time periods
                "this", "last", "next", "today", "yesterday",
                "week", "weeks", "month", "months", "year", "years",
                "quarter", "quarters", "past", "day", "days",
                "recent", "recently", "ago",
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
                "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                "q1", "q2", "q3", "q4",
                # Quantity/frequency words (not product names)
                "more", "than", "once", "twice", "times", "over", "under",
                "least", "most", "many", "much", "few", "several",
                # Order source/channel words (not product names)
                "online", "myshop", "cds", "store", "person",
            }
            if terms and all(t in _TIME_WORDS or t.isdigit() for t in terms):
                _product_term = None

            if _product_term:
                # Category aliases: map common words to OR-matched product name fragments
                _FRAGRANCE_TERMS = ["eau de parfum", "eau de toilette", "cologne spray", "body mist"]
                _CATEGORY_MAP = {
                    "perfume":   _FRAGRANCE_TERMS,
                    "fragrance": _FRAGRANCE_TERMS,
                    "cologne":   _FRAGRANCE_TERMS,
                    "parfum":    _FRAGRANCE_TERMS,
                }
                _category_key = _product_term.lower().strip()
                _or_terms = _CATEGORY_MAP.get(_category_key) or _CATEGORY_MAP.get(_category_key.rstrip("s"))

            if _product_term and terms:
                return _claim("customers_by_product",
                              {"product_term": _product_term, "terms": terms, "or_terms": _or_terms})

    # ---- 7. Fallthrough: the classified intent stands. handle_message
    #         dispatches it (recent_orders, customer_spend, cancel,
    #         edit_request, app_help, chat_help, unit_query, car_program,
    #         customer_info, data_query) or lets the pending flow / normal
    #         LLM order-customer parse consume it. ----

    # Suppressed lapsed_customers (product-phrase override, and the
    # customer-search rule above didn't claim it either): today this falls all
    # the way to the normal parse, so don't let the lapsed handler see it.
    if _lapsed_product_override and intent == "lapsed_customers":
        return IntentResult(intent="unknown", confidence=base.confidence,
                            slots={"suppressed": "lapsed_customers"}, raw_text=msg)

    # Honor a raw_text the classifier extracted (the "customers named X" rule
    # passes just the name so the customer_info handler shows the name picker).
    # Every other parse_intent rule sets raw_text=msg, so this is neutral.
    return IntentResult(intent=base.intent, confidence=base.confidence, slots=base.slots,
                        raw_text=(base.raw_text or msg))
