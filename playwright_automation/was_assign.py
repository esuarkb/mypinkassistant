# playwright_automation/was_assign.py
#
# WAS auto-assign (2026-08-20): assigns pending myCustomers® order rows on the
# InTouch Weekly Accomplishment Sheet (legacy ASP.NET WebForms page at
# applications.marykayintouch.com/weekly/main/entry.aspx).
#
# InTouch itself flows every MyCustomers order into the sheet's pending list
# with Date / Hostess / $ Sales (Less Tax) / $ Sales Tax prefilled. All this
# script does per row is: set the Type dropdown, fill # SCS Sold and
# $ Non-Rcv. Sales Tax where we can compute them, and click Add. Clicking Add
# persists straight to the YTD Summary — the 6-step Submit wizard is the
# consultant's own weekly act and is NEVER touched here.
#
# Safety properties (verified live on Andrea's sheet 2026-08-20):
#   - Added rows leave the pending list, so re-runs are naturally idempotent.
#   - Every added row keeps an edit pencil + an X that returns it to pending.
#   - Rows whose order date predates consultants.was_assign_start_date are
#     left alone: consultants kept these sheets by hand before this feature,
#     and auto-adding history would double-count their manual entries.
#
# Call run_was_assign(page, cur, consultant_id, ph=...) after login_intouch().
# Every Add and week change is a full __doPostBack page reload, so the DOM is
# re-scanned from scratch after each action — row indexes are never reused.

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

from playwright_automation.step_log import step

_ENTRY_URL = "https://applications.marykayintouch.com/weekly/main/entry.aspx"
_SSO_PRIME_URL = "https://www.marykayintouch.com/"

# WAS "Type" dropdown values (captured 2026-08-20): PWS=My Shop Orders,
# ONTHEGO, SCC=Skin Care/Parties/Facials/Color, SHOWS, PCPMISC, REORDERS.
_TYPE_BY_SOURCE = {
    "myshop": "PWS",
    "cds": "PWS",   # Brian 2026-08-20: CDS counts as My Shop unless asked otherwise
}
_TYPE_DEFAULT = "SCC"

_CATALOG_PATH = Path(__file__).parent.parent / "catalog" / "en.csv"
_scs_skus_cache: set[str] | None = None


def _scs_skus() -> set[str]:
    """SKUs that count as a Skin Care Set on the WAS.

    Rule confirmed by Andrea 2026-08-20: catalog category 'skincare' with
    'Set' in the product name, EXCLUDING Go Sets, Microdermabrasion and
    Satin Lips. Rule-based (not a SKU list) so Old-SKU predecessors and
    future set generations count without a code change.
    """
    global _scs_skus_cache
    if _scs_skus_cache is None:
        out = set()
        with open(_CATALOG_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("product_name") or "").lower()
                if (
                    (row.get("category") or "").strip() == "skincare"
                    and re.search(r"\bset\b", name)
                    and "go set" not in name
                    and "microdermabrasion" not in name
                    and "satin lips" not in name
                ):
                    out.add((row.get("sku") or "").strip())
        _scs_skus_cache = out
    return _scs_skus_cache


# ---------------------------------------------------------------------------
# DB side: which orders are new, and what goes on each row
# ---------------------------------------------------------------------------

def _row_val(row, idx, key):
    return row[key] if isinstance(row, dict) else row[idx]


def _fetch_consultant_settings(cur, consultant_id: int, ph: str):
    cur.execute(
        f"SELECT was_auto_assign, was_assign_start_date, tax_rate "
        f"FROM consultants WHERE id = {ph}",
        (consultant_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "auto_assign": _row_val(row, 0, "was_auto_assign"),
        "start_date": _row_val(row, 1, "was_assign_start_date"),
        "tax_rate": _row_val(row, 2, "tax_rate"),
    }


def _fetch_recent_orders(cur, consultant_id: int, ph: str, start_date: str) -> list[dict]:
    """Orders imported in the last 48h whose order date is on/after the
    feature start date — these decide which WAS weeks we visit and provide
    the Type/SCS/NRST data for row matching. Chat orders are re-imported
    nightly as intouch_import (with this run's created_at) before this step
    runs, so they are all visible here with their final source label."""
    cutoff = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        f"""SELECT o.id, o.order_date, o.total, o.tax_amount, o.source,
                   c.first_name, c.last_name
            FROM orders o JOIN customers c ON c.id = o.customer_id
            WHERE o.consultant_id = {ph}
              AND o.created_at >= {ph}
              AND o.source IN ('intouch_import', 'myshop', 'cds')
            ORDER BY o.id""",
        (consultant_id, cutoff),
    )
    orders = []
    for r in cur.fetchall():
        oid = _row_val(r, 0, "id")
        odate = str(_row_val(r, 1, "order_date") or "")[:10]
        if not odate or odate < start_date:
            continue
        orders.append({
            "id": oid,
            "date": odate,
            "total": float(_row_val(r, 2, "total") or 0),
            "tax": _row_val(r, 3, "tax_amount"),
            "source": (_row_val(r, 4, "source") or "").strip(),
            "name": f"{_row_val(r, 5, 'first_name') or ''} {_row_val(r, 6, 'last_name') or ''}".strip(),
        })
    # Guest orders (customer not matched in our DB but real in InTouch) still
    # produce pending WAS rows — match them for Type only (no items = no
    # SCS/NRST). Their source/fulfillment hold the raw API values.
    cur.execute(
        f"""SELECT order_date, total, source, fulfillment, first_name, last_name
            FROM guest_orders
            WHERE consultant_id = {ph} AND created_at >= {ph}""",
        (consultant_id, cutoff),
    )
    for r in cur.fetchall():
        odate = str(_row_val(r, 0, "order_date") or "")[:10]
        if not odate or odate < start_date:
            continue
        raw_src = (_row_val(r, 2, "source") or "").strip()
        raw_ful = (_row_val(r, 3, "fulfillment") or "").strip()
        if raw_src == "Online" and raw_ful == "CDS":
            src = "myshop"
        elif raw_ful == "CDS":
            src = "cds"
        else:
            src = "intouch_import"
        orders.append({
            "id": None,
            "date": odate,
            "total": float(_row_val(r, 1, "total") or 0),
            "tax": None,
            "source": src,
            "name": f"{_row_val(r, 4, 'first_name') or ''} {_row_val(r, 5, 'last_name') or ''}".strip(),
            "guest": True,
        })
    return orders


def _order_scs_and_retail(cur, order_id: int, ph: str) -> tuple[int, float]:
    """(# of skin-care sets, retail value of all items) for one order.
    unit_price on imported items IS the catalog retail price at import time."""
    cur.execute(
        f"SELECT sku, unit_price, quantity FROM order_items WHERE order_id = {ph}",
        (order_id,),
    )
    scs = 0
    retail = 0.0
    skus = _scs_skus()
    for r in cur.fetchall():
        sku = (_row_val(r, 0, "sku") or "").strip()
        price = float(_row_val(r, 1, "unit_price") or 0)
        qty = int(_row_val(r, 2, "quantity") or 1)
        retail += price * qty
        if sku in skus:
            scs += qty
    return scs, retail


def _plan_for_order(cur, order: dict, tax_rate, ph: str) -> dict:
    """What we would type on this order's WAS row."""
    plan = {
        "type": _TYPE_BY_SOURCE.get(order["source"], _TYPE_DEFAULT),
        "scs": 0,
        "nrst": None,
    }
    if order.get("guest") or not order.get("id"):
        return plan
    scs, retail = _order_scs_and_retail(cur, order["id"], ph)
    plan["scs"] = scs
    # NRST only on inventory-fulfilled orders: on myshop/CDS the consultant
    # never prepaid tax (MK sells from its own stock and remits directly),
    # so there is nothing to under-recover.
    if order["source"] == "intouch_import" and tax_rate is not None and retail > 0:
        collected = float(order["tax"] or 0)
        nrst = round(retail * float(tax_rate) / 100.0 - collected, 2)
        if nrst > 0:
            plan["nrst"] = nrst
    return plan


# ---------------------------------------------------------------------------
# Page side: weeks, pending rows, Add
# ---------------------------------------------------------------------------

def _goto_entry(page: Page) -> None:
    # entry.aspx needs the standard login plus one visit to the www home to
    # prime SSO across the applications.marykayintouch.com redirect chain.
    page.goto(_SSO_PRIME_URL, wait_until="domcontentloaded")
    page.goto(_ENTRY_URL, wait_until="load")
    page.wait_for_selector('select[name$="lstWeekYear"]', timeout=30000)


def _week_options(page: Page) -> list[dict]:
    """The ~8 selectable weeks: [{value, start, end}] parsed from option text
    like '8/16/2026 - 8/22/2026'."""
    out = []
    for opt in page.query_selector_all('select[name$="lstWeekYear"] option'):
        text = (opt.text_content() or "").strip()
        m = re.match(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", text)
        if not m:
            continue
        start = datetime.strptime(m.group(1), "%m/%d/%Y").date()
        end = datetime.strptime(m.group(2), "%m/%d/%Y").date()
        out.append({"value": opt.get_attribute("value"), "start": start, "end": end})
    return out


def _select_week(page: Page, value: str) -> None:
    sel = page.locator('select[name$="lstWeekYear"]')
    if sel.input_value() == value:
        return
    # onchange fires __doPostBack → full page reload
    sel.select_option(value)
    page.wait_for_load_state("load")
    page.wait_for_selector('select[name$="lstWeekYear"]', timeout=30000)


def _scan_pending_rows(page: Page) -> list[dict]:
    """Pending myCustomers rows = repeater rows that still have an Add button.
    Row date is the first cell of the row (MM/DD); year comes from the week."""
    rows = []
    for btn in page.query_selector_all('input[name$="btnAdd"]'):
        name = btn.get_attribute("name") or ""
        m = re.match(r"^(.*rptOrders\$ctl\d+\$)btnAdd$", name)
        if not m:
            continue
        prefix = m.group(1)
        esc = prefix.replace("$", "\\$")
        hostess_el = page.query_selector(f'input[name="{prefix}tbxHostess"]')
        if hostess_el is None:
            continue
        tr = hostess_el.evaluate_handle("el => el.closest('tr')").as_element()
        date_txt = ""
        if tr is not None:
            first_td = tr.query_selector("td")
            if first_td:
                date_txt = (first_td.text_content() or "").strip()
        sales_el = page.query_selector(f'input[name="{prefix}tbxSalesLessTax"]')
        rows.append({
            "prefix": prefix,
            "hostess": (hostess_el.get_attribute("value") or "").strip(),
            "date_mmdd": date_txt,
            "sales": float((sales_el.get_attribute("value") or "0") if sales_el else 0 or 0),
        })
    return rows


def _mmdd_to_iso(mmdd: str, week_start: date, week_end: date) -> str:
    """'08/19' + the selected week's range → '2026-08-19' (year from the week;
    a week can straddle New Year, so pick whichever candidate falls inside)."""
    m = re.match(r"(\d{1,2})/(\d{1,2})", mmdd or "")
    if not m:
        return ""
    mo, dy = int(m.group(1)), int(m.group(2))
    for year in {week_start.year, week_end.year}:
        try:
            d = date(year, mo, dy)
        except ValueError:
            continue
        if week_start <= d <= week_end:
            return d.isoformat()
    return ""


def _match_order(row: dict, row_date_iso: str, orders: list[dict]) -> dict | None:
    """Match a pending row to one of this run's orders by customer name +
    date, tightest $ Sales (Less Tax) difference wins. Each order is consumed
    by at most one row (two same-day same-amount orders = two rows)."""
    best = None
    best_diff = 0.05  # sales must agree to within a nickel
    for o in orders:
        if o.get("_used"):
            continue
        if o["date"] != row_date_iso:
            continue
        if o["name"].lower() != row["hostess"].lower():
            continue
        sales_less_tax = round(o["total"] - float(o["tax"] or 0), 2)
        diff = abs(sales_less_tax - row["sales"])
        if diff <= best_diff:
            best, best_diff = o, diff
    if best is not None:
        best["_used"] = True
    return best


def _fill_and_add(page: Page, row: dict, plan: dict) -> None:
    prefix = row["prefix"]
    page.locator(f'select[name="{prefix}ddlSalesType"]').select_option(plan["type"])
    if plan["scs"]:
        page.locator(f'input[name="{prefix}tbxSCS"]').fill(str(plan["scs"]))
    if plan["nrst"] is not None:
        page.locator(f'input[name="{prefix}tbxNRST"]').fill(f"{plan['nrst']:.2f}")
    # Add is a WebForms submit → full postback; caller re-scans afterwards
    page.locator(f'input[name="{prefix}btnAdd"]').click()
    page.wait_for_load_state("load")
    page.wait_for_selector('select[name$="lstWeekYear"]', timeout=30000)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_was_assign(page: Page, cur, consultant_id: int, ph: str = "?",
                   dry_run: bool = False) -> dict:
    """Assign this run's new orders onto the WAS. Returns a summary dict.
    Never raises for per-row trouble — a row that won't fill is left pending
    for the consultant (the sheet stays their editable ledger either way)."""
    settings = _fetch_consultant_settings(cur, consultant_id, ph)
    if not settings:
        return {"skipped": "no consultant"}
    if not settings["auto_assign"]:
        return {"skipped": "opted out"}

    # First run for this consultant: draw the clean line TODAY and assign
    # nothing older. Consultants kept these sheets manually before this
    # feature — reaching back would double-count their hand-entered rows.
    if not settings["start_date"]:
        today = date.today().isoformat()
        if not dry_run:
            cur.execute(
                f"UPDATE consultants SET was_assign_start_date = {ph} WHERE id = {ph}",
                (today, consultant_id),
            )
        return {"initialized": today, "added": 0}

    start_date = str(settings["start_date"])[:10]
    orders = _fetch_recent_orders(cur, consultant_id, ph, start_date)
    if not orders:
        return {"added": 0, "weeks": 0, "note": "no new orders"}

    step("was_assign", 1, 5, "goto_entry", "opening weekly accomplishment sheet")
    _goto_entry(page)

    weeks = _week_options(page)
    target_values = []
    for wk in weeks:
        if any(wk["start"].isoformat() <= o["date"] <= wk["end"].isoformat() for o in orders):
            target_values.append(wk)

    summary = {"added": 0, "weeks": len(target_values), "planned": [],
               "unmatched_added": 0}

    def _plan_for_row(row: dict, row_iso: str) -> dict:
        """Match the row to one of this run's orders if possible; an
        InTouch-real row we can't match (older unassigned row in a week we're
        visiting, order our import missed) still gets the Skin Care default —
        never skipped (Brian 2026-08-20). Everything on the sheet dated after
        the feature start belongs on the YTD."""
        order = _match_order(row, row_iso, orders)
        if order is None:
            summary["unmatched_added"] += 1
            return {"type": _TYPE_DEFAULT, "scs": 0, "nrst": None}
        return _plan_for_order(cur, order, settings["tax_rate"], ph)

    for wk in target_values:
        step("was_assign", 2, 5, "select_week", f"week {wk['start']} - {wk['end']}")
        _select_week(page, wk["value"])

        if dry_run:
            # No Add ever happens, so pending never shrinks — plan every
            # assignable row in one scan and move on.
            for row in _scan_pending_rows(page):
                row_iso = _mmdd_to_iso(row["date_mmdd"], wk["start"], wk["end"])
                if not row_iso or row_iso < start_date:
                    continue
                plan = _plan_for_row(row, row_iso)
                summary["planned"].append({
                    "week": f"{wk['start']}", "date": row_iso,
                    "hostess": row["hostess"], "sales": row["sales"],
                    "type": plan["type"], "scs": plan["scs"], "nrst": plan["nrst"],
                })
            continue

        # Add-loop: process the FIRST assignable row, re-scan after the
        # postback, repeat until a scan finds nothing assignable. Indexes
        # shift as rows leave pending — never iterate a stale row list.
        for _ in range(40):  # hard stop; a week never has this many rows
            step("was_assign", 3, 5, "scan_rows", "scanning pending myCustomers rows")
            pending = _scan_pending_rows(page)
            target = None
            for row in pending:
                row_iso = _mmdd_to_iso(row["date_mmdd"], wk["start"], wk["end"])
                if not row_iso or row_iso < start_date:
                    continue  # predates the feature — the consultant's territory
                target = (row, row_iso)
                break
            if target is None:
                break
            row, row_iso = target
            plan = _plan_for_row(row, row_iso)
            summary["planned"].append({
                "week": f"{wk['start']}", "date": row_iso,
                "hostess": row["hostess"], "sales": row["sales"],
                "type": plan["type"], "scs": plan["scs"], "nrst": plan["nrst"],
            })
            step("was_assign", 4, 5, "fill_row", f"{row['hostess']} {row_iso} → {plan['type']}")
            step("was_assign", 5, 5, "click_add", "clicking Add (WebForms postback)")
            _fill_and_add(page, row, plan)
            summary["added"] += 1

    return summary
