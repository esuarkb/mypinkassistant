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
from intent_router import (
    route,
    INTENT_REGISTRY,
    parse_intent,
    best_matches,
    _looks_like_full_customer_entry,
    _parse_product_price_query_text,
    _parse_inventory_lookup_text,
    _parse_inventory_write,
    _parse_inventory_threshold,
    # re-exported for scripts/tests that still import these from mk_chat_core;
    # their canonical home is intent_router (routing consolidation 2026-07-02)
    _looks_like_new_order_entry,
    _looks_like_bare_inventory_write,
    _looks_like_inventory_print,
    _looks_like_inventory_show,
    _looks_like_inventory_count,
    _looks_like_low_stock_query,
    _looks_like_inventory_threshold,
    _looks_like_product_price_query,
    _PRODUCT_QUERY_SYNONYMS,
)
from inventory_store import (
    upsert_inventory_quantity,
    get_inventory_item,
    list_inventory,
)

from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz, process

from db import connect, is_postgres

from .dbutil import PH, db_connect
from .jobs import insert_job, maybe_queue_initial_customer_import
from .normalize import (
    STATE_MAP,
    STREET_SUFFIXES,
    birthday_display,
    format_phone_display,
    no,
    normalize_birthday,
    normalize_city,
    normalize_phone,
    normalize_state,
    parse_address_line,
    _normalize_street,
    _parse_address_line_raw,
    yes,
)
from .catalog import (
    auto_pick_match,
    fmt_price,
    get_catalog_path_for_language,
    load_catalog,
    multi_product_lookup,
    _find_exact_catalog_match,
    _fmt_product_list_item,
    _fmt_product_lookup_single,
)
from .config import MATCH_LIMIT, MODEL, TOP5
from .customer_edits import apply_customer_edits, looks_like_command
from .order_parse import (
    fix_qty_if_number_is_part_of_name,
    llm_pick_from_candidates,
    parse_add_remove,
    parse_qty_change,
    parse_qty_prefix,
    parse_with_openai,
    _parse_date_value,
    _parse_discount,
    _parse_order_date_cmd,
    _split_order_for_prefix,
)
from .render import (
    propose_top,
    render_customer_delete_picker,
    render_customer_picker,
    render_top5,
    _build_chat_help_html,
    _format_inventory_item,
    _format_inventory_list,
    _format_low_stock_list,
    _QR_YN,
    _wants_to_skip,
)
from .car_program import _handle_car_program
from .data_query import _handle_data_query
from .session import ensure_sessions_table, load_session_state, save_session_state
from .unit_query import _handle_unit_query
from .types import ChatReply
from .ui_text import UI_EN, UI_ES


# ---------------------------------------------------------------------
# Step 4 (2026-07-03): dispatch-table plumbing.
# _HandlerCtx carries the per-message locals that handle_message used to
# share with its inline intent blocks; each _intent_* handler method
# unpacks what it needs. Handlers return a ChatReply, or None to decline
# ("didn't handle — keep falling through").
# ---------------------------------------------------------------------
class _HandlerCtx:
    __slots__ = (
        "message", "msg", "lowered", "sid", "state", "consultant",
        "consultant_id", "session_id", "user_agent", "language", "ui",
        "catalog", "last_customer", "pending", "intent_result", "show_scores",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw[k])


def _interrupts_pending(intent: str) -> bool:
    """Engine dispatch policy: may this intent's handler run while a
    pending flow is open? Declared per-intent in INTENT_REGISTRY
    (intent_router.py) — the one place intents are described."""
    return bool(INTENT_REGISTRY.get(intent, {}).get("interrupts_pending"))


def _resolve_pronoun_guess(guess: str, state: dict) -> str:
    g = (guess or "").strip().lower()

    if g in ("she", "her", "he", "him", "they", "them"):
        name = (state.get("last_ref_customer_name") or "").strip()
        if name:
            return name

    return guess


# Word-salad guard (2026-07-03): the customer-name-guess fallback in
# _intent_recent_orders / _intent_customer_spend / _intent_customer_info takes
# the last 1-2 tokens left after stripping each site's own stop_words set. That
# set was hand-picked per site and didn't cover every common English function
# word or verb, so a stray sentence like "...can you calculate totals or
# discounts?" left "or discounts" as the "name", and "...so the total was
# $52.60" left "the was" — both then produced a nonsense
# "I couldn't find {name} in your saved customers" reply (live production,
# 2026-06-27/29). This is a small, shared blocklist layered on TOP of each
# site's existing stop_words (not a replacement) — smallest fix, no parser
# restructuring. Apply via _is_plausible_name_guess() before using a guess.
_NAME_GUESS_BLOCKLIST = {
    "the", "a", "an", "this", "that", "these", "those",
    "or", "and", "so", "was", "were", "am", "is", "are", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "with", "from", "as", "it", "its",
    "your", "you", "my", "her", "his", "their", "our", "we", "he", "she", "they",
    "gave", "give", "so", "totals", "total", "discount", "discounts",
    "account", "calculate", "calculating",
}

def _is_plausible_name_guess(guess: str) -> bool:
    """Reject a customer-name guess made up entirely of common English
    function words / verbs — those are stray leftovers, not a name."""
    g = (guess or "").strip()
    if not g:
        return False
    words = g.lower().split()
    if not words:
        return False
    return not all(w in _NAME_GUESS_BLOCKLIST for w in words)

# -------------------------
# Chat Engine
# -------------------------

class MKChatEngine:
    """
    Stateless per-request; state is loaded/saved to sessions table (SQLite or Postgres).
    """
    def __init__(self):
        load_dotenv()
        self.client = OpenAI()
        self._catalog_cache = {}  # {"en": [...], "es": [...]}

    ##
    def handle_message(self, message: str, consultant_id: int, session_id: Optional[int] = None, user_agent: Optional[str] = None) -> ChatReply:
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

        # ALL routing decisions live in intent_router.route() — one call, one
        # documented precedence order (see the intent_router.py docstring).
        # raw_text comes back normalized: stripped, standalone 8-digit SKUs
        # replaced with product names.
        import re as _re
        intent_result = route(message, state, catalog)
        msg = intent_result.raw_text

        # Product look-up "show more" — client sends "show all <term>" when
        # consultant taps "+N more". Returns before intent logging, as before.
        if intent_result.intent == "show_all_products":
            _more_term = intent_result.slots.get("term", "")
            def _all_words_in_product_more(query: str, product_name: str) -> bool:
                words = [w for w in query.lower().split() if len(w) >= 2]
                name_l = product_name.lower()
                return bool(words) and all(_re.search(rf"\b{_re.escape(w)}\b", name_l) for w in words)
            _all_more = [c for c in catalog if _all_words_in_product_more(_more_term, c["product_name"])]
            if not _all_more:
                _all_more = best_matches(catalog, _more_term, limit=20, min_score=50)
            if _all_more:
                lines = ["<strong>Product Look Up</strong>"]
                for m in _all_more:
                    lines.append(_fmt_product_list_item(m))
                return ChatReply("<br>".join(lines))
            return ChatReply("I couldn't find any products matching that search.")
        print("[INTENT]", intent_result.intent, intent_result.confidence, intent_result.raw_text)
        _intent_log_id = None
        try:
            with tx() as (_il_conn, _il_cur):
                if is_postgres():
                    _il_cur.execute(
                        f"INSERT INTO intent_logs (consultant_id, intent, confidence, message_text, user_agent) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}) RETURNING id",
                        (consultant_id, intent_result.intent, intent_result.confidence, msg[:200], user_agent),
                    )
                    _row = _il_cur.fetchone()
                    _intent_log_id = _row[0] if _row else None
                else:
                    _il_cur.execute(
                        f"INSERT INTO intent_logs (consultant_id, intent, confidence, message_text, user_agent) VALUES ({PH}, {PH}, {PH}, {PH}, {PH})",
                        (consultant_id, intent_result.intent, intent_result.confidence, msg[:200], user_agent),
                    )
                    _intent_log_id = _il_cur.lastrowid
        except Exception:
            pass


        if not msg:
            return ChatReply(ui["empty_prompt"])
        
        lowered = msg.lower()

        # -----------------------------------------------------------------
        # Dispatch (step 4) — one handler method per intent, wired in
        # _INTENT_DISPATCH below. While a pending flow is open, only intents
        # whose INTENT_REGISTRY entry has interrupts_pending=True may answer
        # (this is the explicit policy that used to be ~20 scattered inline
        # `if not pending` guards). A handler returning None means "didn't
        # handle — keep falling through", exactly like the old inline blocks.
        # -----------------------------------------------------------------
        ctx = _HandlerCtx(
            message=message, msg=msg, lowered=lowered, sid=sid, state=state,
            consultant=consultant, consultant_id=consultant_id,
            session_id=session_id, user_agent=user_agent, language=language,
            ui=ui, catalog=catalog, last_customer=last_customer,
            pending=pending, intent_result=intent_result, show_scores=show_scores,
        )

        _handler_name = self._INTENT_DISPATCH.get(intent_result.intent)
        if _handler_name is not None and (not pending or _interrupts_pending(intent_result.intent)):
            _reply = getattr(self, _handler_name)(ctx)
            if _reply is not None:
                return _reply

        # Pending flows consume the message next (order confirm, pickers, ...)
        if pending:
            _reply = self._handle_pending(ctx)
            if _reply is not None:
                return _reply

        # Nothing claimed it — OpenAI order/customer parser
        return self._normal_parse(ctx)

    def _intent_look_book(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        lowered = ctx.lowered
        language = ctx.language
        intent_result = ctx.intent_result

        # -------------------------
        # Look Book — works even mid-order
        # -------------------------
        if intent_result.intent == "look_book":
            _force_es = "spanish" in lowered or "español" in lowered or "espanol" in lowered
            _force_en = "english" in lowered or "inglés" in lowered or "ingles" in lowered
            if _force_es or (language == "es" and not _force_en):
                lb_url = "https://cdn.mypinkassistant.com/lookbook-es.pdf"
                lb_label = "La Imagen actual"
            else:
                lb_url = "https://cdn.mypinkassistant.com/lookbook.pdf"
                lb_label = "current Look Book"
            return ChatReply(
                f'Here\'s the <a href="{lb_url}" class="inapp-overlay-link">{lb_label}</a>&nbsp; '
                f'<button class="fdp-copy copy-link-btn" data-copy="{lb_url}">Copy Link</button>'
            )
        return None

    def _intent_order_of_application(self, ctx) -> Optional[ChatReply]:
        """Static link to the MK Order of Application skincare chart. The URL is
        read live from the catalog so update_catalog's nightly refresh self-heals
        MK's rotating Demandware static hash. Rendered target="_blank" like the
        per-product fact-sheet / OOA links (MK-hosted, not our CDN — no in-app
        overlay). Works even mid-order. weed-garden 2026-07-16, c78."""
        intent_result = ctx.intent_result
        ui = ctx.ui
        catalog = ctx.catalog
        if intent_result.intent == "order_of_application":
            from .catalog import get_order_of_application_url
            url = get_order_of_application_url(catalog)
            return ChatReply(ui["order_of_application_reply"].format(url=url))
        return None

    def _intent_set_sales_tax(self, ctx) -> Optional[ChatReply]:
        """Set or show the consultant's sales tax rate (consultants.tax_rate).
        Rate auto-applies to My Inventory orders at confirm time; 0/unset = no
        tax (today's behavior). Settings-page field edits the same column.
        Discount feature 2026-07-18."""
        import re
        from db import tx
        msg = ctx.msg
        ui = ctx.ui
        consultant_id = ctx.consultant_id
        if ctx.intent_result.intent != "set_sales_tax":
            return None

        # A number means SET; no number means SHOW. Ignore digits glued to
        # words ("tax2go") — take the first standalone decimal.
        m = re.search(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*%?(?![\w.])", msg)
        if m is None:
            with tx() as (conn, cur):
                cur.execute(f"SELECT tax_rate FROM consultants WHERE id = {PH}", (consultant_id,))
                row = cur.fetchone()
            rate = float(row[0]) if row and row[0] is not None else 0.0
            if rate > 0:
                return ChatReply(ui["sales_tax_show"].format(rate=f"{rate:g}"))
            return ChatReply(ui["sales_tax_unset"])

        rate = float(m.group(1))
        if rate > 100:  # MK's field caps at 100; anything above is a typo
            return ChatReply(ui["sales_tax_invalid"])
        with tx() as (conn, cur):
            cur.execute(f"UPDATE consultants SET tax_rate = {PH} WHERE id = {PH}", (rate, consultant_id))
        if rate == 0:
            return ChatReply(ui["sales_tax_cleared"])
        return ChatReply(ui["sales_tax_set"].format(rate=f"{rate:g}"))

    def _intent_inventory_guardrail(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        intent_result = ctx.intent_result
        ui = ctx.ui

        # -------------------------
        # Bare inventory-style write guardrail
        # -------------------------
        if intent_result.intent == "inventory_guardrail":
            return ChatReply(ui["inventory_guardrail"])
        return None

    def _intent_inventory_print(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        ui = ctx.ui
        intent_result = ctx.intent_result

        # -------------------------
        # Inventory: print / PDF report
        # -------------------------
        if intent_result.intent == "inventory_print":
            import os
            base_url = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
            link = f"{base_url}/inventory/print" if base_url else "/inventory/print"
            return ChatReply(ui["inventory_report"].format(link=link))
        return None

    def _intent_product_lookup(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        catalog = ctx.catalog
        pending = ctx.pending
        intent_result = ctx.intent_result
        ui = ctx.ui
        import re
        import re as _re

        # Name+items order entries sometimes classify as product_lookup — an
        # LLM coin-flip (live 2026-07-03: "Elvia G… eyeliner, sponge, mascara,
        # …" got the one-product-at-a-time coaching and the order was never
        # placed, while the identical shape routed new_order earlier that day).
        # If the message LEADS with a saved customer's name AND reads like an
        # order entry, decline — it falls through to the order parser, which
        # handles name+items correctly.
        if (
            not pending
            and intent_result.slots.get("source") in ("intent", "price")
            and _looks_like_new_order_entry(msg)
        ):
            _nm = re.match(r"^([A-Za-z][a-z'\-]+ [A-Za-z][a-z'\-]+)\b", msg.strip())
            if _nm:
                from db import tx
                from crm_store import find_customers_by_name
                consultant_id = ctx.consultant_id
                with tx() as (conn, cur):
                    _hits = find_customers_by_name(cur, consultant_id=consultant_id, name=_nm.group(1), limit=1)
                if _hits:
                    return None  # let the order parser take it

        # -------------------------
        # Exact product name match — handles data-send clicks from multi-result lists
        # -------------------------
        if intent_result.intent == "product_lookup" and intent_result.slots.get("source") == "exact":
            return ChatReply(_fmt_product_lookup_single(intent_result.slots["match"], ui=ui))

        # -------------------------
        # Product price lookup ("how much is X", "price of X") and bare
        # product names typed alone — claimed by route() with the matched
        # product_text in slots
        # -------------------------
        def _all_words_in_product(query: str, product_name: str) -> bool:
            words = [w for w in query.lower().split() if len(w) >= 2]
            name_l = product_name.lower()
            return bool(words) and all(_re.search(rf"\b{_re.escape(w)}\b", name_l) for w in words)

        if intent_result.intent == "product_lookup" and intent_result.slots.get("source") in ("bare", "price"):
            product_text = intent_result.slots.get("product_text") or msg
            if product_text:
                if intent_result.slots["source"] == "bare":
                    # Word match first — more precise for bare product names
                    word_matches = [c for c in catalog if _all_words_in_product(product_text, c["product_name"])]
                    if len(word_matches) == 1:
                        m = word_matches[0]
                        return ChatReply(_fmt_product_lookup_single(m, ui=ui))
                    elif len(word_matches) > 1:
                        lines = [f"<strong>{ui['product_lookup_header']}</strong>"]
                        for m in word_matches[:3]:
                            lines.append(_fmt_product_list_item(m))
                        if len(word_matches) > 3:
                            remaining = len(word_matches) - 3
                            lines.append(f'<a href="#" data-send="show all {product_text}">+{remaining} more</a>')
                        return ChatReply("<br>".join(lines))
                    # Word match found nothing — fall back to fuzzy
                    matches = best_matches(catalog, product_text, limit=3, min_score=70)
                    if matches:
                        top = matches[0]
                        if len(matches) == 1 or float(top.get("score") or 0) >= 80:
                            return ChatReply(_fmt_product_lookup_single(top, ui=ui))
                        lines = [f"<strong>{ui['product_lookup_header']}</strong>"]
                        for m in matches:
                            lines.append(_fmt_product_list_item(m))
                        return ChatReply("<br>".join(lines))
                else:
                    # Explicit price query — fuzzy only
                    matches = best_matches(catalog, product_text, limit=3, min_score=50)
                    if not matches or float(matches[0].get("score") or 0) < 70:
                        # Weak whole-string match — the ask may name several products
                        multi = multi_product_lookup(catalog, product_text, ui=ui)
                        if multi:
                            return ChatReply(multi)
                    if matches:
                        top = matches[0]
                        if len(matches) == 1 or float(top.get("score") or 0) >= 80:
                            return ChatReply(_fmt_product_lookup_single(top, ui=ui))
                        lines = [f"<strong>{ui['product_lookup_header']}</strong>"]
                        for m in matches:
                            lines.append(_fmt_product_list_item(m))
                        return ChatReply("<br>".join(lines))
                    return ChatReply("I couldn't find that product in the catalog. Try a different name or part of the name.")

        # -------------------------
        # Product price lookup (intent-based fallback)
        # -------------------------
        if not pending and intent_result.intent == "product_lookup" and intent_result.slots.get("source") == "intent":
            product_text = intent_result.slots.get("product_query") or _parse_product_price_query_text(msg)
            matches = best_matches(catalog, product_text, limit=3, min_score=50)
            if not matches or int(matches[0].get("score") or 0) < 70:
                # Weak whole-string match — the ask may name several products
                multi = multi_product_lookup(catalog, product_text, ui=ui)
                if multi:
                    return ChatReply(multi)
            if not matches:
                if re.search(r',', product_text):
                    return ChatReply("I can look up one product at a time — try searching for each one separately.")
                return ChatReply("I couldn't find that product in the catalog. Try a different name or part of the name.")
            top = matches[0]
            top_score = int(top.get("score") or 0)
            runner_up_score = int(matches[1].get("score") or 0) if len(matches) > 1 else 0
            confident = len(matches) == 1 or (top_score >= 80 and (top_score - runner_up_score) >= 15)
            if confident:
                return ChatReply(_fmt_product_lookup_single(top, ui=ui))
            lines = [f"<strong>{ui['product_lookup_header']}</strong>"]
            for m in matches:
                lines.append(_fmt_product_list_item(m))
            return ChatReply("\n".join(lines))
        return None

    def _intent_inventory_count(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        catalog = ctx.catalog
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Inventory: quantity count query ("how many X do I have")
        # -------------------------
        if intent_result.intent == "inventory_count":
            product_text = intent_result.slots.get("product_text") or _parse_inventory_lookup_text(msg)
            if product_text:
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
                            "kind": "inventory_count_confirm_top",
                            "product_text": product_text,
                            "top": top,
                            "matches": matches[:MATCH_LIMIT],
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(propose_top(top, current_qty=1, ui=ui))
                sku = (chosen.get("sku") or "").strip()
                with tx() as (conn, cur):
                    row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                return ChatReply(_format_inventory_item(row, chosen, product_text))
        return None

    def _intent_inventory_show(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        catalog = ctx.catalog
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Inventory: show full list
        # -------------------------
        if intent_result.intent == "inventory_show":
            with tx() as (conn, cur):
                rows = list_inventory(cur, consultant_id=consultant_id)
            return ChatReply(_format_inventory_list(rows, catalog))
        return None

    def _intent_inventory_low_stock(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        catalog = ctx.catalog
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Inventory: low stock / what should I order
        # -------------------------
        if intent_result.intent == "inventory_low_stock":
            from inventory_store import list_low_stock, has_any_thresholds
            with tx() as (conn, cur):
                if not has_any_thresholds(cur, consultant_id=consultant_id):
                    return ChatReply(
                        "You haven't set any desired on-hand levels yet.\n"
                        "Try: \"keep 3 charcoal mask on hand\" and I'll track that for you."
                    )
                rows = list_low_stock(cur, consultant_id=consultant_id)
            return ChatReply(_format_low_stock_list(rows, catalog))
        return None

    def _intent_inventory_threshold(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        catalog = ctx.catalog
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Inventory: set desired on-hand threshold
        # -------------------------
        if intent_result.intent == "inventory_threshold":
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
        return None

    def _intent_inventory_write(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        catalog = ctx.catalog
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Inventory commands (add/remove/set)
        # -------------------------
        if intent_result.intent == "inventory_write":
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
                        reply = ui["inventory_added"].format(qty=qty, product=product_name, current=current_qty)
                    elif action == "remove":
                        reply = ui["inventory_removed"].format(qty=qty, product=product_name, current=current_qty)
                    else:
                        reply = ui["inventory_set"].format(product=product_name, qty=qty, current=current_qty)

                return ChatReply(reply)
        return None

    def _intent_inventory_help(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        intent_result = ctx.intent_result

        # Mentioned inventory but nothing above parsed a command — show help
        # (moved to ui_text 2026-07-06 so ES consultants get Spanish)
        if intent_result.intent == "inventory_help":
            return ChatReply(ctx.ui["inventory_help"])
        return None

    def _intent_delete_customer(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        intent_result = ctx.intent_result
        import re
        from db import tx
        from crm_store import find_customers_by_name
        from crm_store import get_customer_by_id
        from crm_store import count_orders_for_customer

        # (_looks_like_full_customer_entry moved to intent_router.py — imported at top)

        # -------------------------
        # CRM: delete customer (local only)
        # -------------------------
        if intent_result.intent == "delete_customer":
                target = intent_result.slots.get("target", "")

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
                            f"Type DELETE to confirm, or <strong>cancel</strong>."
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
                        f"Type DELETE to confirm, or <strong>cancel</strong>."
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

                return ChatReply(render_customer_delete_picker(top, recent_orders_map, ui=ui))
        return None

    def _intent_referral(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        import os as _os

        ##
        # -------------------------
        # Referral link
        # -------------------------
        if intent_result.intent == "referral":
            import os as _os
            _ref_base = (_os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
            from db import tx as _rtx
            with _rtx() as (_rc, _rcur):
                from db import is_postgres as _risp
                _RPH = "%s" if _risp() else "?"
                _rcur.execute(f"SELECT referral_code FROM consultants WHERE id={_RPH}", (consultant_id,))
                _rrow = _rcur.fetchone()
                _rcode = ((_rrow[0] if _rrow else None) or "").strip()
            if _rcode and _ref_base:
                _ref_link = f"{_ref_base}/r/{_rcode}"
                return ChatReply(
                    f'Your referral link: <a href="{_ref_link}" target="_blank">{_ref_link}</a>&nbsp; '
                    f'<button class="fdp-copy copy-link-btn" data-copy="{_ref_link}">Copy Link</button>'
                )
            return ChatReply('Find your referral link in <a href="/settings">Settings</a>.')
        return None

    def _intent_submitted_order_edit(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        ui = ctx.ui
        intent_result = ctx.intent_result

        # -------------------------
        # Add/remove against an already-submitted order — can't be changed from
        # chat; educate and point at MyCustomers (syncs back automatically)
        # -------------------------
        if intent_result.intent == "submitted_order_edit":
            if intent_result.slots.get("action") == "add":
                return ChatReply(ui["submitted_order_add"])
            return ChatReply(ui["submitted_order_edit"])
        return None

    def _intent_order_remove(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result

        # LLM-classified remove-from-order with no draft open — same reply.
        # (Previously fell through to the normal parse, which started a
        # phantom order draft — live incident 2026-07-02.)
        if not pending and intent_result.intent == "order_remove":
            return ChatReply(ui["submitted_order_edit"])
        return None

    def _intent_edit_request(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        intent_result = ctx.intent_result

        # -------------------------
        # Customer edit requests — not supported, redirect to InTouch
        # (covers both the keyword-classified intent and the text rule)
        # -------------------------
        if intent_result.intent == "edit_request":
            return ChatReply(
                'Changes or updates to customer information must currently be done from '
                '<a href="https://apps.marykayintouch.com/customer-list" target="_blank">MyCustomers</a>. '
                'The changes will then show in MyPinkAssistant on the next sync.'
            )
        return None

    # --- feature-help bubbles (2026-07-06): one fixed ui_text bubble each;
    # routed by the _feature_help_intent gate + LLM long tail ---
    def _intent_order_help(self, ctx) -> Optional[ChatReply]:
        if ctx.intent_result.intent == "order_help":
            return ChatReply(ctx.ui["order_help"])
        return None

    def _intent_followup_help(self, ctx) -> Optional[ChatReply]:
        if ctx.intent_result.intent == "followup_help":
            return ChatReply(ctx.ui["followup_help"])
        return None

    def _intent_sync_help(self, ctx) -> Optional[ChatReply]:
        if ctx.intent_result.intent == "sync_help":
            return ChatReply(ctx.ui["sync_help"])
        return None

    def _intent_billing_help(self, ctx) -> Optional[ChatReply]:
        if ctx.intent_result.intent == "billing_help":
            return ChatReply(ctx.ui["billing_help"])
        return None

    def _intent_privacy_help(self, ctx) -> Optional[ChatReply]:
        if ctx.intent_result.intent == "privacy_help":
            return ChatReply(ctx.ui["privacy_help"])
        return None

    def _intent_notes_educate(self, ctx) -> Optional[ChatReply]:
        """'add a note to X' — notes aren't supported yet; redirect to MyCustomers."""
        ui = ctx.ui
        intent_result = ctx.intent_result

        if intent_result.intent == "notes_educate":
            return ChatReply(ui["notes_educate"])
        return None

    def _intent_mycustomers_link(self, ctx) -> Optional[ChatReply]:
        """'link to mycustomers' / 'mycustomers link' / 'link to intouch' /
        'open mycustomers' — the clickable MyCustomers link, styled like look_book."""
        ui = ctx.ui
        intent_result = ctx.intent_result

        if intent_result.intent == "mycustomers_link":
            return ChatReply(ui["mycustomers_link"])
        return None

    def _intent_bulk_text_educate(self, ctx) -> Optional[ChatReply]:
        """'send a reminder text to Liz Mayo, Dana Smith, ...' — MPA can't send
        texts to customers; point at the follow-up / lapsed-customer lists'
        tap-to-text buttons instead."""
        ui = ctx.ui
        intent_result = ctx.intent_result

        if intent_result.intent == "bulk_text_educate":
            return ChatReply(ui["bulk_text_educate"])
        return None

    def _intent_pcp_list(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        from db import tx

        # PCP enrolled list (no LLM call)
        # -------------------------
        if intent_result.intent == "pcp_list":
            from crm_store import get_pcp_list as _get_pcp
            from followup_store import render_pcp_cards as _render_pcp, get_pcp_completed_ids as _get_pcp_done
            with tx() as (conn, cur):
                _pcp_customers, _pcp_quarter = _get_pcp(cur, consultant_id)
                _pcp_done_ids = _get_pcp_done(cur, consultant_id, _pcp_quarter) if _pcp_quarter else set()
            if not _pcp_customers:
                return ChatReply("No PCP customers found for the current quarter.")
            _pcp_pending = len([c for c in _pcp_customers if c.get("id") not in _pcp_done_ids])
            _pcp_header = f"<strong>PCP List</strong> ({_pcp_pending} remaining · {len(_pcp_customers)} total)"
            return ChatReply(_pcp_header + "\n" + _render_pcp(_pcp_customers, _pcp_done_ids, _pcp_quarter))
        return None

    def _intent_leaderboard(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        lowered = ctx.lowered
        consultant_id = ctx.consultant_id
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx

        ##
        # -------------------------
        # CRM quick lookup: leaderboard / top customers (no LLM call)
        # -------------------------
        if not pending:
            import re

            leaderboard_triggers = (
                "leaderboard",
                "spent the most", "spend the most",
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

                with tx() as (conn, cur):
                    rows = get_top_customers(
                        cur,
                        consultant_id=consultant_id,
                        limit=n,
                        start_date=start_date,
                        end_date=end_date,
                    )

                return ChatReply(format_leaderboard(rows, title))
        return None

    def _intent_top_sellers(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Top sellers
        # -------------------------
        if intent_result.intent == "top_sellers":
            from crm_store import get_top_sellers
            from datetime import datetime as _datetime, timezone, timedelta

            timeframe = (intent_result.slots or {}).get("timeframe")
            now = _datetime.now(timezone.utc)
            if timeframe == "month":
                since = now - timedelta(days=30)
                label = "this month"
            elif timeframe == "quarter":
                since = now - timedelta(days=90)
                label = "this quarter"
            elif timeframe == "year":
                since = now - timedelta(days=365)
                label = "this year"
            elif timeframe == "all_time":
                since = None
                label = "all time"
            else:
                since = now - timedelta(days=365)
                label = "the last 12 months"

            with tx() as (conn, cur):
                rows = get_top_sellers(cur, consultant_id=consultant_id, limit=5, since=since)

            if not rows:
                return ChatReply(f"No order history found for {label}.")

            lines = [f"<strong>Your Top Sellers</strong> ({label})"]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. {r['product_name']} — {r['total_qty']} units")
            return ChatReply("<br>".join(lines))
        return None

    def _intent_birthday_lookup(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        lowered = ctx.lowered
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Lapsed customers (no LLM call)
        # -------------------------
        # Birthday period lookup
        # -------------------------
        if intent_result.intent == "birthday_lookup":
            _bday_period = intent_result.slots.get("period")

            if _bday_period:
                from crm_store import get_customers_by_birthday_period as _gbp
                from crm_store import get_unit_members_by_birthday_period as _gbp_unit
                from followup_store import render_birthday_search_cards as _rbsc
                from auth_core import get_consultant_full as _gcf2
                from db import tx
                _consultant_first = ((_gcf2(consultant_id) or {}).get("first_name") or "").strip()

                # Scope: customers-only, consultants-only, or both (default)
                if "consultant" in lowered or "team" in lowered:
                    _bday_scope = "consultants"
                elif "customer" in lowered:
                    _bday_scope = "customers"
                else:
                    _bday_scope = "both"

                with tx() as (conn, cur):
                    _bday_results = []
                    if _bday_scope in ("customers", "both"):
                        _bday_results += _gbp(consultant_id, _bday_period, cur)
                    if _bday_scope in ("consultants", "both"):
                        _bday_results += _gbp_unit(consultant_id, _bday_period, cur)
                _bday_results.sort(key=lambda r: r["days_until"])

                _period_labels = {
                    "today": "today", "tomorrow": "tomorrow",
                    "month": "this month", "week": "this week", "next_week": "next week",
                    "quarter": "this quarter", "upcoming": "the next 30 days", "next_month": "next month",
                }
                _period_label = _period_labels.get(_bday_period, _bday_period)
                if _bday_period.startswith("month:"):
                    # Named month ("birthdays in July") — weed-garden 2026-07-11
                    import calendar as _cal_bd
                    _period_label = f"in {_cal_bd.month_name[int(_bday_period.split(':', 1)[1])]}"

                if not _bday_results:
                    _empty_who = {"customers": "customers", "consultants": "consultants", "both": "customers or consultants"}[_bday_scope]
                    return ChatReply(f"No {_empty_who} with birthdays {_period_label}.")

                _scope_label = {"customers": "Customer ", "consultants": "Consultant ", "both": ""}[_bday_scope]
                _header = f"<strong>{_scope_label}Birthdays {_period_label.title()}</strong>"
                _show_all = lowered.startswith("show all birthdays")
                _limit = None if _show_all else 5
                return ChatReply(_header + "\n" + _rbsc(_bday_results, _consultant_first, limit=_limit, period_label=_period_label, scope=_bday_scope))
        return None

    def _intent_lapsed_customers(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        lowered = ctx.lowered
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx

        # -------------------------
        # Lapsed customers (route() maps "show all lapsed N days" here too and
        # suppresses product-search phrasings like "who are my retinol customers")
        if not pending and intent_result.intent == "lapsed_customers":
            import re as _re_lapsed
            from crm_store import get_lapsed_customers, format_lapsed_customers

            # "show all lapsed N days" — expand the overflow list
            _show_all = bool(re.match(r"show all lapsed \d+ days", lowered))

            # Parse months or days from the message ("in 3 months", "in one month", "in 90 days", "lately" → 90 days default)
            _word_nums = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,
                          "seven":7,"eight":8,"nine":9,"ten":10,"twelve":12}
            _days = 90
            _m_months = _re_lapsed.search(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s*month", lowered)
            _m_days   = _re_lapsed.search(r"(\d+)\s*day", lowered)
            if _m_months:
                _raw = _m_months.group(1)
                _days = (_word_nums.get(_raw) or int(_raw)) * 30
            elif _m_days:
                _days = int(_m_days.group(1))

            with tx() as (conn, cur):
                result = get_lapsed_customers(cur, consultant_id=consultant_id, days=_days)

            state["pending"] = None
            save_session_state(state, session_id=sid)

            if _show_all:
                # Full plain list of the overflow customers
                rest = result.get("rest") or []
                months = _days // 30
                period = f"{months} month{'s' if months != 1 else ''}" if _days % 30 == 0 else f"{_days} days"
                if not rest:
                    return ChatReply(f"No additional lapsed customers beyond the top 5.")
                lines = [f"All lapsed customers ({period}+):"]
                for r in rest:
                    name = f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
                    d = int(r.get("days_since") or 0)
                    m = round(d / 30)
                    age = f"{m} month{'s' if m != 1 else ''} ago" if m >= 2 else f"{d} days ago"
                    lines.append(f"• {name} — {age}")
                return ChatReply("\n".join(lines))

            return ChatReply(format_lapsed_customers(result, _days))
        return None

    def _intent_customers_by_city(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        lowered = ctx.lowered
        consultant_id = ctx.consultant_id
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx

        # -------------------------
        # Customers by city
        # -------------------------
        if not pending and intent_result.intent == "customers_by_city":
            from crm_store import (
                get_customers_by_city, format_city_customers,
                get_customers_by_city_and_state,
                get_customers_by_state, format_state_customers, parse_city_state,
            )

            # expand overflow list
            _show_all_city = bool(re.match(r"customers\s+in\s+(.+?)\s+all$", lowered))

            city = (intent_result.slots or {}).get("city", "")
            if not city:
                # Allow commas so "Eau Claire, WI" is captured whole, not truncated at the comma
                _cm = re.search(r"\bcustomers?\s+(?:in|from)\s+([A-Za-z][A-Za-z\s.',\-]+?)(?:\s+all)?\s*\??$", lowered)
                if not _cm:
                    _cm = re.match(r"^(?:my\s+)?([A-Za-z][A-Za-z\s.',\-]+?)\s+customers?\b", lowered)
                city = _cm.group(1).strip().title() if _cm else ""
            # Strip "city:" / "city :" label prefix if consultant typed it literally
            city = re.sub(r"^city\s*:\s*", "", city, flags=re.IGNORECASE).strip()
            if _show_all_city:
                _cm2 = re.match(r"customers\s+in\s+(.+?)\s+all$", lowered)
                if _cm2:
                    city = _cm2.group(1).strip().title()

            if not city:
                return ChatReply("This looks like a city/state lookup. Try \"customers in Madison\" or \"customers in Madison, WI\"")

            # Guard: the LLM sometimes hands over a garbage "city" extracted
            # from a non-city question ("Who Are My" — live 2026-07-03, echoed
            # back as 'No customers found in Who Are My.'). If the city
            # contains obvious question/name words, coach instead of querying.
            _CITY_GARBAGE = {"who", "are", "my", "name", "named", "customer", "customers", "the", "with"}
            if any(w in _CITY_GARBAGE for w in city.lower().split()):
                return ChatReply("This looks like a city/state lookup. Try \"customers in Madison\" or \"customers in Madison, WI\"")

            _city_part, _state_abbr, _state_display = parse_city_state(city)

            if _state_abbr and _city_part:
                # City + state — e.g. "Nashville, TN" or "Austin Texas"
                _label = f"{_city_part}, {_state_display}"
                with tx() as (conn, cur):
                    rows = get_customers_by_city_and_state(cur, consultant_id=consultant_id, city=_city_part, state_abbr=_state_abbr)
                return ChatReply(format_city_customers(rows, _label, show_all=_show_all_city))
            elif _state_abbr:
                # Pure state — e.g. "Alabama" or "TX"
                with tx() as (conn, cur):
                    rows = get_customers_by_state(cur, consultant_id=consultant_id, state_abbr=_state_abbr)
                return ChatReply(format_state_customers(rows, _state_display, show_all=_show_all_city))
            else:
                # Pure city
                with tx() as (conn, cur):
                    rows = get_customers_by_city(cur, consultant_id=consultant_id, city=_city_part)
                if not rows:
                    # No city match — try as a product search (e.g. "timewise customers", "repair customers")
                    from crm_store import find_customers_by_product, format_customers_by_product
                    _city_filler = {"who", "are", "my", "show", "list", "find", "get", "all",
                                    "any", "have", "has", "which", "what", "the", "a", "i",
                                    "is", "of", "new", "other", "please", "give", "me"}
                    _ptokens = [w for w in _city_part.lower().split() if len(w) > 1 and w not in _city_filler]
                    if _ptokens:
                        with tx() as (conn, cur):
                            _prod_rows = find_customers_by_product(cur, consultant_id=consultant_id, terms=_ptokens)
                        if _prod_rows:
                            return ChatReply(format_customers_by_product(_prod_rows, _city_part))
                return ChatReply(format_city_customers(rows, _city_part, show_all=_show_all_city))
        return None

    def _intent_followup(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Follow-up trigger (2+2+2)
        # -------------------------
        if intent_result.intent == "followup":
            _is_more = bool(intent_result.slots.get("more"))
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
        return None

    def _intent_customers_by_product(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        from db import tx

        # -------------------------
        # Customer search by product — phrase parsing lives in route(); the
        # extracted product term / search terms arrive in slots
        # -------------------------
        if intent_result.intent == "customers_by_product":
            from crm_store import find_customers_by_product, find_customers_by_category, format_customers_by_product
            from db import tx
            _product_term = intent_result.slots.get("product_term") or ""
            terms = intent_result.slots.get("terms") or []
            _or_terms = intent_result.slots.get("or_terms")

            if _product_term and terms:
                with tx() as (conn, cur):
                    if _or_terms:
                        results = find_customers_by_category(cur, consultant_id=consultant_id, or_terms=_or_terms)
                    else:
                        results = find_customers_by_product(cur, consultant_id=consultant_id, terms=terms)
                state["pending"] = None
                save_session_state(state, session_id=sid)
                return ChatReply(format_customers_by_product(results, _product_term))
        return None

    def _intent_recent_orders(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        lowered = ctx.lowered
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx
        from crm_store import find_customers_by_name

        # -------------------------
        # CRM quick lookup: recent orders lookup (no LLM call)
        # -------------------------
        if not pending:
            if intent_result.intent == "recent_orders":
                    import re, calendar as _cal
                    from datetime import date as _date
                    from crm_store import format_recent_orders

                    # --- 1. Date range parsing (runs first so matched text can be scrubbed
                    #        from the message before name extraction) ---
                    _start_date: str | None = None
                    _end_date: str | None = None
                    _period_label: str | None = None
                    _date_scrub = ""  # exact matched text to remove before name extraction

                    _MONTHS = {
                        "jan": 1, "january": 1, "feb": 2, "february": 2,
                        "mar": 3, "march": 3, "apr": 4, "april": 4,
                        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                        "aug": 8, "august": 8, "sep": 9, "september": 9,
                        "oct": 10, "october": 10, "nov": 11, "november": 11,
                        "dec": 12, "december": 12,
                    }
                    _today = _date.today()
                    _mp = "|".join(_MONTHS.keys())

                    _m_my = re.search(rf"\b({_mp})\.?\s+(20\d{{2}})\b", lowered)
                    _m_yr = re.search(r"\b(20\d{2})\b", lowered)

                    if _m_my:
                        _mo = _MONTHS[_m_my.group(1)]; _yr = int(_m_my.group(2))
                        _last_day = _cal.monthrange(_yr, _mo)[1]
                        _start_date = f"{_yr}-{_mo:02d}-01"
                        _end_date   = f"{_yr}-{_mo:02d}-{_last_day}"
                        _period_label = f"{_m_my.group(1).capitalize()} {_yr}"
                        _date_scrub = _m_my.group(0)
                    elif _m_yr:
                        _yr = int(_m_yr.group(1))
                        _start_date = f"{_yr}-01-01"
                        _end_date   = f"{_yr}-12-31"
                        _period_label = str(_yr)
                        _date_scrub = _m_yr.group(0)
                    elif "this month" in lowered:
                        _start_date = _today.replace(day=1).isoformat()
                        _end_date   = _today.isoformat()
                        _period_label = _today.strftime("%B %Y")
                        _date_scrub = "this month"
                    elif "last month" in lowered:
                        _ft = _today.replace(day=1)
                        _lmo = (_ft.month - 2) % 12 + 1
                        _lyr = _ft.year if _ft.month > 1 else _ft.year - 1
                        _start_date = f"{_lyr}-{_lmo:02d}-01"
                        _end_date   = f"{_lyr}-{_lmo:02d}-{_cal.monthrange(_lyr, _lmo)[1]}"
                        _period_label = _date(_lyr, _lmo, 1).strftime("%B %Y")
                        _date_scrub = "last month"
                    elif "this year" in lowered:
                        _start_date = f"{_today.year}-01-01"
                        _end_date   = _today.isoformat()
                        _period_label = str(_today.year)
                        _date_scrub = "this year"
                    elif "last year" in lowered:
                        _start_date = f"{_today.year - 1}-01-01"
                        _end_date   = f"{_today.year - 1}-12-31"
                        _period_label = str(_today.year - 1)
                        _date_scrub = "last year"

                    # --- 2. Limit ---
                    _WORD_NUMS = {
                        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                    }
                    limit = 999 if _start_date else 3
                    _m_lim = re.search(r"\blast\s+(\d+)\s+orders?\b", lowered)
                    _m_lim_word = re.search(
                        rf"\blast\s+({'|'.join(_WORD_NUMS)})\s+orders?\b", lowered
                    )
                    if _m_lim:
                        limit = max(1, min(10, int(_m_lim.group(1))))
                    elif _m_lim_word:
                        limit = _WORD_NUMS[_m_lim_word.group(1)]
                    elif "last order" in lowered or "latest order" in lowered:
                        limit = 1
                    elif "all" in lowered:
                        limit = 999

                    # --- 3. Name extraction — scrub matched date text first so month
                    #        names belonging to the date don't pollute the name guess ---
                    # "what [product] does [name] use/wear/buy" — the name sits between
                    # "does" and the verb, so capture it directly instead of relying on
                    # the token heuristic (which pulls the product word into one-word names)
                    _m_use = re.search(r"\b(?:what|which)\b.*\bdoes\s+(\w+(?:\s+\w+)?)\s+(?:use|wear|buy|order)\b", lowered)
                    _msg_for_name = re.sub(re.escape(_date_scrub), " ", msg, flags=re.IGNORECASE).strip() if _date_scrub else msg
                    if _m_use:
                        _msg_for_name = _m_use.group(1)
                    m_clean = re.sub(r"[^\w\s']", " ", _msg_for_name).strip()
                    stop_words = {
                        "last", "recent", "show", "lookup", "order", "orders", "history",
                        "for", "on", "in", "info", "information", "what", "is", "whats", "what's",
                        "me", "please", "customer", "was", "did", "do", "does",
                        "ordered", "latest", "all", "buy", "bought", "purchase", "purchased",
                        "have", "has", "had", "this", "the", "a",
                        "use", "uses", "wear", "wears",  # "what cleanser does jane use"
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
                        if t.lower() in ("day", "days", "week", "weeks", "month", "months", "year", "years"):
                            continue
                        if t.lower() in _WORD_NUMS:
                            continue
                        if t.lower() not in stop_words:
                            tokens.append(t)

                    guess = " ".join(tokens[-2:]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
                    if not _is_plausible_name_guess(guess):
                        guess = ""
                    guess = _resolve_pronoun_guess(guess, state) or (state.get("last_ref_customer_name") or "").strip()
                    if not guess:
                        # No plausible name left after filtering stopwords/verbs
                        # (e.g. "what was the last foundation ordered?" with no
                        # name) and no pronoun context to fall back on — ask
                        # instead of guessing the whole message as a "name".
                        return ChatReply(ui["who_is_customer"])

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
                                "orders_limit": limit,
                                "orders_start_date": _start_date,
                                "orders_end_date": _end_date,
                                "orders_period_label": _period_label,
                            }
                            save_session_state(state, session_id=sid)

                            return ChatReply(render_customer_picker(top, ui=ui))

                        c = matches[0]
                        customer_id = int(c["id"])
                        customer_name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()

                        orders = get_recent_orders_for_customer(
                            cur, customer_id=customer_id, limit=limit,
                            start_date=_start_date, end_date=_end_date,
                        )

                    return ChatReply(format_recent_orders(customer_name, orders, period_label=_period_label))
        return None

    def _intent_customer_spend(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        lowered = ctx.lowered
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx
        from crm_store import find_customers_by_name

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
                if not _is_plausible_name_guess(guess):
                    guess = ""
                guess = _resolve_pronoun_guess(guess, state) or (state.get("last_ref_customer_name") or "").strip()
                if not guess:
                    # No plausible name left after filtering stopwords/verbs
                    # (e.g. "can you calculate totals or discounts?") and no
                    # pronoun context to fall back on — ask instead of guessing
                    # the whole message as a "name".
                    return ChatReply(ui["who_is_customer"])

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

                        return ChatReply(render_customer_picker(top, ui=ui))

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
        return None

    def _intent_cancel(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        sid = ctx.sid
        state = ctx.state
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result

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
        return None

    def _intent_app_help(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        intent_result = ctx.intent_result

        # (edit_request handled earlier, next to the other redirect rules)

        # App install help (moved to ui_text 2026-07-06 so ES consultants get Spanish)
        if intent_result.intent == "app_help":
            return ChatReply(ctx.ui["app_help"])
        return None

    def _intent_chat_help(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        consultant_id = ctx.consultant_id
        intent_result = ctx.intent_result
        ui = ctx.ui
        from db import tx

        # Chat help — what can I do
        if intent_result.intent == "chat_help":
            with tx() as (conn, cur):
                cur.execute(
                    f"SELECT 1 FROM unit_members WHERE consultant_id = {PH} LIMIT 1",
                    (consultant_id,),
                )
                has_team = cur.fetchone() is not None
            return ChatReply(_build_chat_help_html(has_team, ui=ui))
        return None

    def _intent_unit_query(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result

        # -------------------------
        # Unit query (team/unit member text-to-SQL)
        # -------------------------
        if not pending and intent_result.intent == "unit_query":
            return _handle_unit_query(msg, consultant_id, ui=ui)
        return None

    def _intent_car_program(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        consultant_id = ctx.consultant_id
        pending = ctx.pending
        intent_result = ctx.intent_result
        ui = ctx.ui

        # -------------------------
        # Car program status (director feature)
        # -------------------------
        if not pending and intent_result.intent == "car_program":
            return _handle_car_program(consultant_id, msg=msg, ui=ui)
        return None

    def _intent_customer_info(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result
        import re
        from db import tx
        from crm_store import find_customers_by_name
        from crm_store import format_customer_card

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
                    _msg_norm = msg.replace('’', "'").replace('‘', "'")
                    m_clean = re.sub(r"[^\w\s']", " ", _msg_norm).strip()
        

                    stop_words = {
                        "what", "is", "whats", "what's", "info", "information", "for", "on",
                        "lookup", "show", "me", "please", "customer", "customers",
                        "email", "phone", "number", "address", "birthday", "bday",
                        "can", "you", "could", "tell", "give", "find", "get", "pull", "see",
                        "i", "my", "the", "a", "an", "do", "would",
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
                    if not _is_plausible_name_guess(guess):
                        guess = ""
                    guess = _resolve_pronoun_guess(guess, state)
                    if not guess:
                        return ChatReply(ui['who_is_customer'])

                    with tx() as (conn, cur):
                        matches = find_customers_by_name(cur, consultant_id=consultant_id, name=guess, limit=10)
                        last_order = None
                        pcp_enrolled = False
                        if len(matches) == 1:
                            orders = get_recent_orders_for_customer(cur, matches[0]["id"], limit=1)
                            last_order = orders[0] if orders else None
                            from crm_store import get_pcp_enrolled
                            pcp_enrolled = get_pcp_enrolled(cur, consultant_id, matches[0]["id"])

                    if len(matches) == 0:
                        # Fallback: search unit_members if this consultant has team data
                        from crm_store import find_unit_member_by_name, format_consultant_card as _fmt_cons
                        with tx() as (_uc, _ucur):
                            _unit_matches = find_unit_member_by_name(_ucur, consultant_id, guess)
                        if _unit_matches:
                            if len(_unit_matches) == 1:
                                return ChatReply(_fmt_cons(_unit_matches[0]))
                            cards = "\n\n".join(_fmt_cons(m) for m in _unit_matches[:3])
                            return ChatReply(cards)
                        return ChatReply(ui["no_customer_found_yet"].format(name=guess))

                    # Check if name also matches a unit_member — show disambiguation if so
                    _unit_matches = []
                    from crm_store import find_unit_member_by_name as _find_um
                    with tx() as (_uc, _ucur):
                        _unit_matches = _find_um(_ucur, consultant_id, guess)

                    if len(matches) == 1:
                        c = matches[0]
                        if _unit_matches:
                            um = _unit_matches[0]
                            c_last = (c.get('last_name') or '').strip().lower()
                            u_last = (um.get('last_name') or '').strip().lower()
                            c_full = f"{c.get('first_name','')} {c.get('last_name','')}".strip().lower()
                            u_full = f"{um.get('first_name','')} {um.get('last_name','')}".strip().lower()
                            same_person = (c_last and c_last == u_last) or c_full == u_full

                            safe_c = _html.escape(f"{c.get('first_name','')} {c.get('last_name','')}".strip())
                            safe_u = _html.escape(f"{um.get('first_name','')} {um.get('last_name','')}".strip())
                            phone_hint = _html.escape(format_phone_display(c.get("phone") or ""))
                            cust_detail = f' <span class="select-detail">• {phone_hint}</span>' if phone_hint else ""
                            um_level = _html.escape(um.get("career_level_desc") or "")
                            um_status = _html.escape(um.get("activity_status") or "")
                            um_parts = [p for p in (um_level, um_status) if p]
                            cons_detail = f' <span class="select-detail">• {" • ".join(um_parts)}</span>' if um_parts else ""

                            if same_person:
                                # Same person appears as both customer and consultant;
                                # also append any other unit members with the same first name
                                _extra_cons_rows = []
                                for _i, _um2 in enumerate(_unit_matches[1:], start=3):
                                    _su2 = _html.escape(f"{_um2.get('first_name','')} {_um2.get('last_name','')}".strip())
                                    _ul2 = _html.escape(_um2.get("career_level_desc") or "")
                                    _us2 = _html.escape(_um2.get("activity_status") or "")
                                    _up2 = [p for p in (_ul2, _us2) if p]
                                    _cd2 = f' <span class="select-detail">• {" • ".join(_up2)}</span>' if _up2 else ""
                                    _extra_cons_rows.append(
                                        f'<div class="select-row" data-send="team member {_su2}"><span class="select-num">{_i}</span>'
                                        f'<span class="select-text">{_su2} — Consultant{_cd2}</span></div>'
                                    )
                                state["pending"] = {"kind": "pick_customer", "candidates": [c], "action": "info"}
                                save_session_state(state, session_id=sid)
                                return ChatReply(
                                    f'<div class="select-intro">I found these options — which did you mean?</div>'
                                    f'<div class="select-list">'
                                    f'<div class="select-row" data-send="1"><span class="select-num">1</span>'
                                    f'<span class="select-text">{safe_c} — Customer{cust_detail}</span></div>'
                                    f'<div class="select-row" data-send="team member {safe_u}"><span class="select-num">2</span>'
                                    f'<span class="select-text">{safe_u} — Consultant{cons_detail}</span></div>'
                                    + "".join(_extra_cons_rows)
                                    + f'</div>'
                                )
                            else:
                                # Different people matched the query — show as neutral picker
                                state["pending"] = {"kind": "pick_customer", "candidates": [c], "action": "info"}
                                save_session_state(state, session_id=sid)
                                _cons_rows = []
                                for _i, _um in enumerate(_unit_matches[:3], start=2):
                                    _su = _html.escape(f"{_um.get('first_name','')} {_um.get('last_name','')}".strip())
                                    _ul = _html.escape(_um.get("career_level_desc") or "")
                                    _us = _html.escape(_um.get("activity_status") or "")
                                    _up = [p for p in (_ul, _us) if p]
                                    _cd = f' <span class="select-detail">• {" • ".join(_up)}</span>' if _up else ""
                                    _cons_rows.append(
                                        f'<div class="select-row" data-send="team member {_su}"><span class="select-num">{_i}</span>'
                                        f'<span class="select-text">{_su} — Consultant{_cd}</span></div>'
                                    )
                                _total = 1 + len(_cons_rows)
                                return ChatReply(
                                    f'<div class="select-intro">I found multiple matches — reply with 1 or {_total}:</div>'
                                    f'<div class="select-list">'
                                    f'<div class="select-row" data-send="1"><span class="select-num">1</span>'
                                    f'<span class="select-text">{safe_c} — Customer{cust_detail}</span></div>'
                                    + "".join(_cons_rows)
                                    + f'</div>'
                                )
                        state["last_ref_customer_id"] = None
                        state["last_ref_customer_name"] = None
                        state["last_customer"] = None
                        save_session_state(state, session_id=sid)
                        return ChatReply(format_customer_card(c, last_order=last_order, pcp_enrolled=pcp_enrolled))

                    # Multiple customer matches — append consultant row if name also matches a unit_member
                    top = matches[:3]
                    state["pending"] = {"kind": "pick_customer", "candidates": top, "action": "info"}
                    save_session_state(state, session_id=sid)
                    picker_html = render_customer_picker(
                        top,
                        intro=ui["render_customer_multi_intro"].format(n=len(top) + 1)
                        if _unit_matches else "",
                        ui=ui,
                    )
                    if _unit_matches:
                        _extra_rows = []
                        for _i, _um in enumerate(_unit_matches[:3], start=len(top) + 1):
                            _su = _html.escape(f"{_um.get('first_name','')} {_um.get('last_name','')}".strip())
                            _ul = _html.escape(_um.get("career_level_desc") or "")
                            _us = _html.escape(_um.get("activity_status") or "")
                            _up = [p for p in (_ul, _us) if p]
                            _cd = f' <span class="select-detail">• {" • ".join(_up)}</span>' if _up else ""
                            _extra_rows.append(
                                f'<div class="select-row" data-send="team member {_su}">'
                                f'<span class="select-num">{_i}</span>'
                                f'<span class="select-text">{_su} — Consultant{_cd}</span></div>'
                            )
                        # Append all consultant rows before the closing </div>
                        _insert = picker_html.rfind("</div>")
                        picker_html = picker_html[:_insert] + "".join(_extra_rows) + picker_html[_insert:]
                    return ChatReply(picker_html)
        return None

    def _handle_pending(self, ctx) -> Optional[ChatReply]:
        """Mid-conversation flows (order confirm, pickers, inventory
        confirms, ...) — body moved verbatim from handle_message (step 4).
        Returns None to fall through to normal parse, as before."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        catalog = ctx.catalog
        last_customer = ctx.last_customer
        pending = ctx.pending
        show_scores = ctx.show_scores
        import re
        from db import tx
        from crm_store import format_customer_card
        from crm_store import count_orders_for_customer
        from crm_store import delete_customer_local

        # -------------------------
        # Pending flows
        # -------------------------
        if pending:
            kind = pending.get("kind")

###

            if kind == "pick_customer":
                # user should reply 1/2/3
                choice = (msg or "").strip()

                # "team member …" means the user tapped the consultant option in a
                # customer/consultant disambiguation picker — clear pending and re-route
                if choice.lower().startswith("team member "):
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return self.handle_message(msg, consultant_id=consultant_id, session_id=sid)

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
                        from crm_store import get_pcp_enrolled
                        pcp_enrolled = get_pcp_enrolled(cur, consultant_id, c["id"])
                    last_order = orders[0] if orders else None
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    state["last_customer"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(format_customer_card(c, last_order=last_order, pcp_enrolled=pcp_enrolled))

                if action == "orders":
                    with tx() as (conn, cur):
                        limit = int(pending.get("orders_limit") or 3)
                        _sd = pending.get("orders_start_date")
                        _ed = pending.get("orders_end_date")
                        _pl = pending.get("orders_period_label")
                        orders = get_recent_orders_for_customer(
                            cur, customer_id=customer_id, limit=limit,
                            start_date=_sd, end_date=_ed,
                        )
                    state["last_ref_customer_id"] = None
                    state["last_ref_customer_name"] = None
                    state["last_customer"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(format_recent_orders(customer_name, orders, period_label=_pl))

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
                        f"Type DELETE to confirm, or <strong>cancel</strong>."
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

                    # Drop any items whose text is just a customer name token —
                    # happens when the LLM mistakes a last name for a product
                    # (e.g. "Order for Carrie Alloy" → items=["alloy"])
                    _cust_tokens = {
                        t.lower() for t in [
                            (c.get("first_name") or "").strip(),
                            (c.get("last_name") or "").strip(),
                        ] if t
                    }
                    if _cust_tokens:
                        order_draft["lines"] = [
                            ln for ln in order_draft.get("lines", [])
                            if ln.get("text", "").strip().lower() not in _cust_tokens
                        ]

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

                        state["pending"] = self._pending_for_top(order_draft, nxt, top, matches)
                        save_session_state(state, session_id=sid)
                        return ChatReply(propose_top(top, current_qty=order_draft["lines"][nxt]["qty"], ui=ui, original_text=order_draft["lines"][nxt].get("text")))

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

            if kind == "inventory_count_confirm_top":
                top = pending["top"]
                matches = pending.get("matches") or []

                if yes(msg):
                    sku = (top.get("sku") or "").strip()
                    with tx() as (conn, cur):
                        row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                    state["pending"] = None
                    save_session_state(state, session_id=sid)
                    return ChatReply(_format_inventory_item(row, top, pending.get("product_text", "")))

                if no(msg):
                    state["pending"] = {
                        "kind": "inventory_count_pick_top5",
                        "product_text": pending.get("product_text", ""),
                        "matches": matches,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches, show_scores=show_scores, ui=ui))

                return ChatReply(ui["reply_yes_no"])

            if kind == "inventory_count_pick_top5":
                choice = (msg or "").strip()
                matches = pending.get("matches") or []

                if not choice.isdigit():
                    return ChatReply(ui["pick_match_5"])

                idx = int(choice)
                if idx < 1 or idx > min(TOP5, len(matches)):
                    return ChatReply(ui["pick_match_5"])

                chosen = matches[idx - 1]
                sku = (chosen.get("sku") or "").strip()
                with tx() as (conn, cur):
                    row = get_inventory_item(cur, consultant_id=consultant_id, sku=sku)
                state["pending"] = None
                save_session_state(state, session_id=sid)
                return ChatReply(_format_inventory_item(row, chosen, pending.get("product_text", "")))

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
                            "Please type <strong>cancel</strong> and re-enter the customer with the full name."
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
                        _orig = (order["lines"][line_index].get("text") or "that product").strip()
                        return ChatReply(
                            f"I couldn't find \"{_orig}\" in the catalog. "
                            "Try rewording it (brand, line, or shade helps), say <strong>skip</strong> to skip this item, or <strong>cancel</strong> to start over."
                        )
                    order["lines"][line_index]["chosen"] = top
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

                if no(msg):
                    if not matches:
                        _orig = (order["lines"][line_index].get("text") or "that product").strip()
                        state["pending"] = {
                            "kind": "order_line_pick_top5_or_search",
                            "order": order,
                            "line_index": line_index,
                            "matches": [],
                        }
                        save_session_state(state, session_id=sid)
                        return ChatReply(
                            f"I couldn't find \"{_orig}\" in the catalog. "
                            "Try rewording it (brand, line, or shade helps), say <strong>skip</strong> to skip this item, or <strong>cancel</strong> to start over."
                        )
                    state["pending"] = {
                        "kind": "order_line_pick_top5_or_search",
                        "order": order,
                        "line_index": line_index,
                        "matches": matches[:MATCH_LIMIT],
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_top5(matches, show_scores=show_scores, ui=ui, skip_hint=True))

                if _wants_to_skip(msg):
                    order["lines"][line_index]["chosen"] = {"sku": "", "_skipped": True}
                    state["pending"] = None
                    return self._continue_resolving_and_reply(state, order, consultant_id, sid, catalog, ui)

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

                if _wants_to_skip(msg):
                    order["lines"][line_index]["chosen"] = {"sku": "", "_skipped": True}
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
                return ChatReply(render_top5(new_matches, show_scores=show_scores, ui=ui, skip_hint=True))

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
                except Exception as _openai_err:
                    print(f"[OpenAI] awaiting_order_items parse failed for consultant_id={consultant_id}: {_openai_err}")
                    items = []
                if not items:
                    qty, item_text = parse_qty_prefix(msg.strip())
                    items = [{"text": item_text, "qty": qty}] if item_text else []
                # modifiers can arrive with the items reply too ("one powder, 20% off")
                from .order_parse import extract_order_modifiers as _eom
                order_draft = self._make_order_draft(
                    cust_first, cust_last, items, fulfillment_method, leave_pending,
                    modifiers=_eom(msg), tax_rate=self._get_tax_rate(consultant_id))
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

                # "add 20% off" / "add 7% sales tax" is a MODIFIER, not an item —
                # fall through to the modifier block below instead of item-parsing
                # it ("20% off" fuzzy-matched Illuminea; local test 2026-07-18).
                from .order_parse import is_pure_modifier_item as _ipmi
                if action == "add" and rest and _ipmi(rest):
                    action, rest = None, ""

                if action == "add":
                    if not rest:
                        return ChatReply(ui["add_hint"])
                    # Parse items through OpenAI same as initial order entry so multi-item
                    # text without commas works (e.g. "add cc cream timewise cleanser satin hands")
                    cust_first = order.get("customer", {}).get("First Name", "")
                    cust_last  = order.get("customer", {}).get("Last Name", "")
                    try:
                        _add_parsed = parse_with_openai(self.client, f"order for {cust_first} {cust_last}: {rest}", last_customer)
                    except Exception as _openai_err:
                        print(f"[OpenAI] add_items parse failed for consultant_id={consultant_id}: {_openai_err}")
                        _add_parsed = {}
                    _add_items = (_add_parsed.get("order") or {}).get("items") or []
                    if not _add_items:
                        # Fallback: treat whole rest as single item
                        qty, item_text = parse_qty_prefix(rest)
                        _add_items = [{"text": item_text, "qty": qty}] if item_text else []
                    if not _add_items:
                        return ChatReply(ui["add_hint"])
                    from .order_parse import strip_modifier_text as _smt, extract_order_modifiers as _eom_add
                    for it in _add_items:
                        item_text = (it.get("text") or "").strip()
                        if item_text and _eom_add(item_text):
                            item_text = _smt(item_text)  # clean "mask $5 off" → "mask"
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
                    # Strip leading count: "2 apple and almond lotion" → count=2, target="apple and almond lotion"
                    # Word numbers count too — "remove one dark brunette" failed while
                    # "remove 1 lash love fanorama" worked (weed-garden 2026-07-08, c92+c114).
                    _remove_count = 1
                    _count_m = re.match(
                        r'^(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(.+)$',
                        target, re.IGNORECASE,
                    )
                    if _count_m:
                        _cw = _count_m.group(1).lower()
                        _word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                                      "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
                        _remove_count = max(1, int(_cw)) if _cw.isdigit() else _word_nums[_cw]
                        target = _count_m.group(2).strip()
                    # Only reject "and"/"," if the name itself doesn't match an order line
                    # (product names like "apple and almond" contain "and" legitimately)
                    _has_conjunction = bool(re.search(r'\band\b|,', target, re.IGNORECASE))
                    if _has_conjunction and not self._remove_line_peek(order, target):
                        return ChatReply(
                            "I can only remove one item at a time. Which one would you like to remove first?\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )
                    _removed_count = 0
                    for _ in range(_remove_count):
                        if self._remove_line(order, target):
                            _removed_count += 1
                        else:
                            break
                    if not _removed_count and _count_m:
                        # The stripped "count" may actually be part of the product
                        # name ("3 in 1 cleanser") — retry the untouched text once.
                        if self._remove_line(order, _count_m.group(0).strip()):
                            _removed_count = 1
                    if not _removed_count:
                        return ChatReply(
                            ui["remove_not_found"] + "\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )
                    state["pending"] = {"kind": "order_confirm", "order": order}
                    save_session_state(state, session_id=sid)
                    return ChatReply(self._format_order_confirm(order, ui) + "\n\n" + ui["order_adjust_hint"])

                # ✅ Date change (before guardrail so it isn't blocked)
                _date_text = _parse_order_date_cmd(msg)
                if _date_text is not None:
                    _parsed_date = _parse_date_value(_date_text)
                    if _parsed_date:
                        order["order_date"] = _parsed_date
                        state["pending"] = {"kind": "order_confirm", "order": order}
                        save_session_state(state, session_id=sid)
                        return ChatReply(self._format_order_confirm(order, ui) + "\n\n" + ui["order_adjust_hint"])
                    else:
                        return ChatReply(
                            "I couldn't read that date. Try something like `date 5/4/26` or `date May 4`.\n\n"
                            + self._format_order_confirm(order, ui) + "\n\n"
                            + ui["order_adjust_hint"]
                        )

                # ✅ Discount/tax mid-confirm — APPLY (2026-07-18, MK shipped the
                # MyCustomers discount fields; verified live via inspect_discount_fields).
                # "add 20% off" / "$5 off" / "7% sales tax" / "no tax" adjust the
                # draft and redisplay. CDS orders: the fields don't exist on that
                # form → educate (Brian's copy) instead of silently dropping.
                from .order_parse import extract_order_modifiers as _eom_mc
                _mods_mc = _eom_mc(msg)
                if _mods_mc or self._mentions_discount(msg):
                    # CDS: mods still get STORED — _order_money zeroes them and
                    # the confirm formatter shows the CDS educate (single path
                    # with the initial-message case; gap found by Brian 2026-07-18).
                    if _mods_mc:
                        if "discounts" in _mods_mc:
                            # REPLACE semantics: a new discount message swaps the
                            # whole discount set (restating never doubles it)
                            order["discount_mentions"] = _mods_mc["discounts"]
                            order["discount_type"] = _mods_mc.get("discount_type")
                            order["discount_value"] = _mods_mc.get("discount_value")
                            order["discount_requested"] = False
                        if "tax_percent_override" in _mods_mc:
                            order["tax_percent_override"] = _mods_mc["tax_percent_override"]
                            order["no_tax"] = False
                        if _mods_mc.get("no_tax"):
                            order["no_tax"] = True
                            order["tax_percent_override"] = None
                    else:
                        # discount mentioned but unparseable — can't-read educate
                        order["discount_requested"] = True
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

                    # Compute discount + tax before saving — _order_money is the
                    # single source of truth (same math the confirm displayed).
                    _money = self._order_money(order)
                    _total_discount = _money["discount_amount"]
                    _tax_amount = _money["tax_amount"]
                    _order_discounts = []
                    if _total_discount > 0:
                        _d_label = (f"{_money.get('rec_value'):g}% off"
                                    if _money.get("rec_type") == "%"
                                    else f"${_total_discount:.2f} off")
                        _order_discounts = [{"amount": _total_discount, "line_idx": None, "label": _d_label}]

                    # 1) Save order + items to CRM (permanent, even if Playwright fails)
                    # CDS orders are skipped here — left pending in InTouch for the
                    # consultant to finalize. The nightly import brings them back in
                    # their final form, avoiding stale/duplicate records.
                    from crm_store import get_customer_id_by_name, create_order_from_confirmed, upsert_customer_from_pending

                    _fulfillment = order.get("fulfillment_method", "inventory")
                    if _fulfillment != "cds":
                        with tx() as (conn, cur):
                            customer_id = order.get("customer_id")
                            if not customer_id:
                                customer_id = get_customer_id_by_name(cur, consultant_id, cust_first, cust_last)
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
                                discounts=_order_discounts,
                                tax_amount=_tax_amount,
                                discount_type=_money.get("rec_type"),
                                discount_value=_money.get("rec_value"),
                                tax_percent=(_money["tax_percent"] if _tax_amount > 0 else None),
                            )

                    # 2) Queue jobs for worker/playwright
                    _leave_pending = bool(order.get("leave_pending", False))
                    _order_date = (order.get("order_date") or "").strip() or None

                    # For CDS orders, include customer address in payload so Playwright
                    # can fill it in if InTouch reports a missing delivery address
                    _cds_address = {}
                    if _fulfillment == "cds":
                        from crm_store import get_customer_id_by_name as _get_cid_by_name
                        with tx() as (_cds_conn, _cds_cur):
                            _cds_cid = order.get("customer_id") or _get_cid_by_name(_cds_cur, consultant_id, cust_first, cust_last)
                            if _cds_cid:
                                _cds_cur.execute(
                                    f"SELECT street, city, state, postal_code FROM customers WHERE consultant_id={PH} AND id={PH} LIMIT 1",
                                    (consultant_id, int(_cds_cid)),
                                )
                                _cds_row = _cds_cur.fetchone()
                                if _cds_row:
                                    _cds_address = {
                                        "street": (_cds_row["street"] if isinstance(_cds_row, dict) else _cds_row[0]) or "",
                                        "city": (_cds_row["city"] if isinstance(_cds_row, dict) else _cds_row[1]) or "",
                                        "state": normalize_state((_cds_row["state"] if isinstance(_cds_row, dict) else _cds_row[2]) or ""),
                                        "postal_code": (_cds_row["postal_code"] if isinstance(_cds_row, dict) else _cds_row[3]) or "",
                                    }

                    _first_job = True
                    for line in order["lines"]:
                        sku = (line["chosen"].get("sku") or "").strip()
                        if not sku:
                            continue
                        qty = int(line["qty"])
                        for _ in range(max(1, qty)):
                            payload = {
                                "First Name": cust_first,
                                "Last Name": cust_last,
                                "SKU": sku,
                                "fulfillment_method": _fulfillment,
                                "leave_pending": _leave_pending,
                                "order_date": _order_date,
                            }
                            if _cds_address:
                                payload.update(_cds_address)
                            if _first_job and (_total_discount > 0 or _tax_amount > 0):
                                # first job of the batch carries the order-level
                                # modifiers; process_order_batch reads rows[0].
                                # tax goes as the RATE — MK's field is a percent.
                                payload["discount_amount"] = _total_discount
                                payload["tax_percent"] = _money["tax_percent"]
                            insert_job(
                                "NEW_ORDER_ROW",
                                payload,
                                consultant_id=consultant_id,
                            )
                            _first_job = False

                    # 3) Decrement personal inventory for each ordered item (skip for CDS)
                    if _fulfillment != "cds":
                        with tx() as (conn, cur):
                            for line in order["lines"]:
                                sku = (line["chosen"].get("sku") or "").strip()
                                if not sku:
                                    continue
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
        return None

    def _intent_data_query(self, ctx) -> Optional[ChatReply]:
        """Handler body moved verbatim from handle_message (step 4).
        Returns None to decline — fall through to pending flow / normal parse."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        pending = ctx.pending
        intent_result = ctx.intent_result

        # -------------------------
        # CRM data query (text-to-SQL fallback for cross-customer searches)
        # -------------------------
        if not pending and intent_result.intent == "data_query":
            return _handle_data_query(msg, consultant_id, ui=ui)
        return None

    def _normal_parse(self, ctx) -> ChatReply:
        """Nothing claimed the message — OpenAI order/customer parser.
        Body moved verbatim from handle_message (step 4). Always replies."""
        # (step 4) generated unpack of shared per-message context
        msg = ctx.msg
        lowered = ctx.lowered
        sid = ctx.sid
        state = ctx.state
        consultant_id = ctx.consultant_id
        ui = ctx.ui
        catalog = ctx.catalog
        last_customer = ctx.last_customer
        import re as _re
        from db import tx
        from crm_store import find_customers_by_name

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
        except Exception as _openai_err:
            print(f"[OpenAI] parse_with_openai failed for consultant_id={consultant_id}: {_openai_err}")
            return ChatReply(ui["trouble"])

        if parsed.get("type") == "customer":
            customer = parsed.get("customer") or {}

            # If no name was parsed, prompt them to provide full info.
            _first = (customer.get("First Name") or "").strip()
            _last = (customer.get("Last Name") or "").strip()
            if not _first and not _last:
                return ChatReply(ui["need_customer_info"])

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
            # Discount/tax in the initial order text? Extract and APPLY (2026-07-18).
            # The LLM parser ignores modifier phrasing, so extract from raw msg.
            # _disc_req survives as the safety net: a discount MENTION that
            # extraction couldn't parse → can't-read educate on the confirm
            # instead of a silent drop (weed-garden 2026-07-13 bug class).
            from .order_parse import extract_order_modifiers, is_pure_modifier_item
            _order_mods = extract_order_modifiers(msg)
            _disc_req = self._mentions_discount(msg) and not _order_mods.get("discounts")
            _cons_tax_rate = self._get_tax_rate(consultant_id)

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
                elif is_pure_modifier_item(item_text):
                    # modifier text the parser emitted as an "item" ("20% off",
                    # "7% sales tax") — already captured in _order_mods; without
                    # this it fuzzy-matches a random product (2026-07-18).
                    pass
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

            _PRONOUNS = {"she", "he", "they", "her", "him", "them"}

            if cust_first.lower() in _PRONOUNS or cust_last.lower() in _PRONOUNS or cust_last.lower() == "ordered":
                return ChatReply(ui["need_customer_for_order"])

            customer_name_for_lookup = " ".join([p for p in [cust_first, cust_last] if p]).strip()

            if not customer_name_for_lookup:
                if fulfillment_method == "cds":
                    return ChatReply('To create a CDS order, type: <strong>New CDS order for [customer name]</strong> and then tell me the products.')
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
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending, discount_requested=_disc_req, modifiers=_order_mods, tax_rate=_cons_tax_rate)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3], ui=ui))

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
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending, discount_requested=_disc_req, modifiers=_order_mods, tax_rate=_cons_tax_rate)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3], ui=ui))

                else:
                    # Full name typed, multiple fuzzy matches, none exact — show picker
                    items = order.get("items") or []
                    if not items and explicit_item_hint:
                        items = [{"text": explicit_item_hint, "qty": 1}]
                    order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending, discount_requested=_disc_req, modifiers=_order_mods, tax_rate=_cons_tax_rate)
                    order_draft["order_date"] = (order.get("order_date") or "").strip()
                    state["pending"] = {
                        "kind": "pick_customer",
                        "candidates": matches[:3],
                        "action": "order_customer_pick",
                        "order_draft": order_draft,
                    }
                    save_session_state(state, session_id=sid)
                    return ChatReply(render_customer_picker(matches[:3], ui=ui))

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

            order_draft = self._make_order_draft(cust_first, cust_last, items, fulfillment_method, leave_pending, discount_requested=_disc_req, modifiers=_order_mods, tax_rate=_cons_tax_rate)
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

                state["pending"] = self._pending_for_top(order_draft, nxt, top, matches)
                save_session_state(state, session_id=sid)
                prefix = ui["got_it_ordering_for"].format(name=customer_line)
                return ChatReply(f"{prefix}\n{propose_top(top, current_qty=order_draft['lines'][nxt]['qty'], ui=ui, original_text=order_draft['lines'][nxt].get('text'))}")

            # CDS orders require an address — hard block before showing confirm
            if fulfillment_method == "cds" and not self._customer_has_address(consultant_id, order_draft.get("customer_id")):
                cust_name = f"{cust_first} {cust_last}".strip()
                return ChatReply(
                    f"CDS orders ship directly to the customer, so {cust_name} needs an address on file in "
                    f"<a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a> before this order can be placed. "
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

    # ------------------------------------------------------------------
    # Dispatch table (step 4) — intent name -> handler method name.
    # One entry per dispatchable intent; intents absent here (new_order,
    # order_add, new_customer, unknown, ...) fall through to the pending
    # flow / normal parse. show_all_products is special-cased inline in
    # handle_message because it answers before intent logging.
    # ------------------------------------------------------------------
    _INTENT_DISPATCH = {
        "look_book": "_intent_look_book",
        "order_of_application": "_intent_order_of_application",
        "set_sales_tax": "_intent_set_sales_tax",
        "inventory_guardrail": "_intent_inventory_guardrail",
        "inventory_print": "_intent_inventory_print",
        "product_lookup": "_intent_product_lookup",
        "inventory_count": "_intent_inventory_count",
        "inventory_show": "_intent_inventory_show",
        "inventory_low_stock": "_intent_inventory_low_stock",
        "inventory_threshold": "_intent_inventory_threshold",
        "inventory_write": "_intent_inventory_write",
        "inventory_help": "_intent_inventory_help",
        "delete_customer": "_intent_delete_customer",
        "referral": "_intent_referral",
        "submitted_order_edit": "_intent_submitted_order_edit",
        "order_remove": "_intent_order_remove",
        "edit_request": "_intent_edit_request",
        "notes_educate": "_intent_notes_educate",
        "mycustomers_link": "_intent_mycustomers_link",
        "bulk_text_educate": "_intent_bulk_text_educate",
        "order_help": "_intent_order_help",
        "followup_help": "_intent_followup_help",
        "sync_help": "_intent_sync_help",
        "billing_help": "_intent_billing_help",
        "privacy_help": "_intent_privacy_help",
        "pcp_list": "_intent_pcp_list",
        "leaderboard": "_intent_leaderboard",
        "top_sellers": "_intent_top_sellers",
        "birthday_lookup": "_intent_birthday_lookup",
        "lapsed_customers": "_intent_lapsed_customers",
        "customers_by_city": "_intent_customers_by_city",
        "followup": "_intent_followup",
        "customers_by_product": "_intent_customers_by_product",
        "recent_orders": "_intent_recent_orders",
        "customer_spend": "_intent_customer_spend",
        "cancel": "_intent_cancel",
        "app_help": "_intent_app_help",
        "chat_help": "_intent_chat_help",
        "unit_query": "_intent_unit_query",
        "car_program": "_intent_car_program",
        "customer_info": "_intent_customer_info",
        "data_query": "_intent_data_query",
    }

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

            state["pending"] = self._pending_for_top(order, nxt, top, matches)
            save_session_state(state, session_id=sid)
            return ChatReply(propose_top(top, current_qty=order["lines"][nxt]["qty"], ui=ui, original_text=order["lines"][nxt].get("text")))

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
        referred_by = (customer.get("Referred By") or "").strip()
        referred_by_line = f"• Referred By: {referred_by}\n" if referred_by else ""

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
            f"{referred_by_line}"
            f"{ui['cust_confirm_q']}\n"
            f"{ui['cust_edit_hint']}"
            + _QR_YN
        )


    @staticmethod
    def _mentions_discount(text: str) -> bool:
        """Detect a discount/percent mention in an order message. Since 2026-07-18
        discounts APPLY (extract_order_modifiers); this remains the safety net —
        a mention that extraction could NOT parse gets the can't-read educate on
        the confirm screen instead of being silently dropped (the original
        2026-07-13 Wendy bug class). Tax spans are stripped first: "7% sales tax"
        is a tax request, not a discount (weed-garden 2026-07-17 F3)."""
        t = (text or "").lower()
        t = re.sub(r"\d+(?:\.\d+)?\s*%\s*(?:sales\s+)?(?:tax|impuesto)\b", " ", t)
        t = re.sub(r"(?:sales\s+tax|tax|impuesto(?:\s+de\s+ventas)?)(?:\s+rate)?\s+(?:of|de|at|to|is|a)?\s*\d+(?:\.\d+)?\s*%", " ", t)
        return bool(re.search(r"\bdiscount(?:ed|s)?\b|\bpercent\b|\d+\s*%|%\s*off\b|\b\d+(?:\.\d+)?\s*(?:%|percent|dollars?|\$)?\s*off\b|\$\s*\d+(?:\.\d+)?\s*off\b", t))

    def _get_tax_rate(self, consultant_id: int) -> float:
        """Consultant's saved sales tax rate (consultants.tax_rate), 0 if unset."""
        try:
            from db import tx as _tx
            with _tx() as (conn, cur):
                cur.execute(f"SELECT tax_rate FROM consultants WHERE id = {PH}", (consultant_id,))
                row = cur.fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _order_money(order: dict) -> dict:
        """One source of truth for order math (confirm display AND save/queue).
        Discount clamps: % capped at 100, $ capped at the subtotal (MK's own
        field limits). Tax base = DISCOUNTED subtotal (verify vs MK's computed
        display in the live test; adjust here if MK taxes pre-discount).
        CDS orders never get discount/tax — the fields don't exist on that form.
        Returns {subtotal, discount_amount, tax_percent, tax_amount, grand_total}."""
        subtotal = 0.0
        for ln in order.get("lines") or []:
            chosen = ln.get("chosen") or {}
            if chosen.get("_skipped"):
                continue
            price = chosen.get("price")
            if price is not None and str(price).strip():
                try:
                    subtotal += float(price) * max(1, int(ln.get("qty") or 1))
                except Exception:
                    pass

        if order.get("fulfillment_method") == "cds":
            return {"subtotal": round(subtotal, 2), "discount_amount": 0.0,
                    "tax_percent": 0.0, "tax_amount": 0.0,
                    "grand_total": round(subtotal, 2),
                    "rec_type": None, "rec_value": None,
                    "discount_over_total": False, "notes": []}

        # ---- discount: resolve mentions (item-scoped %/$ summed to one flat
        # total — MK has a single order-level field) or fall back to the legacy
        # single type/value fields. 2026-07-18 two-discount fix: "charcoal mask
        # at 20% off, repair set at $100 off" = 20%×mask + $100 (item-capped),
        # NOT 20%×whole-order with the $100 dropped.
        notes: list[str] = []
        mentions = order.get("discount_mentions") or []
        if mentions:
            def _line_total(ln):
                try:
                    return float((ln.get("chosen") or {}).get("price") or 0) * max(1, int(ln.get("qty") or 1))
                except Exception:
                    return 0.0

            def _match_line(target: str):
                """Fuzzy-match a mention target to an order line (None = order-level)."""
                if not target:
                    return None
                try:
                    from rapidfuzz import fuzz as _fz
                except Exception:
                    return None
                best, best_score = None, 0
                for ln in order.get("lines") or []:
                    chosen = ln.get("chosen") or {}
                    if chosen.get("_skipped"):
                        continue
                    name = (chosen.get("product_name") or ln.get("text") or "")
                    s = _fz.token_set_ratio(target.lower(), name.lower())
                    if s > best_score:
                        best, best_score = ln, s
                return best if best_score >= 70 else None

            discount = 0.0
            for men in mentions:
                ln = _match_line(men.get("target") or "")
                base = _line_total(ln) if ln is not None else subtotal
                if men["type"] == "%":
                    part = round(base * min(float(men["value"]), 100.0) / 100.0, 2)
                else:
                    part = float(men["value"])  # no per-item cap (Brian 2026-07-18)
                discount += part
            discount = round(discount, 2)
            if len(mentions) == 1 and mentions[0]["type"] == "%" and not mentions[0].get("target"):
                rec_type, rec_value = "%", float(mentions[0]["value"])
            else:
                rec_type, rec_value = "$", discount
        else:
            d_type = order.get("discount_type")
            d_value = float(order.get("discount_value") or 0)
            if d_type == "%":
                d_value = min(d_value, 100.0)
                discount = round(subtotal * d_value / 100.0, 2)
                rec_type, rec_value = "%", d_value
            elif d_type == "$":
                discount = round(d_value, 2)
                rec_type, rec_value = "$", discount
            else:
                discount = 0.0
                rec_type, rec_value = None, None

        # Over-total rule (Brian 2026-07-18): if the summed discounts exceed the
        # retail total, apply NONE of them — the confirm says so and she can
        # re-enter the discount before confirming. (Replaces the per-item cap.)
        discount_over_total = False
        if discount > subtotal:
            discount = 0.0
            rec_type, rec_value = None, None
            discount_over_total = True

        if order.get("no_tax"):
            pct = 0.0
        elif order.get("tax_percent_override") is not None:
            pct = min(float(order["tax_percent_override"]), 100.0)
        else:
            pct = min(float(order.get("tax_rate") or 0), 100.0)
        tax = round((subtotal - discount) * pct / 100.0, 2) if pct > 0 else 0.0

        return {"subtotal": round(subtotal, 2), "discount_amount": discount,
                "tax_percent": pct, "tax_amount": tax,
                "grand_total": round(subtotal - discount + tax, 2),
                "rec_type": rec_type if discount > 0 else None,
                "rec_value": rec_value if discount > 0 else None,
                "discount_over_total": discount_over_total,
                "notes": notes}

    def _make_order_draft(self, cust_first: str, cust_last: str, items: List[dict], fulfillment_method: str = "inventory", leave_pending: bool = False, discount_requested: bool = False, modifiers: dict = None, tax_rate: float = 0.0) -> dict:
        from .order_parse import extract_order_modifiers as _eom_d, strip_modifier_text
        lines = []
        for it in items:
            text = (it.get("text") or "").strip()
            if not text:
                continue
            if _eom_d(text):
                # modifier text inside the item ("repair set $50 off") wrecks
                # catalog scores (93→55, Go Set outranked the real sets) —
                # strip it; a pure modifier ("20% off") strips to nothing and
                # the line is dropped entirely (both Brian 2026-07-18).
                text = strip_modifier_text(text)
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
            "discount_requested": discount_requested,
            # discount/tax modifiers (2026-07-18): set from extract_order_modifiers
            # at draft time or mid-confirm; consumed by _order_money.
            # discount_mentions = full list incl. item targets ("mask at 20% off");
            # legacy type/value only for a single untargeted mention.
            "discount_mentions": modifiers.get("discounts") if modifiers else None,
            "discount_type": modifiers.get("discount_type") if modifiers else None,
            "discount_value": modifiers.get("discount_value") if modifiers else None,
            "tax_percent_override": modifiers.get("tax_percent_override") if modifiers else None,
            "no_tax": bool(modifiers.get("no_tax")) if modifiers else False,
            "tax_rate": tax_rate,  # consultant's saved rate, snapshotted at draft time
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
            chosen = line.get("chosen") or {}
            if chosen.get("_skipped"):
                continue

            qty = int(line.get("qty") or 1)
            if qty < 1:
                qty = 1

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
            "If the order fails, please open the customer in "
            "<a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>, "
            "confirm the name and address details, and try again."
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
            except Exception as _date_err:
                print(f"[OrderDate] date parse failed for value '{order_date_str}': {_date_err}")

        total = 0.0
        any_prices = False

        preview_lines = self._aggregate_lines_for_preview(order)

        # Build a map: original line index -> preview line index for per-item discounts
        # (preview_lines may aggregate duplicates; we match on name)
        discounts = order.get("discounts") or []
        per_item_discounts: dict[str, float] = {}  # product_name -> discount amount
        order_level_discount = 0.0
        for d in discounts:
            if d.get("line_idx") is not None:
                raw_lines = order.get("lines") or []
                if d["line_idx"] < len(raw_lines):
                    chosen = raw_lines[d["line_idx"]].get("chosen") or {}
                    pname = chosen.get("product_name") or raw_lines[d["line_idx"]].get("text") or ""
                    per_item_discounts[pname] = per_item_discounts.get(pname, 0) + d["amount"]
            else:
                order_level_discount += d["amount"]

        for pl in preview_lines:
            qty = int(pl["qty"])
            price = pl.get("price")

            if isinstance(price, (int, float)):
                any_prices = True
                total += float(price) * qty

            disc = per_item_discounts.get(pl["name"], 0)
            disc_str = f"  (-${disc:.2f} off)" if disc > 0 else ""
            out.append(f"• {pl['name']} {fmt_price(price)} x{qty}{disc_str}")

        # Money breakdown (2026-07-18): _order_money is the single source of
        # truth — same math the yes-path saves and queues. Legacy per-item
        # "discounts" list still renders above; order-level type/value drive it.
        money = self._order_money(order)
        if any_prices:
            out.append(ui["estimated_total"].format(total=f"${money['subtotal']:.2f}"))
            if money["discount_amount"] > 0:
                if money.get("rec_type") == "%":
                    out.append(ui["order_discount_line_pct"].format(
                        rate=f"{float(money.get('rec_value') or 0):g}",
                        amount=f"${money['discount_amount']:.2f}"))
                else:
                    out.append(ui["order_discount_line"].format(
                        amount=f"${money['discount_amount']:.2f}"))
            if money.get("discount_over_total"):
                out.append(ui["discount_over_total"])
            if money["tax_amount"] > 0:
                out.append(ui["order_tax_line"].format(
                    rate=f"{money['tax_percent']:g}", amount=f"${money['tax_amount']:.2f}"))
            if money["discount_amount"] > 0 or money["tax_amount"] > 0:
                out.append(ui["order_grand_total"].format(total=f"${money['grand_total']:.2f}"))

        if fulfillment == "cds":
            # She asked for a discount/tax on a CDS order — the fields don't
            # exist on that form; say so ABOVE the finalize reminder instead of
            # silently showing full price (Brian 2026-07-18).
            if (order.get("discount_mentions") or order.get("discount_type")
                    or order.get("tax_percent_override") is not None
                    or order.get("discount_requested")):
                out.append(ui["discount_cds_educate"])
            out.append(ui["cds_finalize_reminder"])

        # Discount mentioned but unparseable — can't-read educate (the applied
        # path clears this flag; silent drops are the 2026-07-13 bug class).
        if order.get("discount_requested") and fulfillment != "cds":
            out.append(ui["discount_educate"])

        out.append(ui["order_confirm_q"])
        return "\n".join(out) + _QR_YN


    def _next_unresolved_index(self, order: dict) -> Optional[int]:
        for i, line in enumerate(order["lines"]):
            if line["chosen"] is None:
                return i
        return None

    def _pending_for_top(self, order: dict, line_index: int, top: dict, matches: list) -> dict:
        """Return the right pending state: search mode when no SKU match, confirm mode when matched."""
        if not (top.get("sku") or "").strip():
            return {"kind": "order_line_pick_top5_or_search", "order": order, "line_index": line_index, "matches": []}
        return {"kind": "order_line_confirm_top", "order": order, "line_index": line_index, "top": top, "matches": matches}

    def _start_line_resolution(self, catalog: List[dict], order: dict, line_index: int) -> Tuple[dict, List[dict], str]:
        text = order["lines"][line_index]["text"]
        matches = best_matches(catalog, text, limit=MATCH_LIMIT)
        if not matches:
            return {"sku": "", "product_name": "No close matches found", "price": None, "score": 0}, [], text
        return matches[0], matches, text

    @staticmethod
    def _name_matches(target: str, name: str) -> bool:
        """
        Flexible name match for remove: normalize & → and, then check
        substring first, then all-words fallback for cases where the
        catalog name has extra words (e.g. 'Scented', 'Mary Kay').
        Target punctuation is stripped — voice-to-text inserts commas
        ("precision, brow, liner, dark, brunette") — and the all-words
        fallback tolerates light word-form drift ("cleanser" ≈ "cleansing")
        via a shared ≥5-char stem (weed-garden 2026-07-08, c92+c114).
        """
        t = target.lower().replace(' & ', ' and ').replace('&', 'and')
        t = re.sub(r"[,.;:!]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        n = (name or "").lower().replace(' & ', ' and ').replace('&', 'and')
        if t in n:
            return True

        def _stem(w: str) -> str:
            # crude, tight: cleansing→cleans, cleanser→cleans, wipes→wipe
            for suf in ("ing", "er", "s"):
                if w.endswith(suf) and len(w) - len(suf) >= 4:
                    return w[: len(w) - len(suf)]
            return w

        name_words = re.sub(r"[^a-z0-9 ]+", " ", n).split()

        def _word_ok(w: str) -> bool:
            if w in n:
                return True
            ws = _stem(w)
            return len(ws) >= 5 and any(_stem(nw) == ws for nw in name_words)

        # All-words fallback: every word in the target appears in the name
        words = [w for w in t.split() if len(w) > 2]
        return bool(words) and all(_word_ok(w) for w in words)

    def _remove_line_peek(self, order: dict, target: str) -> bool:
        """Return True if target matches any line — without removing it."""
        if not (target or "").strip():
            return False
        for line in order["lines"]:
            chosen = line.get("chosen")
            name = chosen.get("product_name") if chosen else (line.get("text") or "")
            if self._name_matches(target, name):
                return True
        return False

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

        for i, line in enumerate(order["lines"]):
            chosen = line.get("chosen")
            name = chosen.get("product_name") if chosen else (line.get("text") or "")
            if self._name_matches(t, name):
                order["lines"].pop(i)
                return True

        return False
