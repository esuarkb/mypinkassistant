"""
Scrape a Director Early Ordering page and write CSVs in the same format as en.csv / es.csv.

Usage:
    python scrape_deo.py <url> [output_stem] [--merge] [--both]

Examples:
    # Preview only (no merge):
    python scrape_deo.py "https://order.marykayintouch.com/summer-director-early-ordering/?lang=en_US" deo_summer2026

    # Merge EN only:
    python scrape_deo.py "https://...?lang=en_US" deo_summer2026 --merge

    # Merge both EN and ES in one run (derives ES URL by swapping lang param):
    python scrape_deo.py "https://...?lang=en_US" deo_summer2026 --merge --both

--both scrapes EN then ES, merges into en.csv and es.csv respectively.
       The ES URL is derived automatically by replacing lang=en_US with lang=es_US.
"""
import re
import csv
import sys
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from dotenv import dotenv_values
from cryptography.fernet import Fernet
import psycopg2

from playwright_automation.inventory_import import login_order_site

TODAY = date.today().isoformat()
CATALOG_DIR = Path(__file__).parent / "catalog"

FIELDS = ["sku", "product_name", "price", "search_terms",
          "date_added", "last_seen", "display_name_card", "display_name_sms"]

# Name fragments that identify samples / collateral — not orderable products
# Covers both English and Spanish collateral names
EXCLUDE_RE = re.compile(
    r"sample strip"         # EN sample strips
    r"|the look\b"          # EN "The Look" booklet
    r"|la imagen\b"         # ES "The Look" booklet
    r"|brochure"            # EN brochures
    r"|folleto"             # ES brochures (folletos)
    r"|flip chart"          # EN flip chart pages
    r"|rotafolio"           # ES flip chart pages
    r"|wands? pk\."         # EN mascara wand packs
    r"|varitas"             # ES wands (varitas para muestra)
    r"|pk\./\d+"            # pack notation "pk./10", "pk./6"
    r"|paq\./\d+",          # ES pack notation "paq./10"
    re.IGNORECASE,
)

# Prefixes that should NOT get "Mary Kay " prepended
NO_PREFIX = (
    "mary kay", "timewise", "mkmen", "special-edition", "limited-edition",
    "clear proof", "lash love", "gel semi", "domain", "belara", "bella",
    "forever", "live fearlessly", "thinking of you", "enchanted", "cityscape",
    "beyond", "mk high", "mint bliss", "fragrance-free", "white tea",
)

EXTRACT_JS = """
() => {
    const STRIP = str => str.replace(/[®™†*]/g, "").replace(/\\s+/g, " ").trim();
    const items = [];

    document.querySelectorAll(".tile-body-section.main-info").forEach(el => {
        const nameEl = el.querySelector(".pdp-link");
        if (!nameEl) return;
        const name = STRIP(nameEl.innerText);
        if (!name) return;

        const shadeEl = el.querySelector(".variation-name");
        const shade = shadeEl ? STRIP(shadeEl.innerText) : "";

        const skuEl = el.querySelector(".variation-id");
        const skuText = skuEl ? skuEl.innerText : el.innerText;
        const skuMatch = skuText.match(/([0-9]{8})/);
        if (!skuMatch) return;
        const sku = skuMatch[1];

        let price = "";
        let sib = el.nextElementSibling;
        while (sib) {
            const p = sib.innerText.trim();
            if (/^\\$[\\d.]+/.test(p)) { price = p.replace("$", "").trim(); break; }
            sib = sib.nextElementSibling;
        }

        items.push({ name, shade, sku, price });
    });

    return items;
}
"""


def get_credentials():
    env = dotenv_values(Path(__file__).parent / ".env.production")
    enc_key = dotenv_values(Path(__file__).parent / ".env")["MK_ENC_KEY"]
    fernet = Fernet(enc_key.encode())
    conn = psycopg2.connect(env["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        "SELECT intouch_username, intouch_password_enc "
        "FROM consultants WHERE email = 'briankrause@gmail.com'"
    )
    row = cur.fetchone()
    conn.close()
    return row[0], fernet.decrypt(row[1].encode()).decode()


def build_product_name(name: str, shade: str) -> str:
    full = name + (" - " + shade if shade else "")
    if not any(full.lower().startswith(p) for p in NO_PREFIX):
        full = "Mary Kay " + full
    return full


def build_display_names(product_name: str, lang: str = "en") -> tuple[str, str]:
    card = re.sub(r"^Special-Edition\s+", "", product_name, flags=re.IGNORECASE)
    card = re.sub(r"^Mary Kay\s+", "", card, flags=re.IGNORECASE)
    if lang == "es":
        card = re.sub(r"\s+de edición especial", "", card, flags=re.IGNORECASE)
    card = card.strip()
    sms = re.sub(r"\s+[-–]\s+.+$", "", card).strip()
    return card, sms


def load_existing_skus_from(path: Path) -> set:
    skus = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sku = (row.get("sku") or "").strip()
                if sku:
                    skus.add(sku)
    return skus


def scrape(url: str, username: str, password: str) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        login_order_site(page, username, password)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(2000)

        clicks = 0
        while True:
            try:
                btn = page.locator("button.btn-outline-secondary.btn-lg.col-12")
                btn.wait_for(state="visible", timeout=3000)
                btn.scroll_into_view_if_needed()
                btn.click()
                page.wait_for_timeout(1800)
                clicks += 1
            except PWTimeout:
                break

        total = page.locator(".tile-body-section.main-info").count()
        print(f"  Loaded {total} tiles ({clicks} Load More clicks)")
        items = page.evaluate(EXTRACT_JS)
        browser.close()
    return items


def process_and_merge(url: str, lang: str, stem: str, do_merge: bool, username: str, password: str):
    target_csv = CATALOG_DIR / ("en.csv" if lang == "en" else "es.csv")
    out_csv    = CATALOG_DIR / f"{stem}.csv"

    print(f"\n{'='*60}")
    print(f"[{lang.upper()}] {url}")
    raw_items = scrape(url, username, password)

    products, collateral = [], []
    for item in raw_items:
        full = item["name"] + (" - " + item["shade"] if item["shade"] else "")
        if EXCLUDE_RE.search(full):
            collateral.append(full)
        else:
            item["product_name"] = build_product_name(item["name"], item["shade"])
            item["display_name_card"], item["display_name_sms"] = build_display_names(item["product_name"], lang)
            products.append(item)

    print(f"  Products: {len(products)}   Collateral excluded: {len(collateral)}")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for item in products:
            writer.writerow({
                "sku": item["sku"], "product_name": item["product_name"],
                "price": item["price"], "search_terms": "",
                "date_added": TODAY, "last_seen": TODAY,
                "display_name_card": item["display_name_card"],
                "display_name_sms":  item["display_name_sms"],
            })
    print(f"  Staging CSV → {out_csv.name}")

    if do_merge:
        existing  = load_existing_skus_from(target_csv)
        new_items = [i for i in products if i["sku"] not in existing]
        already   = [i for i in products if i["sku"] in existing]
        print(f"  Merge → {target_csv.name}: {len(new_items)} new, {len(already)} already present")
        if new_items:
            with open(target_csv, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                for item in new_items:
                    writer.writerow({
                        "sku": item["sku"], "product_name": item["product_name"],
                        "price": item["price"], "search_terms": "",
                        "date_added": TODAY, "last_seen": TODAY,
                        "display_name_card": item["display_name_card"],
                        "display_name_sms":  item["display_name_sms"],
                    })


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python scrape_deo.py <url> [output_stem] [--merge] [--both]")
        sys.exit(1)

    en_url    = args[0]
    es_url    = en_url.replace("lang=en_US", "lang=es_US")
    do_merge  = "--merge" in args
    do_both   = "--both" in args
    name_args = [a for a in args[1:] if not a.startswith("--")]
    stem      = name_args[0] if name_args else "deo_staging"

    username, password = get_credentials()

    process_and_merge(en_url, "en", stem,          do_merge, username, password)
    if do_both:
        process_and_merge(es_url, "es", stem + "_es", do_merge, username, password)

    print("\nDone.")


if __name__ == "__main__":
    main()
