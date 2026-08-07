"""
Customer-facing invoices for an order that already exists.

Built 2026-08-04 after a support request from a consultant asking whether she
could email a customer an invoice from the app. MyCustomers can save an order
as a PDF receipt; this is our answer to that, and it starts from a different
place than a competitor's would. QT Office builds the invoice FIRST and derives
inventory and tax reporting from it, so their invoice is a bookkeeping
primitive with write-off/return/exchange types. Ours is a VIEW of an order we
already synced from InTouch — the consultant isn't creating anything, she's
sending a copy of something that happened. Keep it that way: an invoice here
must never be the origin of a number.

PRICING — read this before changing anything.
Line prices come from the stored order_items.unit_price, falling back to the
catalog when that is 0 (see _line_price). But the SUBTOTAL IS SUMMED FROM THE
LINES, never read from orders.total. That is deliberate. Measured 2026-08-04
against production: on imported orders, line items reconcile to the stored
total 93% of the time in July 2026 and 97% in August, but only ~29% in
September 2025 — the old history predates the order-detail sync
(getOrderSummaryRecordByIds, shipped 2026-06-10) and is missing line items
outright. Printing a stored total next to lines that do not add up to it is the
one failure mode that makes a consultant look careless in front of her
customer, so the document is made internally consistent by construction. On a
recent order the two numbers agree anyway; on an old one we would rather be
self-consistent than agree with a number we cannot show the arithmetic for.

WHAT IS DELIBERATELY ABSENT:
- Shipping / payment method / payment status. MK's own receipt has all three;
  we track none of them, and a "Shipping: $0.00" line is a claim while a
  missing line is merely silent. Payment status was considered and declined
  (Brian, 2026-08-04): showing the field invites "mark Jane's invoice paid" in
  chat, which is a whole workflow, not a field.
- Satisfaction guarantee / notice of cancellation. MK prints both; ours points
  at the consultant instead. Simple first (Brian, 2026-08-04).
"""
from __future__ import annotations

import csv
import html as _html
import io
import re
from datetime import datetime
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"

# Order sources Mary Kay fulfills and bills directly — never invoiceable.
# orders.source records who PLACED the order (she did, or her customer did on
# her personal web site), not how it shipped; both of these ship from MK, who
# charges the customer their own tax and shipping. The same pair is treated as
# one thing in order_history_import_store.py's sample handling, for the same
# reason. Two consumers import this: the block_reason below, and the "Send
# invoice" link on order cards (crm_store.format_recent_orders) — they must
# agree, or she gets a button that leads to a refusal.
MK_FULFILLED_SOURCES = ("cds", "myshop")

_PRICE_CACHE: dict[str, dict[str, float]] = {}


def _catalog_prices(language: str = "en") -> dict[str, float]:
    """SKU -> current retail price, straight off the catalog CSV.

    Deliberately NOT mk_chat_core.load_catalog(): that one filters out samples
    and collateral to keep product MATCHING clean, and those rows are exactly
    the ones we still need to price (as $0.00) on an invoice.
    """
    lang = (language or "en").strip().lower()
    if lang not in ("en", "es"):
        lang = "en"
    if lang in _PRICE_CACHE:
        return _PRICE_CACHE[lang]

    prices: dict[str, float] = {}
    try:
        with open(CATALOG_DIR / f"{lang}.csv", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                sku = (row.get("sku") or "").strip()
                if not sku:
                    continue
                try:
                    prices[sku] = float(str(row.get("price") or "0").replace("$", "").strip())
                except ValueError:
                    continue
    except OSError:
        pass  # no catalog on disk — every line falls back to its stored price

    _PRICE_CACHE[lang] = prices
    return prices


def _line_price(item: dict, prices: dict[str, float]) -> float:
    """What this line costs, per unit.

    Stored price wins — it is what she actually charged. The catalog is only a
    rescue for rows the import left at 0, which is ~8% of historical line items
    and near zero on recent orders. A genuinely free item (CDS samples, gift
    with purchase) has no catalog row either, so it correctly stays $0.00.
    """
    try:
        stored = float(item.get("unit_price") or 0)
    except (TypeError, ValueError):
        stored = 0.0
    if stored > 0:
        return stored
    return float(prices.get((item.get("sku") or "").strip(), 0.0))


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _and_list(names: list[str]) -> str:
    """"a", "a and b", "a, b and c" — for naming products inside a sentence.
    Caps at three so one badly-synced order doesn't produce a paragraph."""
    names = [n for n in names if n]
    if len(names) > 3:
        return ", ".join(names[:3]) + f" and {len(names) - 3} other items"
    if len(names) > 1:
        return ", ".join(names[:-1]) + f" and {names[-1]}"
    return names[0] if names else "one of these items"


def _fmt_date(raw) -> str:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
    else:
        return ""
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _pretty_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return (raw or "").strip()


def _address_lines(street: str, street2: str, city: str, state: str, postal: str) -> list[str]:
    """Street lines plus a 'City, ST 12345' line, skipping whatever is blank."""
    lines = [s.strip() for s in (street, street2) if (s or "").strip()]
    city, state, postal = (city or "").strip(), (state or "").strip(), (postal or "").strip()
    tail = ", ".join(p for p in (city, " ".join(x for x in (state, postal) if x)) if p)
    if tail:
        lines.append(tail)
    return lines


def _is_sqlite(cur) -> bool:
    return "sqlite" in type(cur).__module__.lower()


def _row(row, key, idx):
    if row is None:
        return None
    return row[key] if isinstance(row, dict) else row[idx]


def build_invoice(cur, consultant_id: int, order_id: int, language: str = "en") -> dict | None:
    """Everything an invoice needs, or None if the order isn't this consultant's.

    The consultant_id in the WHERE is load-bearing, not decoration: order_id
    arrives from a chat message, and a chat message is user input even when it
    came from a link we rendered.
    """
    PH = "?" if _is_sqlite(cur) else "%s"

    cur.execute(
        f"""SELECT o.id, o.order_date, o.total, o.discount_amount, o.tax_amount,
                   o.discount_type, o.discount_value, o.tax_percent, o.source,
                   c.first_name, c.last_name, c.email, c.phone,
                   c.street, c.street2, c.city, c.state, c.postal_code
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.id = {PH} AND o.consultant_id = {PH}""",
        (order_id, consultant_id),
    )
    o = cur.fetchone()
    if not o:
        return None
    # MUST stay in the same order as the SELECT above — _row() falls back to
    # positional access, so inserting a column in one list and not the other
    # silently shifts every field after it.
    keys = ("id", "order_date", "total", "discount_amount", "tax_amount",
            "discount_type", "discount_value", "tax_percent", "source",
            "first_name", "last_name", "email", "phone",
            "street", "street2", "city", "state", "postal_code")
    order = {k: _row(o, k, i) for i, k in enumerate(keys)}

    cur.execute(
        f"""SELECT sku, product_name, unit_price, quantity
            FROM order_items WHERE order_id = {PH} ORDER BY id ASC""",
        (order_id,),
    )
    raw_items = cur.fetchall() or []
    item_keys = ("sku", "product_name", "unit_price", "quantity")
    items = [{k: _row(r, k, i) for i, k in enumerate(item_keys)} for r in raw_items]
    if not items:
        return None  # nothing to itemize; the caller explains rather than sending a blank

    cur.execute(
        f"""SELECT first_name, last_name, email, invoice_phone, invoice_street,
                   invoice_city, invoice_state, invoice_zip, invoice_email
            FROM consultants WHERE id = {PH}""",
        (consultant_id,),
    )
    cons_row = cur.fetchone()
    cons_keys = ("first_name", "last_name", "email", "invoice_phone", "invoice_street",
                 "invoice_city", "invoice_state", "invoice_zip", "invoice_email")
    cons = {k: (_row(cons_row, k, i) or "") for i, k in enumerate(cons_keys)}

    prices = _catalog_prices(language)
    lines, subtotal = [], 0.0
    for it in items:
        try:
            qty = max(1, int(it.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        unit = _line_price(it, prices)
        line_total = unit * qty
        subtotal += line_total
        lines.append({
            # unescape first: some synced product names carry a literal "&reg;"
            # as TEXT ("Satin Hands&reg; Nourishing Shea Cream"). Escaping that
            # for output would print the entity to the customer. Real
            # ampersands ("White Tea & Citrus") are untouched by unescape and
            # still get escaped normally at render time.
            "name": _html.unescape((it.get("product_name") or it.get("sku") or "Item").strip()),
            "unit": unit,
            "qty": qty,
            "total": line_total,
        })

    def _num(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    discount = _num(order.get("discount_amount"))
    tax = _num(order.get("tax_amount"))

    # How she SAID it, so the invoice echoes her words: "20% off" not "-$8.40".
    discount_label = "Discount"
    d_type, d_value = (order.get("discount_type") or "").strip(), _num(order.get("discount_value"))
    if d_type == "%" and d_value:
        discount_label = f"Discount ({d_value:g}% off)"
    elif d_type == "$" and d_value:
        discount_label = f"Discount (${d_value:,.2f} off)"

    tax_label = "Sales Tax"
    if _num(order.get("tax_percent")):
        tax_label = f"Sales Tax ({_num(order['tax_percent']):g}%)"

    consultant_name = " ".join(p for p in (cons["first_name"], cons["last_name"]) if p).strip()
    customer_name = " ".join(
        p for p in ((order["first_name"] or ""), (order["last_name"] or "")) if p
    ).strip() or "Customer"

    return {
        "order_id": int(order["id"]),
        "date": _fmt_date(order.get("order_date")),
        "lines": lines,
        "subtotal": subtotal,
        "discount": discount,
        "discount_label": discount_label,
        "tax": tax,
        "tax_label": tax_label,
        "total": subtotal - discount + tax,
        # What InTouch says the order was worth. NOT printed on the invoice —
        # it's only here for diagnosis. The invoice bills what the lines say.
        "stored_total": _num(order.get("total")),
        "source": (order.get("source") or "").strip(),
        # None = safe to send. Anything else names the reason it isn't, and the
        # preview refuses. Deliberately only TWO conditions, no arithmetic
        # threshold: an invoice is a document, so the bar is "would this page be
        # visibly wrong", not "do two numbers agree".
        #
        # "cds" — Mary Kay ships and bills these customers directly, so there is
        #   no invoice for her to send in the first place. Their line data is
        #   also badly wrong in the overbilling direction: in local data order
        #   1954 is a $28 order whose lines sum to $488, 1941 is $44 vs $292,
        #   1949 is $20 vs $250. Cause not yet diagnosed (2026-08-04) — parked
        #   until it turns up in testing. Skipping the source sidesteps it.
        #
        #   "myshop" counts as CDS here and gets the same block (Brian,
        #   2026-08-06). The source column records who PLACED the order — she
        #   did, or her customer did online — not how it shipped, and both
        #   ship and bill from MK's end. It also carries MK's own tax and
        #   shipping, which their APIs never break out (probed 2026-08-06: the
        #   order list returns GrandTotalAmount and nothing else; the detail
        #   call returns grandTotal plus line amounts, no tax or freight
        #   field). An invoice for one of these could therefore never be made
        #   to match what the customer was actually charged. Invoices are for
        #   the orders SHE fulfills, where the numbers are hers: whatever tax,
        #   shipping and discount she entered in MyCustomers or MPA is the
        #   truth, and if she entered none, that is also the truth.
        #
        # "unpriced" — the bulk history import writes a $0 row for any product
        #   it can't match to the catalog (order_history_import_store.py:377-381),
        #   which would print something she was paid for as free.
        #
        # What is deliberately NOT checked: the gap between the lines and
        # o.total. Those disagree constantly for honest reasons — MK shipping
        # and tax ride along in GrandTotalAmount, and she isn't billing her
        # customer for those. An earlier draft blocked on it and refused 7% of
        # otherwise-fine orders.
        "block_reason": (
            "cds" if (order.get("source") or "").strip() in MK_FULFILLED_SOURCES
            else ("unpriced" if any(l["unit"] <= 0 for l in lines) else None)
        ),
        "unpriced": [l["name"] for l in lines if l["unit"] <= 0],
        "sold_by": {
            "name": consultant_name or "Your Mary Kay Consultant",
            "address": _address_lines(cons["invoice_street"], "", cons["invoice_city"],
                                      cons["invoice_state"], cons["invoice_zip"]),
            "phone": _pretty_phone(cons["invoice_phone"]),
            # Business email if she set one, otherwise the address she logs in
            # with. Never blank — a customer must always have a way to reply.
            "email": (cons["invoice_email"] or cons["email"] or "").strip(),
        },
        "sold_to": {
            "name": customer_name,
            "address": _address_lines(order["street"] or "", order["street2"] or "",
                                      order["city"] or "", order["state"] or "",
                                      order["postal_code"] or ""),
            "phone": _pretty_phone(order["phone"] or ""),
            "email": (order["email"] or "").strip(),
        },
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_PDF_CSS = """
@page { size: letter portrait; margin: 0.6in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #111; }
h1 { font-size: 17pt; color: #e91e63; margin: 0 0 1pt 0; }
.sub { color: #666; font-size: 9pt; margin: 0 0 16pt 0; }
.party-label { font-size: 8pt; color: #888; letter-spacing: 1pt; }
.party-name { font-weight: bold; }
table.parties { width: 100%; margin-bottom: 6pt; }
table.parties td { vertical-align: top; font-size: 9.5pt; line-height: 1.45; }
table.items { width: 100%; border-collapse: collapse; margin-top: 10pt; }
table.items th { background: #f7f7f8; text-align: left; padding: 6pt 5pt;
                 font-size: 8.5pt; color: #555; border-bottom: 1pt solid #e0e0e0; }
table.items td { padding: 6pt 5pt; border-bottom: 0.5pt solid #eee; font-size: 9.5pt; }
table.totals { width: 46%; margin-left: 54%; margin-top: 10pt; }
table.totals td { padding: 3pt 5pt; font-size: 10pt; }
tr.grand td { font-weight: bold; font-size: 11.5pt; border-top: 1pt solid #333; padding-top: 6pt; }
.r { text-align: right; }
.foot { margin-top: 26pt; color: #888; font-size: 8.5pt; text-align: center; }
"""


def _party_block(party: dict, label: str) -> str:
    parts = [f'<div class="party-label">{label}</div>',
             f'<div class="party-name">{_html.escape(party["name"])}</div>']
    parts += [f"<div>{_html.escape(l)}</div>" for l in party["address"]]
    if party["phone"]:
        parts.append(f'<div>{_html.escape(party["phone"])}</div>')
    if party["email"]:
        parts.append(f'<div>{_html.escape(party["email"])}</div>')
    return "".join(parts)


def _totals_rows(inv: dict, cls_prefix: str = "") -> str:
    """Subtotal / discount / tax / total. Zero-value rows are omitted entirely."""
    rows = [f'<tr><td>Subtotal</td><td class="r">{_money(inv["subtotal"])}</td></tr>']
    if inv["discount"]:
        rows.append(f'<tr><td>{_html.escape(inv["discount_label"])}</td>'
                    f'<td class="r">-{_money(inv["discount"])}</td></tr>')
    if inv["tax"]:
        rows.append(f'<tr><td>{_html.escape(inv["tax_label"])}</td>'
                    f'<td class="r">{_money(inv["tax"])}</td></tr>')
    rows.append(f'<tr class="grand"><td>Total</td>'
                f'<td class="r">{_money(inv["total"])}</td></tr>')
    return "".join(rows)


def render_invoice_html(inv: dict) -> str:
    """Standalone invoice document — used for the PDF and the email body.

    Table-based and inline-CSS-free on purpose: this same markup goes through
    xhtml2pdf (which supports tables and little else) AND through email clients
    (which support tables and little else). Two renderers, one lowest common
    denominator, so what she previews is what the customer receives.
    """
    item_rows = "".join(
        f'<tr><td>{_html.escape(l["name"])}</td>'
        f'<td class="r">{_money(l["unit"])}</td>'
        f'<td class="r">{l["qty"]}</td>'
        f'<td class="r">{_money(l["total"])}</td></tr>'
        for l in inv["lines"]
    )
    return f"""<html><head><meta charset="utf-8"><style>{_PDF_CSS}</style></head><body>
<h1>Invoice</h1>
<p class="sub">Order Date: {_html.escape(inv["date"])}</p>
<table class="parties"><tr>
  <td width="50%">{_party_block(inv["sold_by"], "SOLD BY")}</td>
  <td width="50%">{_party_block(inv["sold_to"], "SOLD TO")}</td>
</tr></table>
<table class="items">
  <tr><th>Product</th><th class="r">Price</th><th class="r">Qty</th><th class="r">Total</th></tr>
  {item_rows}
</table>
<table class="totals">{_totals_rows(inv)}</table>
<p class="foot">Thank you for your business!</p>
</body></html>"""


def render_invoice_preview(inv: dict) -> str:
    """The chat bubble she sees BEFORE anything is sent.

    Not the invoice itself — a summary plus the two actions. Rendering the full
    document inside a chat bubble would be unreadable at phone width, and the
    point of this step is confirming the right order and the right address, not
    proofreading line art.
    """
    lines = "".join(
        f'<div>• {l["qty"]} × {_html.escape(l["name"])} '
        f'<span style="color:#888">{_money(l["total"])}</span></div>'
        for l in inv["lines"]
    )
    to_email = _html.escape(inv["sold_to"]["email"])
    send_cmd = _html.escape(f'email invoice for order {inv["order_id"]}', quote=True)

    # Date only, no order number. The id is ours — a global autoincrement
    # across all consultants, so her invoices look like they skip hundreds at a
    # time and the number means nothing to her or her customer (Brian,
    # 2026-08-06). It is not on the invoice document either; the order date is
    # what identifies the transaction to both of them.
    # Discount and tax get their own lines here, not just on the document
    # (2026-08-06). Without them the bubble listed $60.00 of product and then a
    # Total of $52.32 with nothing in between, which reads as an arithmetic bug
    # in the moment she is deciding whether to send it. Same omit-when-zero
    # rule as _totals_rows, so an ordinary order looks exactly as it did.
    adjustments = ""
    if inv["discount"]:
        adjustments += (f'<div style="color:#888">{_html.escape(inv["discount_label"])} '
                        f'−{_money(inv["discount"])}</div>')
    if inv["tax"]:
        adjustments += (f'<div style="color:#888">{_html.escape(inv["tax_label"])} '
                        f'{_money(inv["tax"])}</div>')

    head = (
        f'<strong>Invoice for {_html.escape(inv["sold_to"]["name"])}</strong><br>'
        f'<span style="color:#888">{_html.escape(inv["date"])}</span>'
        f'<div style="margin:8px 0">{lines}{adjustments}</div>'
    )

    # The order list she just looked at prints the STORED total; this invoice
    # sums its own lines. When those disagree we know the itemization is
    # incomplete — almost always an imported order that has not been through
    # the detail sync yet, so its quantities are still the bulk import's
    # placeholder 1 (order_history_import_store.py:12). Order 1953 in local
    # data: one line of 1 x $20, stored total $80.
    #
    # This REFUSES rather than warning, which is the opposite of what an
    # earlier draft did. Email is one-way: a wrong invoice cannot be pulled
    # back, and she would be defending a number to her customer that neither
    # of them can reconstruct. An amber caption is the right weight for a
    # thing you can undo. Orders placed through MPA (source='consultant')
    # reconcile 100% in local data, so the flow this protects is the imported
    # one, and the wait is at most until the next nightly sync.
    if inv["block_reason"] == "cds":
        return (
            head
            + '<div style="margin-top:8px">This one shipped from Mary Kay directly, so '
              'they already billed your customer for it — there\'s no invoice to send.</div>'
        )

    if inv["block_reason"] == "unpriced":
        return (
            head
            + f'<div style="margin-top:8px">I can\'t send this one — I don\'t have a '
              f'price on file for {_html.escape(_and_list(inv["unpriced"]))}, so your '
              f'customer would see it as free.</div>'
              f'<div style="margin-top:8px;color:#888">Nightly sync usually fills in '
              f'missing prices, so try again tomorrow.</div>'
        )

    # "View invoice" stays a plain link, deliberately OUTSIDE .quick-replies:
    # it carries no data-send, so app.js's delegated handler doesn't treat the
    # click as a chat message.
    #
    # data-newwin makes app.js open it with window.open() instead of following
    # the href. That matters because this bubble must survive the trip: in the
    # installed PWA target="_blank" navigates in place, and returning to /app
    # reloads chat empty — taking the Email button she came back for with it.
    # href + target stay as the no-JS fallback.
    #
    # The two actions below are the same qr-btn buttons the order confirm uses
    # (mk_chat_core/render.py:_qr) — pink for the one that does the thing,
    # white for the way out — carrying qr-always so styles.css shows them on
    # desktop too (Brian, 2026-08-06). data-send-label keeps the id out of the
    # echoed message: she sends "email invoice for order 1953" and sees
    # "Email".
    return (
        head
        + f'<div><strong>Total: {_money(inv["total"])}</strong></div>'
          f'<div style="margin-top:8px">'
          f'<a href="/invoice/{inv["order_id"]}" data-newwin '
          f'target="_blank" rel="noopener">View invoice</a></div>'
          f'<div style="margin-top:10px">Send invoice to {to_email}?</div>'
          f'<div class="quick-replies qr-always" style="margin-top:8px">'
          f'<button class="qr-btn qr-yes" data-send="{send_cmd}" '
          f'data-send-label="Email">Email</button>'
          f'<button class="qr-btn qr-no" data-send="cancel">Cancel</button>'
          f'</div>'
    )


def render_invoice_pdf(inv: dict) -> bytes | None:
    """PDF bytes, or None if rendering fails.

    None is a normal outcome, not an error to raise: the caller still sends the
    email with the invoice inline in the body, so a PDF problem costs the
    attachment and nothing else. xhtml2pdf is pure Python — the web service has
    no Playwright and no chromium (that is the worker's image, not this one).
    """
    try:
        from xhtml2pdf import pisa
    except ImportError:
        return None

    buf = io.BytesIO()
    try:
        result = pisa.CreatePDF(io.StringIO(render_invoice_html(inv)), dest=buf)
    except Exception:
        return None
    if result.err:
        return None
    data = buf.getvalue()
    return data if data.startswith(b"%PDF-") else None
