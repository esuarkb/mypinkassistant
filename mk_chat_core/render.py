"""HTML rendering for chat replies: pickers, match proposals, inventory
lists, help pages. No routing, no DB writes.
"""
import html as _html
import re
from typing import List, Optional

from .catalog import fmt_price
from .config import TOP5
from .normalize import birthday_display, format_phone_display
from .ui_text import UI_EN


def propose_top(top: dict, current_qty: int, ui: dict = None, original_text: str | None = None) -> str:
    if ui is None:
        ui = UI_EN
    if not (top.get("sku") or "").strip():
        _label = f'"{original_text}"' if original_text else ui["propose_top_no_match_default_label"]
        return ui["propose_top_no_match"].format(label=_label) + _QR_YN
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

_QR_YN_SKIP = _qr([
    {"cls": "yes",  "send": "yes",  "label": "Yes"},
    {"cls": "no",   "send": "no",   "label": "No"},
    {"cls": "skip", "send": "skip", "label": "Skip"},
])

def _wants_to_skip(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return s in (
        "skip", "skip it", "skip that", "skip that one",
        "none", "none of those", "none of them",
        "delete that", "delete that one", "remove that", "remove that one",
        "move on", "next", "forget it", "forget that", "never mind",
        # Spanish (UI_ES describes skip as "omitir este artículo" — accept the
        # words a Spanish speaker would actually type; added 2026-07-11)
        "omitir", "omitelo", "omítelo", "saltar", "salta", "siguiente",
        "ninguno", "ninguna", "ninguno de esos", "ninguna de esas",
    )


def render_top5(matches: List[dict], show_scores: bool = False, ui: dict = None, skip_hint: bool = False) -> str:
    if ui is None:
        ui = UI_EN
    top = matches[:TOP5]
    n = len(top)
    reply_range = "1" if n == 1 else f"1-{n}"
    if skip_hint:
        intro = ui["render_top5_intro_skip"]
    else:
        intro = _html.escape(ui["render_top5_intro"].format(range=reply_range))
    rows = ""
    for i, m in enumerate(top, start=1):
        name = _html.escape(m["product_name"])
        price = _html.escape(fmt_price(m.get("price")))
        score_str = f' <span class="select-score">[{int(m.get("score") or 0)}%]</span>' if show_scores else ""
        rows += f'<div class="select-row" data-send="{i}"><span class="select-num">{i}</span><span class="select-text">{name} {price}{score_str}</span></div>'
    return f'<div class="select-intro">{intro}</div><div class="select-list">{rows}</div>'

def render_customer_picker(matches: List[dict], intro: str = "", ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
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
            f'<div class="select-intro">{ui["render_customer_single_intro"]}</div>'
            f'<div class="select-list">'
            f'<div class="select-row" data-send="1"><span class="select-num">1</span>'
            f'<div class="select-text"><span>{full}</span>{detail}</div></div>'
            f'</div>{yn}'
        )

    if not intro:
        intro = ui["render_customer_multi_intro"].format(n=n)
    rows = ""
    for i, c in enumerate(top, start=1):
        full = _html.escape(f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip())
        phone_hint = _html.escape(format_phone_display(c.get("phone") or ""))
        email_hint = _html.escape((c.get("email") or "").strip())
        hint_parts = [p for p in (phone_hint, email_hint) if p]
        detail = f' <span class="select-detail">• {" • ".join(hint_parts)}</span>' if hint_parts else ""
        rows += f'<div class="select-row" data-send="{i}"><span class="select-num">{i}</span><span class="select-text">{full}{detail}</span></div>'
    return f'<div class="select-intro">{_html.escape(intro)}</div><div class="select-list">{rows}</div>'

def render_customer_delete_picker(matches: List[dict], recent_orders_map: dict[int, list[dict]], ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    top = (matches or [])[:3]
    n = len(top)
    intro = ui["render_delete_picker_intro"].format(suffix=f'-{n}' if n > 1 else '')
    rows = ""

    for i, c in enumerate(top, start=1):
        cid = int(c["id"])
        full = _html.escape(f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip())

        email = _html.escape((c.get("email") or "").strip() or ui["none"])
        phone = _html.escape(format_phone_display(c.get("phone") or "") or ui["none"])

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

        address = _html.escape(", ".join(addr_parts) if addr_parts else ui["none"])
        birthday = _html.escape(birthday_display(c.get("birthday") or "") or ui["none"])

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
            orders_html = f'<span class="delete-label">{ui["render_delete_orders_label"]}</span> {order_lines}'
        else:
            orders_html = f'<span class="delete-label">{ui["render_delete_orders_label"]}</span> {ui["render_delete_no_orders"]}'

        rows += (
            f'<div class="select-row delete-row" data-send="{i}">'
            f'<span class="select-num">{i}</span>'
            f'<div class="select-text">'
            f'<span class="delete-name">{full}</span>'
            f'<span class="delete-detail">{email} • {phone}</span>'
            f'<span class="delete-detail">{address}</span>'
            f'<span class="delete-detail">{ui["render_delete_birthday"].format(birthday=birthday)}</span>'
            f'<span class="delete-detail">{orders_html}</span>'
            f'</div></div>'
        )

    return f'<div class="select-intro">{_html.escape(intro)}</div><div class="select-list">{rows}</div>'


def _looks_like_inventory_add(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return "inventory" in s and (s.startswith("add ") or s.startswith("remove ") or s.startswith("set "))

# _inventory_help_text moved to ui_text.py (EN+ES) 2026-07-06
# Routing predicates/parsers (_PRODUCT_QUERY_SYNONYMS, price-query,
# inventory count/write/bare-write/lookup-text) moved to intent_router.py
# (routing consolidation 2026-07-02); imported back at the top of this file.

def _format_inventory_list(rows: List[dict], catalog: List[dict], ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    if not rows:
        return ui["inventory_list_empty"]

    by_sku = {str(c.get("sku") or "").strip(): c for c in catalog}
    lines = [ui["inventory_list_intro"]]

    shown_any = False

    for row in rows:
        sku = str(row.get("sku") or "").strip()
        qty = int(row.get("qty_on_hand") or 0)

        # Hide zero or negative inventory items
        if qty <= 0:
            continue

        shown_any = True

        cat = by_sku.get(sku) or {}
        name = (cat.get("product_name") or "").strip()
        if not name:
            continue  # skip unmatched SKUs (samples, discontinued items not in catalog)
        retail = cat.get("price")
        retail_txt = fmt_price(retail)

        if retail_txt:
            lines.append(ui["inventory_row_with_price"].format(name=name, price=retail_txt, qty=qty))
        else:
            lines.append(ui["inventory_row_no_price"].format(name=name, qty=qty))

    if not shown_any:
        return ui["inventory_list_none_shown"]

    return "\n".join(lines)


def _format_inventory_item(row: dict | None, catalog_item: dict | None, requested_text: str, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    name = (catalog_item or {}).get("product_name") or requested_text
    if not row:
        return ui["inventory_item_absent"].format(name=name)
    qty = int(row.get("qty_on_hand") or 0)
    return ui["inventory_item_present"].format(qty=qty, name=name)


def _format_low_stock_list(rows: list[dict], catalog: list[dict], ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    if not rows:
        return ui["low_stock_none"]

    by_sku = {str(c.get("sku") or "").strip(): c for c in catalog}
    lines = [ui["low_stock_intro"]]

    for row in rows:
        sku = str(row.get("sku") or "").strip()
        qty = int(row.get("qty_on_hand") or 0)
        threshold = int(row.get("low_stock_threshold") or 0)
        needed = threshold - qty

        cat = by_sku.get(sku) or {}
        name = (cat.get("product_name") or sku or ui["low_stock_unknown_product"]).strip()

        lines.append(ui["low_stock_row"].format(name=name, qty=qty, threshold=threshold, needed=needed))

    return "\n".join(lines)


# -------------------------
# App install help
# -------------------------

def _build_chat_help_html(has_team: bool, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    text = ui["chat_help_base"]
    if has_team:
        text += ui["chat_help_team_extra"]
    return text


# _APP_HELP_HTML moved to ui_text.py (EN+ES) 2026-07-06


# -------------------------
# Unit Query (text-to-SQL for team/unit member data)
# -------------------------
