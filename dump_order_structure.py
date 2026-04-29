"""
Diagnoses the duplicate div.order-product-line-item issue on an order detail page.
For each element, uses JavaScript closest() to check what containers it lives in,
so we can find a selector that targets only the real items.

Usage:
    python dump_order_structure.py <order_no>
    python dump_order_structure.py 06942254
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import dotenv_values

ORDER_SITE_BASE = "https://order.marykayintouch.com"
ORDER_TYPE_ALL = "1%2C2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C14%2C15%2C16%2C17%2C18%2C19%2C20%2C21%2C22%2C23%2C24%2C25%2C26%2C27%2C28%2C29%2C30%2C31%2C32"

def main(order_no: str) -> None:
    env = dotenv_values(Path(__file__).parent / ".env")
    username = env.get("INTOUCH_USER", "")
    password = env.get("INTOUCH_PASS", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("Logging in...")
        page.goto(f"{ORDER_SITE_BASE}/orders?lang=en_US&placedFor=yourself&orderDate=days365&orderType={ORDER_TYPE_ALL}", wait_until="domcontentloaded")
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

        # Find order link — wait for AJAX list to load first
        target_link = None
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
                    break
            except Exception:
                continue

        if not target_link:
            print(f"Order {order_no} not found on list page — check saved HTML or extend date range.")
            browser.close()
            return

        detail_url = ORDER_SITE_BASE + target_link if target_link.startswith("/") else target_link
        print(f"Navigating to: {detail_url}")
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Use JavaScript to inspect every order-product-line-item element
        results = page.evaluate("""
            () => {
                const items = Array.from(document.querySelectorAll('div.order-product-line-item'));
                return items.map((el, idx) => {
                    const sku = el.getAttribute('data-sku') || '';
                    const qty = el.getAttribute('data-quantity') || '';

                    // Walk up and collect immediate parent and grandparent classes
                    const parent = el.parentElement;
                    const grandparent = parent ? parent.parentElement : null;
                    const parentClass = parent ? (parent.className || '') : '';
                    const gpClass = grandparent ? (grandparent.className || '') : '';

                    // Check key ancestor containers using closest()
                    const inSection = !!el.closest('.section-order-product-line-items');
                    const inProductsCol = !!el.closest('.order-details-products-col');
                    const inPrintNone = !!el.closest('.d-print-none');
                    const inModal = !!el.closest('.modal');

                    // Check computed visibility
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.height > 0;

                    return {
                        idx, sku, qty,
                        parentClass,
                        gpClass,
                        inSection,
                        inProductsCol,
                        inPrintNone,
                        inModal,
                        height: Math.round(rect.height),
                        visible,
                    };
                });
            }
        """)

        print(f"\nTotal div.order-product-line-item: {len(results)}")
        print(f"\n{'idx':>4}  {'sku':<12} {'qty':>4}  {'inSec':>6}  {'inCol':>6}  {'printNone':>9}  {'inModal':>7}  {'h':>5}  {'vis':>5}  parent")
        print("-" * 110)

        from collections import Counter
        section_counts = Counter()
        for r in results:
            key = f"inSection={r['inSection']} inProductsCol={r['inProductsCol']}"
            section_counts[key] += 1
            print(f"{r['idx']:>4}  {r['sku']:<12} {r['qty']:>4}  {str(r['inSection']):>6}  {str(r['inProductsCol']):>6}  {str(r['inPrintNone']):>9}  {str(r['inModal']):>7}  {r['height']:>5}  {str(r['visible']):>5}  {r['parentClass'][:40]}")

        print(f"\nSummary:")
        for k, v in section_counts.items():
            print(f"  {k}: {v} items")

        # What selector would give us ONLY the real items?
        real = [r for r in results if not r['inSection']]
        in_sec = [r for r in results if r['inSection']]
        print(f"\nNot in section: {len(real)} items")
        print(f"In section: {len(in_sec)} items")

        input("\nPress Enter to close...")
        browser.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python dump_order_structure.py <order_no>")
        sys.exit(1)
    main(sys.argv[1])
