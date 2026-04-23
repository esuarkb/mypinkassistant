"""
Dumps the InTouch order-list page and intercepts all network requests
so we can find the API endpoint behind the pagination.

Usage:
    python dump_order_history.py <intouch_username> <intouch_password>
"""
import json
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ORDER_LIST_URL = "https://apps.marykayintouch.com/order-list"

EXPORT_KEYWORDS = [
    "export", "download", "csv", "excel", "pageSize", "pagesize",
    "page_size", "limit", "offset", "totalCount", "total_count",
    "getAllOrders", "orderHistory", "order-history", "salesticket",
    "graphql", "/api/", "api/orders", "api/order",
]


def dump(page, name: str) -> Path:
    path = Path(f"dump_history_{name}.html")
    path.write_text(page.content(), encoding="utf-8")
    print(f"  Saved {path} ({path.stat().st_size:,} bytes)")
    return path


def scan_html(path: Path) -> None:
    html = path.read_text(encoding="utf-8").lower()
    hits = {}
    for kw in EXPORT_KEYWORDS:
        idx = html.find(kw.lower())
        if idx >= 0:
            snippet = path.read_text(encoding="utf-8")[max(0, idx-60):idx+100].replace("\n", " ").strip()
            hits[kw] = snippet
    if hits:
        for kw, snippet in hits.items():
            print(f"  [{kw}] ...{snippet}...")
    else:
        print("  (no export/pagination keywords found in HTML)")


def main(username: str, password: str) -> None:
    captured_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page    = context.new_page()

        # Intercept ALL network requests so we can see the API calls
        def on_request(request):
            url = request.url
            # Filter to anything that looks like data (not images/fonts/css)
            if any(x in url for x in [
                "api", "graphql", "order", "sales", "query", "data",
                ".json", "fetch", "lightning", "aura", "apex"
            ]):
                captured_requests.append({
                    "method": request.method,
                    "url": url,
                    "post_data": request.post_data,
                })

        def on_response(response):
            url = response.url
            if any(x in url for x in [
                "api", "graphql", "order", "sales", "query", "data",
                ".json", "fetch", "lightning", "aura", "apex"
            ]):
                try:
                    body = response.body()
                    # Only log if it looks like JSON and mentions orders
                    text = body.decode("utf-8", errors="ignore")
                    if any(k in text.lower() for k in ["order", "sales", "ticket", "sku", "partnum"]):
                        out = Path(f"dump_history_response_{len(captured_requests):03d}.json")
                        out.write_bytes(body)
                        print(f"  [RESPONSE] {response.status} {url[:120]}")
                        print(f"    → Saved {out} ({len(body):,} bytes)")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        # Login
        print("Logging in...")
        from playwright_automation.login import login_intouch
        login_intouch(page, username, password)
        print("  Logged in.")

        # Navigate directly to order list
        print(f"\nNavigating to {ORDER_LIST_URL}...")
        page.goto(ORDER_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        print("\nStep 1: Order list page (initial load)")
        p1 = dump(page, "1_order_list")
        print("  Scanning HTML...")
        scan_html(p1)

        # Scroll to load any lazy sections
        print("\nStep 2: Scrolling to load all visible orders...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        p2 = dump(page, "2_order_list_scrolled")

        # Look for pagination — "Next", ">" button or page numbers
        print("\nStep 3: Looking for pagination controls...")
        for label in ["Next", "next", ">", "›", "Load More", "Show More"]:
            try:
                btn = page.get_by_role("button", name=label).first
                btn.wait_for(state="visible", timeout=2000)
                print(f"  Found pagination button: {label!r} — clicking...")
                btn.click()
                page.wait_for_timeout(2000)
                dump(page, "3_page_2")
                break
            except PlaywrightTimeoutError:
                pass
        else:
            # Try locator-based next page
            try:
                page.locator("button[title='Next Page'], [aria-label='Next Page'], .next-page").first.click()
                page.wait_for_timeout(2000)
                dump(page, "3_page_2_aria")
                print("  Clicked next-page via aria/title selector.")
            except Exception:
                print("  No pagination button found — dumping page as-is.")
                dump(page, "3_no_pagination")

        # Look for any export / download button anywhere on the page
        print("\nStep 4: Looking for export/download controls...")
        for label in ["Export", "Download", "CSV", "Print", "Export All", "Download All"]:
            try:
                el = page.get_by_role("button", name=label).first
                el.wait_for(state="visible", timeout=1500)
                print(f"  ✅ Found button: {label!r} at {el.evaluate('e => e.outerHTML')[:200]}")
            except PlaywrightTimeoutError:
                pass

        # Print all captured API requests
        print(f"\n\n=== CAPTURED NETWORK REQUESTS ({len(captured_requests)}) ===")
        seen_urls = set()
        for r in captured_requests:
            url = r["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            print(f"\n  [{r['method']}] {url[:150]}")
            if r["post_data"]:
                pd = r["post_data"][:400] if r["post_data"] else ""
                print(f"    POST: {pd}")

        print(f"\n\nAll done. Check dump_history_*.html and dump_history_response_*.json")
        input("Press Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python dump_order_history.py <username> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
