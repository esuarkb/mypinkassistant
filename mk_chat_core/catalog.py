"""Product catalog: loading, exact/fuzzy matching, product formatting.

Fuzzy scoring (best_matches) lives in intent_router (routing needs it);
this module imports it for auto_pick_match.
"""
import html as _html
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from intent_router import best_matches

from .config import CATALOG_DIR, MATCH_LIMIT
from .ui_text import UI_EN


def get_catalog_path_for_language(language: str) -> Path:
    language = (language or "en").strip().lower()
    if language == "es":
        return CATALOG_DIR / "es.csv"
    return CATALOG_DIR / "en.csv"


# The Order of Application skincare chart is a single MK-hosted PDF shared by
# nearly every skincare product (49 of 53 rows carrying a URL on 2026-07-16).
# We surface the live catalog URL rather than hardcoding it, so update_catalog's
# nightly refresh self-heals MK's rotating Demandware static hash. The fallback
# is the dominant URL as of 2026-07-16, used only if the catalog carries none.
_ORDER_OF_APPLICATION_FALLBACK = (
    "https://order.marykayintouch.com/on/demandware.static/-/"
    "Sites-us-master-catalog/default/dw2fadb95e/Original/10005/Order%20of%20Application.pdf"
)


def get_order_of_application_url(catalog: List[dict]) -> str:
    """Most common non-empty order_of_application_url in the catalog, else the
    2026-07-16 fallback. Cheap to compute per call (~400 rows)."""
    from collections import Counter
    counts = Counter(
        u for c in (catalog or [])
        if (u := (c.get("order_of_application_url") or "").strip())
    )
    return counts.most_common(1)[0][0] if counts else _ORDER_OF_APPLICATION_FALLBACK


# -------------------------
# Catalog
# -------------------------
def load_catalog(path: Path) -> List[dict]:
    """
    Loads catalog CSV with headers: sku (lowercase), product_name, price, search_terms
    Filters obvious samples/collateral to improve matching.
    """
    import csv

    if not path.exists():
        raise FileNotFoundError(f"Catalog not found at: {path}")

    items: List[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            name = (row.get("product_name") or "").strip().replace("®", "")
            price = row.get("price")

            # ✅ NEW
            search_terms = (row.get("search_terms") or "").strip()

            if not sku or not name:
                continue

            if (row.get("discontinued") or "").strip() == "1":
                continue

            name_l = name.lower()
            if "sample" in name_l:
                continue
            if "the look" in name_l or "booklet" in name_l or "look (" in name_l:
                continue
            if "(old sku)" in name_l:
                continue

            try:
                price_val = float(price) if price else None
            except ValueError:
                price_val = None

            from datetime import date as _date, datetime as _datetime
            prev_price_val = None
            price_changed_at = (row.get("price_changed_at") or "").strip()
            if price_changed_at:
                try:
                    changed = _datetime.strptime(price_changed_at, "%Y-%m-%d").date()
                    if (_date.today() - changed).days <= 30:
                        pp = (row.get("previous_price") or "").strip()
                        prev_price_val = float(pp) if pp else None
                except (ValueError, TypeError):
                    pass

            items.append({
                "sku": sku,
                "product_name": name,
                "price": price_val,
                "previous_price": prev_price_val,
                "search_terms": search_terms,
                "search_string": f"{name} {search_terms}".strip(),
                # exposed for best_matches' tie-break: newest same-name SKU wins (2026-07-11)
                "date_added": (row.get("date_added") or "").strip(),
                "fact_sheet_url": (row.get("fact_sheet_url") or "").strip(),
                "order_of_application_url": (row.get("order_of_application_url") or "").strip(),
                "use_up_rate_months": (row.get("use_up_rate_months") or "").strip(),
            })

    return items


def fmt_price(p: Any) -> str:
    if isinstance(p, (int, float)):
        return f"${p:.2f}"
    return ""


def _fmt_price_with_change(m: dict) -> str:
    price = f"${m['price']:.2f}" if m.get("price") is not None else ""
    if m.get("previous_price") is not None:
        price += f" (was ${m['previous_price']:.2f})"
    return price


def _fmt_product_list_item(m: dict) -> str:
    name = m['product_name']
    price = _fmt_price_with_change(m)
    safe = _html.escape(name, quote=True)
    return f'• <a href="#" data-send="{safe}">{_html.escape(name)}</a> — {price}'


def _fmt_product_lookup_single(m: dict, ui: dict = None) -> str:
    """Format a single product lookup result with optional PDF links."""
    if ui is None:
        ui = UI_EN
    price = _fmt_price_with_change(m)
    line = f"{m['product_name']} — {price}".strip(" —")
    # Part # shown subtly on the card so consultants can grab it for InTouch
    # order/replacement entry. weed-garden 2026-07-09: "part number" questions
    # were routing to product_lookup with no way to answer them — the number
    # simply wasn't on the card. Gray/small like other muted card meta text.
    sku = (m.get("sku") or "").strip()
    if sku:
        line += f" <span style='color:#888;font-size:0.85em'>{ui['product_part_number'].format(sku=_html.escape(sku))}</span>"
    parts = [f"<strong>{ui['product_lookup_header']}</strong>", line]
    links = []
    if m.get("fact_sheet_url"):
        links.append(f'<a href="{m["fact_sheet_url"]}" target="_blank">{ui["product_fact_sheet_link"]}</a>')
    if m.get("order_of_application_url"):
        links.append(f'<a href="{m["order_of_application_url"]}" target="_blank">{ui["product_order_of_application_link"]}</a>')
    if links:
        parts.append(" &bull; ".join(links))
    return "<br>".join(parts)


def multi_product_lookup(catalog: List[dict], product_text: str, ui: dict = None) -> Optional[str]:
    """
    Fallback for lookups that name several products at once
    ("how much is the cc cream, lifting serum and night treatment").

    Callers must try the whole string first and only come here when that
    search was weak. Guard against splitting a single product whose NAME
    contains "and"/"&" ("berry and vanilla body lotion"): if any one catalog
    product contains every significant word of the query, this is that
    product, not a list — never split it.
    Returns formatted HTML when 2+ parts independently resolve, else None.
    """
    if ui is None:
        ui = UI_EN
    text = (product_text or "").strip()
    if not re.search(r",|\s+and\s+", text, flags=re.IGNORECASE):
        return None

    sig = [
        w for w in re.split(r"[^a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in ("and", "the", "mary", "kay")
    ]
    if sig:
        for c in catalog:
            s = c["search_string"].lower()
            if all(re.search(rf"\b{re.escape(w)}\b", s) for w in sig):
                return None

    parts = [
        re.sub(r"^(?:the|a|an)\s+", "", p.strip(), flags=re.IGNORECASE)
        for p in re.split(r",\s*|\s+and\s+", text, flags=re.IGNORECASE)
    ]
    parts = [p for p in parts if len(p) >= 3]
    if len(parts) < 2:
        return None

    found: List[Tuple[str, Optional[dict]]] = []
    for p in parts[:6]:
        # Same threshold the single-product lookup paths use
        m = best_matches(catalog, p, limit=1, min_score=50)
        found.append((p, m[0] if m else None))

    if sum(1 for _, f in found if f) < 2:
        return None

    lines = [f"<strong>{ui['product_lookup_header']}</strong>"]
    for p, f in found:
        if f:
            lines.append(_fmt_product_list_item(f))
        else:
            lines.append(ui["product_lookup_not_found_bullet"].format(name=_html.escape(p)))
    return "<br>".join(lines)


# best_matches moved to intent_router.py (routing consolidation 2026-07-02);
# imported back at the top of this file.

def auto_pick_match(catalog: List[dict], query: str) -> Tuple[Optional[dict], List[dict]]:
    q = (query or "").strip().lower()
    matches = best_matches(catalog, query, limit=MATCH_LIMIT)
    if not matches:
        return None, matches

    # Broad / ambiguous product phrases should not auto-pick
    broad_queries = {
        "eye cream",
        "cleanser",
        "foundation",
        "lipstick",
        "mascara",
        "serum",
        "moisturizer",
        "night cream",
        "day cream",
    }
    if q in broad_queries:
        return None, matches

    top = matches[0]
    second = matches[1] if len(matches) > 1 else {"score": 0}

    if top["score"] >= 88 and (top["score"] - second["score"]) >= 6:
        return top, matches

    return None, matches


def _normalize_match_text(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _find_exact_catalog_match(catalog: List[dict], product_text: str) -> Optional[dict]:
    target = _normalize_match_text(product_text)
    if not target:
        return None

    for c in catalog:
        name_norm = _normalize_match_text(c.get("product_name") or "")
        if target == name_norm:
            return c

        raw_terms = (c.get("search_terms") or "").strip()
        if raw_terms:
            for term in raw_terms.split("|"):
                if target == _normalize_match_text(term):
                    return c

    return None
