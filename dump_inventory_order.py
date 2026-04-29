"""
Dumps the InTouch order detail page for a given order number.
Saves the full HTML and prints all div.order-product-line-item elements
with their data-sku and data-quantity attributes so we can see exactly
what the scraper is reading.

Usage:
    python dump_inventory_order.py <order_no>
    python dump_inventory_order.py 06942254
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import dotenv_values

ORDER_SITE_BASE = "https://order.marykayintouch.com"

def main(order_no: str) -> None:
    env = dotenv_values(Path(__file__).parent / ".env")
    username = env.get("INTOUCH_USER", "")
    password = env.get("INTOUCH_PASS", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Login
        print("Logging in...")
        login_url = f"{ORDER_SITE_BASE}/orders?lang=en_US"
        page.goto(login_url, wait_until="domcontentloaded")
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

        # Try multiple filter combos to find the order
        target_link = None
        search_urls = [
            f"{ORDER_SITE_BASE}/orders?lang=en_US&placedFor=yourself&orderDate=days90",
            f"{ORDER_SITE_BASE}/orders?lang=en_US&placedFor=yourself&orderDate=days90&orderType=2",
            f"{ORDER_SITE_BASE}/orders?lang=en_US&placedFor=yourself&orderDate=days365",
        ]
        for search_url in search_urls:
            print(f"\nSearching: {search_url}")
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            for link in page.locator("a").all():
                try:
                    text = (link.text_content() or "").strip()
                    href = link.get_attribute("href") or ""
                    if text == order_no and "orderdetails" in href:
                        target_link = href
                        print(f"Found at: {href}")
                        break
                except Exception:
                    continue

            # Show all orders found on this page
            found_orders = []
            for link in page.locator("a").all():
                try:
                    text = (link.text_content() or "").strip()
                    href = link.get_attribute("href") or ""
                    if len(text) == 8 and text.isdigit() and "orderdetails" in href:
                        found_orders.append(text)
                except Exception:
                    continue
            print(f"  Orders on page: {found_orders}")

            if target_link:
                break

        # Save order list HTML for reference
        Path("dump_order_list.html").write_text(page.content(), encoding="utf-8")
        print("Saved dump_order_list.html")

        if not target_link:
            print(f"Could not find order {order_no} on the order list page.")
            print("Saving order list HTML for inspection...")
            Path("dump_order_list.html").write_text(page.content(), encoding="utf-8")
            print("Saved dump_order_list.html")
            input("Press Enter to close...")
            browser.close()
            return

        # Navigate to order detail
        detail_url = ORDER_SITE_BASE + target_link if target_link.startswith("/") else target_link
        print(f"\nNavigating to order detail: {detail_url}")
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Save full HTML
        html_path = Path(f"dump_order_{order_no}.html")
        html_path.write_text(page.content(), encoding="utf-8")
        print(f"Saved full page HTML → {html_path}")

        # Print all div.order-product-line-item elements
        print(f"\n{'='*60}")
        print("All div.order-product-line-item elements found:")
        print(f"{'='*60}")
        items = page.locator("div.order-product-line-item").all()
        print(f"Total elements: {len(items)}\n")

        from collections import defaultdict
        sku_counts = defaultdict(int)

        for i, el in enumerate(items):
            sku = (el.get_attribute("data-sku") or "").strip()
            qty = (el.get_attribute("data-quantity") or "").strip()
            # Also grab visible text to understand context
            try:
                text = el.inner_text()[:120].replace("\n", " ").strip()
            except Exception:
                text = ""
            print(f"[{i:03d}] sku={sku}  qty={qty}  text={text!r}")
            if sku:
                sku_counts[sku] += int(qty or 0)

        print(f"\n{'='*60}")
        print(f"Unique SKUs: {len(sku_counts)}")
        dupes = {sku: qty for sku, qty in sku_counts.items() if qty != int(items[0].get_attribute("data-quantity") or 1)}

        # Check for SKUs appearing more than once in raw elements
        raw_sku_count = defaultdict(int)
        for el in items:
            sku = (el.get_attribute("data-sku") or "").strip()
            if sku:
                raw_sku_count[sku] += 1

        doubled_skus = {sku: cnt for sku, cnt in raw_sku_count.items() if cnt > 1}
        if doubled_skus:
            print(f"\n⚠ SKUs appearing more than once in the DOM ({len(doubled_skus)}):")
            for sku, cnt in list(doubled_skus.items())[:5]:
                print(f"  {sku} appears {cnt} times")
        else:
            print("\n✓ No duplicate SKUs in raw element list.")

        input("\nPress Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python dump_inventory_order.py <order_no>")
        sys.exit(1)
    main(sys.argv[1])
