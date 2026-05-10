"""
Logs into InTouch, scrapes the full One Page Order Sheet in both English
and Spanish, and upserts catalog/en.csv and catalog/es.csv.

- New SKUs are appended with empty search_terms
- Existing SKUs have name/price updated if changed
- Old SKUs are never removed (consultants may still have old stock)
- ® is stripped from product names
- Emails a change summary to the owner after each run

Usage:
    python update_catalog.py <consultant_number> <intouch_password>
"""
import csv
import os
import sys
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

OWNER_EMAIL = "briankrause@gmail.com"

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
                let name   = nameEl.textContent.trim()
                    .replace(/\u00ae|\u2122|\u2020|[*]+/g, '')  // strip ®, ™, †, * (and **)
                    .replace(/,?\\s*pk\\.\\/\\d+\\s*pairs?/gi, '')   // strip ", pk./30 pairs" suffix
                    .trim();
                const price = parseFloat(priceEl.getAttribute('data-value') || '0');

                // Append shade/variant name if present (e.g. lipstick colors, foundation shades)
                // First try GTM data, then fall back to visible variant text on the page
                let variant = '';
                if (qtyEl) {
                    try {
                        const gtm = JSON.parse(qtyEl.getAttribute('data-gtmdata') || '{}');
                        variant = (gtm.itemVariantName || '').replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
                    } catch (e) {}
                }
                if (!variant) {
                    // Look for visible variant text element (skin type, shade name shown on page)
                    // .sku-formula-name covers skin type variants (Normal/Dry, Combination/Oily)
                    const variantEl = row.querySelector('.sku-formula-name, .product-variant-name, .variant-name, .product-shade, [class*="variant"]');
                    if (variantEl) {
                        variant = variantEl.textContent.trim();
                    }
                }
                if (variant) name = name + ' - ' + variant;

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
                    "sku":                    sku,
                    "product_name":           row.get("product_name", ""),
                    "price":                  row.get("price", ""),
                    "search_terms":           row.get("search_terms", ""),
                    "date_added":             row.get("date_added", ""),
                    "last_seen":              row.get("last_seen", ""),
                    "display_name_card":      row.get("display_name_card", ""),
                    "display_name_sms":       row.get("display_name_sms", ""),
                    "predecessor_sku":        row.get("predecessor_sku", ""),
                    "fact_sheet_url":         row.get("fact_sheet_url", ""),
                    "order_of_application_url": row.get("order_of_application_url", ""),
                }
    return catalog


def save_catalog(catalog: dict[str, dict], path: Path, scraped_order: list[dict] | None = None) -> None:
    # Items currently in OPOS — preserve scrape order
    if scraped_order:
        # Deduplicate scrape order — same SKU can appear twice if listed under multiple categories
        seen_skus: set[str] = set()
        opos_skus = []
        for item in scraped_order:
            if item["sku"] not in seen_skus:
                opos_skus.append(item["sku"])
                seen_skus.add(item["sku"])
        opos_set  = seen_skus
        active_rows = [catalog[sku] for sku in opos_skus if sku in catalog]
        # Items not in this scrape — only treat as dropped if last_seen > 60 days ago (or never seen)
        cutoff = (date.today() - __import__("datetime").timedelta(days=60)).isoformat()
        dropped_rows = sorted(
            [r for r in catalog.values() if r["sku"] not in opos_set
             and (r.get("last_seen") or r.get("date_added") or "") < cutoff],
            key=lambda r: r.get("date_added") or "",
            reverse=True,
        )
        # Items not in scrape but seen recently — keep them in active position (end of active list)
        recent_rows = [
            r for r in catalog.values() if r["sku"] not in opos_set
            and (r.get("last_seen") or r.get("date_added") or "") >= cutoff
        ]
        rows = active_rows + recent_rows + dropped_rows
    else:
        rows = sorted(catalog.values(), key=lambda r: r["sku"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sku", "product_name", "price", "search_terms", "date_added", "last_seen", "display_name_card", "display_name_sms", "predecessor_sku", "fact_sheet_url", "order_of_application_url"])
        writer.writeheader()
        writer.writerows(rows)


def _normalize_name(name: str) -> str:
    import re
    return re.sub(r"[®™\u00ae\u2122\u2020]", "", name).strip().lower()


def upsert(catalog: dict[str, dict], scraped: list[dict]) -> tuple[list, list, list]:
    added_items: list[dict] = []
    updated_items: list[dict] = []
    labeled_items: list[dict] = []
    scraped_skus = {item["sku"] for item in scraped}

    for item in scraped:
        sku       = item["sku"]
        name      = item["product_name"]
        price_str = f"{item['price']:.2f}"

        today = date.today().isoformat()
        if sku not in catalog:
            catalog[sku] = {"sku": sku, "product_name": name, "price": price_str, "search_terms": "", "date_added": today, "last_seen": today, "display_name_card": "", "display_name_sms": "", "predecessor_sku": "", "fact_sheet_url": "", "order_of_application_url": ""}
            added_items.append({"sku": sku, "product_name": name, "price": price_str})
        else:
            existing = catalog[sku]
            changes = []
            existing_name = existing["product_name"]
            # Don't overwrite if we've manually added a suffix (variant, Old SKU label, etc.)
            name_is_enriched = (
                "(Old SKU)" in existing_name
                or existing_name.lower().startswith(name.lower() + " ")
            )
            if existing_name != name and not name_is_enriched:
                changes.append({"field": "name", "before": existing_name, "after": name})
                existing["product_name"] = name
            if existing["price"] != price_str:
                changes.append({"field": "price", "before": existing["price"], "after": price_str})
                existing["price"] = price_str
            existing["last_seen"] = today
            if changes:
                updated_items.append({"sku": sku, "product_name": name, "changes": changes})

    # For every newly added SKU, find any existing catalog entry with the same
    # normalized name that's no longer in OPOS → label it (Old SKU) and copy display names
    for item in added_items:
        target = _normalize_name(item["product_name"])
        new_entry = catalog[item["sku"]]
        for other_sku, other in catalog.items():
            if other_sku == item["sku"]:
                continue
            if other_sku in scraped_skus:
                continue  # still active — never label
            if "(Old SKU)" in other["product_name"]:
                continue  # already labeled
            if _normalize_name(other["product_name"]) == target:
                if not new_entry.get("display_name_card"):
                    new_entry["display_name_card"] = other.get("display_name_card", "")
                if not new_entry.get("display_name_sms"):
                    new_entry["display_name_sms"] = other.get("display_name_sms", "")
                new_entry["predecessor_sku"] = other_sku
                other["product_name"] = other["product_name"] + " (Old SKU)"
                labeled_items.append({"sku": other_sku, "product_name": other["product_name"], "replaced_by": item["sku"]})
                print(f"  Auto-labeled: {other_sku} → {other['product_name']}")

    return added_items, updated_items, labeled_items


def scrape_product_links(page, catalog: dict, scraped_skus: set) -> dict[str, dict]:
    """
    Click each product popup on the already-loaded/expanded OPOS page to extract PDF links.
    Only fetches links for SKUs missing both fact_sheet_url and order_of_application_url.
    Returns {sku: {fact_sheet_url, order_of_application_url}}.
    """
    skus_needing = {
        sku for sku in scraped_skus
        if not (catalog.get(sku, {}).get("fact_sheet_url") or
                catalog.get(sku, {}).get("order_of_application_url"))
    }
    if not skus_needing:
        print("  All products already have PDF links — skipping popup scrape.")
        return {}

    print(f"  Scraping PDF links for {len(skus_needing)} products (first-run may take several minutes)...")
    links: dict[str, dict] = {}
    seen: set[str] = set()
    checked = 0

    rows = page.query_selector_all('.row.single-order-product.product')
    for row in rows:
        sku_el = row.query_selector('.product-manufacturersku')
        if not sku_el:
            continue
        sku = sku_el.text_content().strip()
        if sku not in skus_needing or sku in seen:
            continue
        seen.add(sku)
        checked += 1
        if checked % 50 == 0:
            print(f"    ...{checked}/{len(skus_needing)} checked, {len(links)} links found so far")

        name_el = row.query_selector('.line-item-name-text')
        if not name_el:
            continue
        try:
            name_el.click()
            page.wait_for_timeout(1500)
            found = page.evaluate("""
                () => {
                    const result = {fact_sheet_url: '', order_of_application_url: ''};
                    document.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href || '';
                        if (!href.toLowerCase().includes('.pdf')) return;
                        const text = (a.textContent || '').toLowerCase();
                        if (text.includes('fact sheet')) result.fact_sheet_url = href;
                        else if (text.includes('order of application')) result.order_of_application_url = href;
                    });
                    return result;
                }
            """)
            if found.get('fact_sheet_url') or found.get('order_of_application_url'):
                links[sku] = {
                    'fact_sheet_url': found.get('fact_sheet_url', ''),
                    'order_of_application_url': found.get('order_of_application_url', ''),
                }
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
        except Exception as e:
            print(f"    Warning: SKU {sku}: {e}")
            try:
                page.keyboard.press('Escape')
                page.wait_for_timeout(300)
            except Exception:
                pass

    print(f"  Found PDF links for {len(links)} of {len(skus_needing)} products.")
    return links


def _send_change_email(lang_reports: list[dict]) -> None:
    try:
        from dotenv import dotenv_values
        import requests as _requests
        env = dotenv_values(Path(__file__).parent / ".env")
        api_key  = env.get("RESEND_API_KEY", "").strip()
        mail_from = env.get("MAIL_FROM", "").strip()
        if not api_key or not mail_from:
            print("  (email skipped — RESEND_API_KEY or MAIL_FROM not set)")
            return

        today_str = date.today().strftime("%B %d, %Y")
        any_changes = any(
            r["added"] or r["updated"] or r["labeled"]
            for r in lang_reports
        )

        rows_html = ""
        for r in lang_reports:
            lang_label = r["lang"].upper()
            if not (r["added"] or r["updated"] or r["labeled"]):
                rows_html += f"<tr><td colspan='3' style='padding:8px 12px;color:#888'>[{lang_label}] No changes.</td></tr>"
                continue

            rows_html += f"<tr><td colspan='3' style='padding:10px 12px 4px;font-weight:700;background:#f7f7f8'>[{lang_label}]</td></tr>"

            for item in r["added"]:
                rows_html += (
                    f"<tr>"
                    f"<td style='padding:6px 12px;color:#2e7d32'>NEW</td>"
                    f"<td style='padding:6px 12px'>{item['sku']}</td>"
                    f"<td style='padding:6px 12px'>{item['product_name']} — ${item['price']}</td>"
                    f"</tr>"
                )
            for item in r["updated"]:
                for ch in item["changes"]:
                    if ch["field"] == "price":
                        desc = f"Price: ${ch['before']} → ${ch['after']}"
                    else:
                        desc = f"Name: {ch['before']} → {ch['after']}"
                    rows_html += (
                        f"<tr>"
                        f"<td style='padding:6px 12px;color:#e65100'>CHANGED</td>"
                        f"<td style='padding:6px 12px'>{item['sku']}</td>"
                        f"<td style='padding:6px 12px'>{desc}</td>"
                        f"</tr>"
                    )
            for item in r["labeled"]:
                rows_html += (
                    f"<tr>"
                    f"<td style='padding:6px 12px;color:#888'>OLD SKU</td>"
                    f"<td style='padding:6px 12px'>{item['sku']}</td>"
                    f"<td style='padding:6px 12px'>{item['product_name']} (replaced by {item['replaced_by']})</td>"
                    f"</tr>"
                )

        subject = f"MK Catalog Update — {today_str}" + ("  ⚠️ Changes detected" if any_changes else " — No changes")
        html = f"""
        <div style="font-family:system-ui,sans-serif;max-width:700px;margin:0 auto">
          <h2 style="margin-bottom:4px">MK Catalog Update</h2>
          <p style="color:#888;margin-top:0">{today_str}</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px">
            <thead>
              <tr style="border-bottom:2px solid #e6e6e6">
                <th style="padding:8px 12px;text-align:left;width:110px">Type</th>
                <th style="padding:8px 12px;text-align:left;width:110px">SKU</th>
                <th style="padding:8px 12px;text-align:left">Detail</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """

        _requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": mail_from, "to": [OWNER_EMAIL], "subject": subject, "html": html},
            timeout=15,
        ).raise_for_status()
        print(f"  Email sent to {OWNER_EMAIL}")
    except Exception as e:
        print(f"  (email failed: {e})")


def _apply_en_replacements(en_labeled: list[dict], es_catalog: dict[str, dict]) -> list[dict]:
    """Mirror EN-detected SKU replacements onto the ES catalog by SKU number."""
    applied = []
    for item in en_labeled:
        old_sku = item["sku"]
        new_sku = item["replaced_by"]
        if old_sku not in es_catalog:
            continue
        if "(Old SKU)" in es_catalog[old_sku]["product_name"]:
            continue  # already handled
        if new_sku in es_catalog:
            new_es = es_catalog[new_sku]
            old_es = es_catalog[old_sku]
            if not new_es.get("display_name_card"):
                new_es["display_name_card"] = old_es.get("display_name_card", "")
            if not new_es.get("display_name_sms"):
                new_es["display_name_sms"] = old_es.get("display_name_sms", "")
        es_catalog[old_sku]["product_name"] += " (Old SKU)"
        applied.append({"sku": old_sku, "product_name": es_catalog[old_sku]["product_name"], "replaced_by": new_sku})
        print(f"  [ES] Mirrored label: {old_sku} → {es_catalog[old_sku]['product_name']}")
    return applied


def _mirror_links_to_es(en_catalog: dict, es_catalog: dict) -> None:
    """Copy fact_sheet_url / order_of_application_url from EN to ES entries by SKU."""
    for sku, en_entry in en_catalog.items():
        if sku not in es_catalog:
            continue
        es_entry = es_catalog[sku]
        for field in ("fact_sheet_url", "order_of_application_url"):
            if en_entry.get(field) and not es_entry.get(field):
                es_entry[field] = en_entry[field]


def _print_lang_report(lang: str, before: int, scraped: list, catalog: dict,
                       added: list, updated: list, labeled: list, path: Path) -> None:
    print(f"\n[{lang.upper()}] Done.")
    print(f"  Catalog before : {before} SKUs")
    print(f"  Scraped        : {len(scraped)} products")
    print(f"  Total now      : {len(catalog)} SKUs")
    print(f"  Saved to       : {path}")

    if not (added or updated or labeled):
        print("  No changes.")
        return

    if added:
        print(f"\n  NEW ({len(added)}):")
        for item in added:
            print(f"    + {item['sku']}  {item['product_name']}  ${item['price']}")

    if updated:
        print(f"\n  CHANGED ({len(updated)}):")
        for item in updated:
            for ch in item["changes"]:
                if ch["field"] == "price":
                    print(f"    ~ {item['sku']}  price: ${ch['before']} → ${ch['after']}")
                else:
                    print(f"    ~ {item['sku']}  name: {ch['before']} → {ch['after']}")

    if labeled:
        print(f"\n  OLD SKU LABELED ({len(labeled)}):")
        for item in labeled:
            print(f"    ! {item['sku']}  {item['product_name']}  (replaced by {item['replaced_by']})")


def main(username: str, password: str) -> None:
    en_scraped: list[dict] = []
    es_scraped: list[dict] = []
    en_links:   dict[str, dict] = {}
    en_catalog: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        login(page, username, password)

        # ── EN: scrape products then PDF links while page is still open ──
        print("\n[EN]")
        en_scraped = scrape_products(page, next(c["opos_url"] for c in LANGUAGES if c["lang"] == "en"))
        if en_scraped:
            en_path    = CATALOG_DIR / "en.csv"
            en_catalog = load_catalog(en_path)
            en_scraped_skus = {item["sku"] for item in en_scraped}
            en_links = scrape_product_links(page, en_catalog, en_scraped_skus)

        # ── ES: scrape products ──
        print("\n[ES]")
        es_scraped = scrape_products(page, next(c["opos_url"] for c in LANGUAGES if c["lang"] == "es"))

        browser.close()

    lang_reports = []

    # ── EN: upsert, apply PDF links, save ──
    if not en_scraped:
        print("\n[EN] No products found — skipping.")
        en_labeled: list[dict] = []
    else:
        en_path   = CATALOG_DIR / "en.csv"
        en_before = len(en_catalog)
        en_added, en_updated, en_labeled = upsert(en_catalog, en_scraped)
        for sku, link_data in en_links.items():
            if sku in en_catalog:
                if link_data.get("fact_sheet_url"):
                    en_catalog[sku]["fact_sheet_url"] = link_data["fact_sheet_url"]
                if link_data.get("order_of_application_url"):
                    en_catalog[sku]["order_of_application_url"] = link_data["order_of_application_url"]
        save_catalog(en_catalog, en_path, scraped_order=en_scraped)
        _print_lang_report("en", en_before, en_scraped, en_catalog, en_added, en_updated, en_labeled, en_path)
        lang_reports.append({"lang": "en", "added": en_added, "updated": en_updated, "labeled": en_labeled})

    # ── ES: upsert, mirror EN labels + PDF links, save ──
    if not es_scraped:
        print("\n[ES] No products found — skipping.")
    else:
        es_path    = CATALOG_DIR / "es.csv"
        es_catalog = load_catalog(es_path)
        es_before  = len(es_catalog)
        es_added, es_updated, es_labeled = upsert(es_catalog, es_scraped)
        if en_labeled:
            es_mirrored = _apply_en_replacements(en_labeled, es_catalog)
            es_labeled  = es_labeled + es_mirrored
        if en_catalog:
            _mirror_links_to_es(en_catalog, es_catalog)
        save_catalog(es_catalog, es_path, scraped_order=es_scraped)
        _print_lang_report("es", es_before, es_scraped, es_catalog, es_added, es_updated, es_labeled, es_path)
        lang_reports.append({"lang": "es", "added": es_added, "updated": es_updated, "labeled": es_labeled})

    any_changes = any(
        r["added"] or r["updated"] or r["labeled"]
        for r in lang_reports
    )
    if any_changes:
        print("\nSending change summary email...")
        _send_change_email(lang_reports)
    else:
        print("\nNo changes — skipping email.")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        from dotenv import dotenv_values
        _env = dotenv_values(Path(__file__).parent / ".env")
        _number = _env.get("INTOUCH_USER", "").strip()
        _password = _env.get("INTOUCH_PASS", "").strip()
        if not _number or not _password:
            print("Usage: python update_catalog.py <consultant_number> <password>")
            print("Or set INTOUCH_USER and INTOUCH_PASS in .env")
            sys.exit(1)
        main(_number, _password)
