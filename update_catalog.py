"""
Logs into InTouch, scrapes the full One Page Order Sheet in both English
and Spanish, and upserts catalog/en.csv and catalog/es.csv.

- New SKUs are appended with empty search_terms
- Existing SKUs have name/price updated if changed
- Old SKUs are never removed (consultants may still have old stock)
- ® is stripped from product names

Usage:
    python update_catalog.py <consultant_number> <intouch_password>
"""
import csv
import sys
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CATALOG_DIR = Path(__file__).parent / "catalog"
ORDER_URL   = "https://order.marykayintouch.com/orders?lang=en_US"

LANGUAGES = [
    {"lang": "en", "opos_url": "https://order.marykayintouch.com/opos?lang=en_US"},
    {"lang": "es", "opos_url": "https://order.marykayintouch.com/opos?lang=es_US"},
]


def login(page, username: str, password: str) -> None:
    page.goto(ORDER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    try:
        num_field = page.get_by_role("textbox", name="Consultant Number")
        num_field.wait_for(state="visible", timeout=5000)
        num_field.fill(username)
        page.get_by_role("textbox", name="Password").fill(password)
        page.wait_for_timeout(200)
        page.get_by_text("Log In").click()
        page.wait_for_timeout(4000)
        print("Logged in.")
    except PlaywrightTimeoutError:
        print("Already authenticated.")


def scrape_products(page, opos_url: str) -> list[dict]:
    """Navigate to OPOS for a given language, expand all, return product list."""
    print(f"  Loading {opos_url} ...")
    page.goto(opos_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    print("  Clicking Expand All...")
    try:
        page.get_by_text("Expand All").click()
        page.wait_for_timeout(8000)
    except Exception as e:
        print(f"  Warning: could not click Expand All: {e}")

    print("  Extracting products...")
    products = page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.row.single-order-product.product');
            const results = [];
            rows.forEach(row => {
                const skuEl   = row.querySelector('.product-manufacturersku');
                const nameEl  = row.querySelector('.line-item-name-text');
                const priceEl = row.querySelector('.pricing[data-value]');
                const qtyEl   = row.querySelector('input.quantity-select[data-gtmdata]');
                if (!skuEl || !nameEl || !priceEl) return;

                // Only include Section 1 (sellable) products — Section 2 is samples/collateral
                if (qtyEl) {
                    try {
                        const gtm = JSON.parse(qtyEl.getAttribute('data-gtmdata') || '{}');
                        if (String(gtm.sectionCode) !== '1') return;
                    } catch (e) {}
                }

                const sku  = skuEl.textContent.trim();
                let name   = nameEl.textContent.trim().replace(/\u00ae/g, '').trim();
                const price = parseFloat(priceEl.getAttribute('data-value') || '0');

                // Append shade/variant name if present (e.g. lipstick colors, foundation shades)
                if (qtyEl) {
                    try {
                        const gtm = JSON.parse(qtyEl.getAttribute('data-gtmdata') || '{}');
                        const variant = (gtm.itemVariantName || '').replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
                        if (variant) name = name + ' - ' + variant;
                    } catch (e) {}
                }

                if (sku && name && price > 0) {
                    results.push({ sku, product_name: name, price });
                }
            });
            return results;
        }
    """)
    print(f"  Found {len(products)} products.")
    return products


def load_catalog(path: Path) -> dict[str, dict]:
    catalog = {}
    if not path.exists():
        return catalog
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            if sku:
                catalog[sku] = {
                    "sku":          sku,
                    "product_name": row.get("product_name", ""),
                    "price":        row.get("price", ""),
                    "search_terms": row.get("search_terms", ""),
                    "date_added":   row.get("date_added", ""),
                }
    return catalog


def save_catalog(catalog: dict[str, dict], path: Path, scraped_order: list[dict] | None = None) -> None:
    # Items currently in OPOS — preserve scrape order
    if scraped_order:
        opos_skus = [item["sku"] for item in scraped_order]
        opos_set  = set(opos_skus)
        active_rows = [catalog[sku] for sku in opos_skus if sku in catalog]
        # Items no longer in OPOS (discontinued) — appended at bottom, sorted by date_added desc
        dropped_rows = sorted(
            [r for r in catalog.values() if r["sku"] not in opos_set],
            key=lambda r: r.get("date_added") or "",
            reverse=True,
        )
        rows = active_rows + dropped_rows
    else:
        rows = sorted(catalog.values(), key=lambda r: r["sku"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sku", "product_name", "price", "search_terms", "date_added"])
        writer.writeheader()
        writer.writerows(rows)


def upsert(catalog: dict[str, dict], scraped: list[dict]) -> tuple[int, int]:
    added = updated = 0
    for item in scraped:
        sku       = item["sku"]
        name      = item["product_name"]
        price_str = f"{item['price']:.2f}"

        if sku not in catalog:
            catalog[sku] = {"sku": sku, "product_name": name, "price": price_str, "search_terms": "", "date_added": date.today().isoformat()}
            added += 1
        else:
            existing = catalog[sku]
            changed = False
            if existing["product_name"] != name:
                existing["product_name"] = name
                changed = True
            if existing["price"] != price_str:
                existing["price"] = price_str
                changed = True
            if changed:
                updated += 1
    return added, updated


def main(username: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        login(page, username, password)

        results = {}
        for lang_cfg in LANGUAGES:
            lang = lang_cfg["lang"]
            print(f"\n[{lang.upper()}]")
            scraped = scrape_products(page, lang_cfg["opos_url"])
            results[lang] = scraped

        browser.close()

    for lang_cfg in LANGUAGES:
        lang    = lang_cfg["lang"]
        scraped = results[lang]

        if not scraped:
            print(f"\n[{lang.upper()}] No products found — skipping.")
            continue

        path    = CATALOG_DIR / f"{lang}.csv"
        catalog = load_catalog(path)
        before  = len(catalog)
        added, updated = upsert(catalog, scraped)
        save_catalog(catalog, path, scraped_order=scraped)

        print(f"\n[{lang.upper()}] Done.")
        print(f"  Catalog before : {before} SKUs")
        print(f"  Scraped        : {len(scraped)} products")
        print(f"  Added          : {added}")
        print(f"  Updated        : {updated}")
        print(f"  Total now      : {len(catalog)} SKUs")
        print(f"  Saved to       : {path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python update_catalog.py <consultant_number> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
