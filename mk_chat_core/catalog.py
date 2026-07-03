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


def get_catalog_path_for_language(language: str) -> Path:
    language = (language or "en").strip().lower()
    if language == "es":
        return CATALOG_DIR / "es.csv"
    return CATALOG_DIR / "en.csv"


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


def _fmt_product_lookup_single(m: dict) -> str:
    """Format a single product lookup result with optional PDF links."""
    price = _fmt_price_with_change(m)
    line = f"{m['product_name']} — {price}".strip(" —")
    parts = ["<strong>Product Look Up</strong>", line]
    links = []
    if m.get("fact_sheet_url"):
        links.append(f'<a href="{m["fact_sheet_url"]}" target="_blank">Product Fact Sheet</a>')
    if m.get("order_of_application_url"):
        links.append(f'<a href="{m["order_of_application_url"]}" target="_blank">Order of Application</a>')
    if links:
        parts.append(" &bull; ".join(links))
    return "<br>".join(parts)


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
