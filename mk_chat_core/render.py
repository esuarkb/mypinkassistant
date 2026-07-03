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
        _label = f'"{original_text}"' if original_text else "that product"
        return (
            f"I couldn't find {_label} in the catalog. "
            "Try rewording it (brand, line, or shade helps), say <strong>skip</strong> to skip this item, or <strong>cancel</strong> to start over."
        ) + _QR_YN
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
    )


def render_top5(matches: List[dict], show_scores: bool = False, ui: dict = None, skip_hint: bool = False) -> str:
    if ui is None:
        ui = UI_EN
    top = matches[:TOP5]
    n = len(top)
    reply_range = "1" if n == 1 else f"1-{n}"
    if skip_hint:
        intro = "Got it — select the best match, try different search words, or say <strong>skip</strong> to move on."
    else:
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
        intro = f"I found multiple customer matches — reply with 1-{n}:"
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


def _looks_like_inventory_add(msg: str) -> bool:
    s = (msg or "").strip().lower()
    return "inventory" in s and (s.startswith("add ") or s.startswith("remove ") or s.startswith("set "))

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

# Routing predicates/parsers (_PRODUCT_QUERY_SYNONYMS, price-query,
# inventory count/write/bare-write/lookup-text) moved to intent_router.py
# (routing consolidation 2026-07-02); imported back at the top of this file.

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
        name = (cat.get("product_name") or "").strip()
        if not name:
            continue  # skip unmatched SKUs (samples, discontinued items not in catalog)
        retail = cat.get("price")
        retail_txt = fmt_price(retail)

        if retail_txt:
            lines.append(f"• {name} {retail_txt} — {qty} on hand")
        else:
            lines.append(f"• {name} — {qty} on hand")

    if not shown_any:
        return "We have not yet added any items to your inventory."

    return "\n".join(lines)


def _format_inventory_item(row: dict | None, catalog_item: dict | None, requested_text: str) -> str:
    name = (catalog_item or {}).get("product_name") or requested_text
    if not row:
        return f"You have 0 {name} in inventory."
    qty = int(row.get("qty_on_hand") or 0)
    return f"You have {qty} {name} in inventory."


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


# -------------------------
# App install help
# -------------------------

def _build_chat_help_html(has_team: bool, lang: str = "en") -> str:
    if lang == "es":
        lines = [
            "<strong>Aquí hay algunas cosas que puedes hacer en el chat:</strong>\n",
            "<strong>Clientes</strong>",
            "• Buscar un cliente — solo escribe su nombre: <em>Jane Doe</em>",
            "• Agregar un cliente — <em>Nuevo cliente Jane Doe, 555-1234, jane@gmail.com</em>",
            "• Qué ordenó alguien — <em>¿Qué ordenó Jane?</em>\n",
            "<strong>Pedidos</strong>",
            "• Hacer un pedido — <em>Pedido para Jane: 2 labiales y una base</em>",
            "• Buscar un producto y precio — <em>Satin hands</em> o <em>¿Cuánto cuesta la mascarilla de carbón?</em>\n",
            "<strong>Tus clientes</strong>",
            "• Por ciudad — <em>Clientes en Houston</em>",
            "• Sin pedidos recientes — <em>¿Quién no ha ordenado en 3 meses?</em>",
            "• Mejores compradoras — <em>¿Cuáles son mis mejores clientes?</em>",
            "• Cumpleaños — <em>¿Quién cumple años este mes?</em>\n",
            "<strong>Inventario</strong>",
            "• Verificar existencias — <em>¿Cuántas mascarillas de carbón tengo?</em>",
            "• Establecer mínimo — <em>Set charcoal mask par to 3</em>\n",
            "<strong>Otro</strong>",
            "• Look Book actual — <em>Look book</em>",
            "• Tu enlace de referido — <em>Mi enlace de referido</em>",
        ]
        if has_team:
            lines += [
                "\n<strong>Tu equipo</strong>",
                "• <em>¿Quiénes son mis consultoras?</em>",
                "• <em>¿Quién no ha configurado MyShop?</em>",
                "• <em>¿Quién está cerca de un paquete Gran Inicio?</em>",
                "• <em>¿Quién es el equipo de Sarah?</em>",
            ]
    else:
        lines = [
            "<strong>Here are some things you can do in chat:</strong>\n",
            "<strong>Customers</strong>",
            "• Look up a customer — just type their name: <em>Jane Doe</em>",
            "• Add a customer — <em>New customer Jane Doe, 555-1234, jane@gmail.com</em>",
            "• What someone ordered — <em>What did Jane order</em>\n",
            "<strong>Orders</strong>",
            "• Place an order — <em>Order for Jane: 2 lipsticks and a foundation</em>",
            "• Look up a product & price — <em>Satin hands</em> or <em>How much is the charcoal mask</em>\n",
            "<strong>Your customers</strong>",
            "• By city — <em>Customers in Huntsville</em>",
            "• Lapsed — <em>Who hasn't ordered in 3 months</em>",
            "• Top spenders — <em>Who are my top customers</em>",
            "• Birthdays — <em>Who has birthdays this month</em>\n",
            "<strong>Inventory</strong>",
            "• Check stock — <em>How many TimeWise moisturizers do I have</em>",
            "• Set a par — <em>Set charcoal mask par to 3</em>\n",
            "<strong>Other</strong>",
            "• Current Look Book — <em>Look book</em>",
            "• Your referral link — <em>My referral link</em>",
        ]
        if has_team:
            lines += [
                "\n<strong>Your team</strong>",
                "• <em>Who is on my team</em>",
                "• <em>Who hasn't set up MyShop</em>",
                "• <em>Who is close to a Great Start bundle</em>",
                "• <em>Who is on Sarah's team</em>",
            ]
    return "\n".join(lines)


_APP_HELP_HTML = (
    "<strong>Add MPA to your home screen</strong>\n\n"
    "<strong>iPhone / iPad (Safari):</strong>\n"
    "1. Tap the <strong>Share</strong> button (box with arrow) at the bottom of the screen\n"
    "2. Scroll down and tap <strong>Add to Home Screen</strong>\n"
    "3. Tap <strong>Add</strong> — done!\n\n"
    "<strong>Android (Chrome):</strong>\n"
    "1. Tap the <strong>⋮ menu</strong> in the top-right corner\n"
    "2. Tap <strong>Add to Home Screen</strong> or <strong>Install App</strong>\n"
    "3. Tap <strong>Add</strong> — done!\n\n"
    "Once installed it opens full-screen with no browser bar, just like a real app."
)


# -------------------------
# Unit Query (text-to-SQL for team/unit member data)
# -------------------------
