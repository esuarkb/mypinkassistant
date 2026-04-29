"""
Examines the InTouch order list page to see what data is available
per row WITHOUT clicking into detail pages.

Looks for: order number, order type, order source, date, amount —
anything visible in the list that could let us skip detail-page scraping.

Usage:
    python dump_order_list_structure.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import dotenv_values

ORDER_SITE_BASE = "https://order.marykayintouch.com"

ORDER_TYPE_COSMETIC = (
    "1%2C4%2C5%2C10%2C13%2C14%2C15%2C18%2C19%2C20"
    "%2C22%2C23%2C24%2C25%2C26%2C28%2C29%2C30%2C31%2C32"
)

def main() -> None:
    env = dotenv_values(Path(__file__).parent / ".env")
    username = env.get("INTOUCH_USER", "")
    password = env.get("INTOUCH_PASS", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Login
        print("Logging in...")
        page.goto(f"{ORDER_SITE_BASE}/orders?lang=en_US", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        try:
            num_field = page.get_by_role("textbox", name="Consultant Number")
            num_field.wait_for(state="visible", timeout=4000)
            num_field.fill(username)
            page.get_by_role("textbox", name="Password").fill(password)
            page.wait_for_timeout(200)
            page.get_by_text("Log In").click()
            page.wait_for_timeout(3000)
            print("Logged in.")
        except PlaywrightTimeoutError:
            print("Already authenticated.")

        # --- Page 1: Cosmetic-filtered list (what the scraper uses) ---
        cosmetic_url = (
            f"{ORDER_SITE_BASE}/orders?lang=en_US"
            f"&placedFor=yourself"
            f"&orderDate=days90"
            f"&orderType={ORDER_TYPE_COSMETIC}"
        )
        print(f"\nNavigating to cosmetic-filtered list:\n  {cosmetic_url}")
        page.goto(cosmetic_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        Path("dump_order_list_cosmetic.html").write_text(page.content(), encoding="utf-8")
        print("Saved dump_order_list_cosmetic.html")

        # Examine the DOM for order rows — try common row selectors
        print("\n" + "="*60)
        print("Examining order row structure (cosmetic filter):")
        print("="*60)

        # Try to find order row containers
        for selector in [
            "tr",
            "[class*='order-row']",
            "[class*='order-item']",
            "[class*='order-list']",
            "[class*='order-card']",
            "[data-order]",
            "[data-order-no]",
            "[data-order-number]",
        ]:
            els = page.locator(selector).all()
            if els:
                print(f"\n  Found {len(els)} elements matching '{selector}'")
                for i, el in enumerate(els[:3]):
                    try:
                        text = el.inner_text()[:200].replace("\n", " | ").strip()
                        attrs = page.evaluate("el => Array.from(el.attributes).map(a => a.name+'='+a.value).join(' ')", el.element_handle())
                        print(f"    [{i}] attrs: {attrs}")
                        print(f"         text: {text!r}")
                    except Exception as e:
                        print(f"    [{i}] error: {e}")

        # Also dump all unique class names on the page to find row containers
        print("\n" + "="*60)
        print("All classes on elements containing 8-digit order numbers:")
        print("="*60)
        classes = page.evaluate("""
            () => {
                const seen = new Set();
                document.querySelectorAll('a').forEach(a => {
                    const t = (a.textContent || '').trim();
                    if (/^\\d{8}$/.test(t)) {
                        let el = a;
                        for (let i = 0; i < 5; i++) {
                            el = el.parentElement;
                            if (!el) break;
                            if (el.className) seen.add(el.tagName + '.' + el.className.trim().replace(/\\s+/g, '.'));
                        }
                    }
                });
                return Array.from(seen);
            }
        """)
        for c in classes:
            print(f"  {c}")

        # --- Page 2: Unfiltered list to see all order types ---
        all_url = (
            f"{ORDER_SITE_BASE}/orders?lang=en_US"
            f"&placedFor=yourself"
            f"&orderDate=days90"
        )
        print(f"\n\nNavigating to UNFILTERED list (all order types):\n  {all_url}")
        page.goto(all_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        Path("dump_order_list_all.html").write_text(page.content(), encoding="utf-8")
        print("Saved dump_order_list_all.html")

        # Print all order links with surrounding text to see if type is visible in list
        print("\n" + "="*60)
        print("All orders visible (unfiltered) — surrounding text:")
        print("="*60)
        order_data = page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('a').forEach(a => {
                    const t = (a.textContent || '').trim();
                    if (!/^\\d{8}$/.test(t)) return;
                    // Walk up to grab the row/card container text
                    let el = a.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!el) break;
                        const txt = el.innerText || '';
                        if (txt.length > 20 && txt.length < 500) {
                            results.push({
                                order_no: t,
                                href: a.getAttribute('href') || '',
                                row_text: txt.replace(/\\n/g, ' | ').trim()
                            });
                            return;
                        }
                        el = el.parentElement;
                    }
                    results.push({order_no: t, href: a.getAttribute('href') || '', row_text: ''});
                });
                return results;
            }
        """)
        for row in order_data:
            print(f"\n  Order: {row['order_no']}")
            print(f"  Text:  {row['row_text'][:300]!r}")

        input("\nPress Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    main()
