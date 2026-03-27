"""
One-shot script: logs in to InTouch, expands the full catalog, and dumps
the page HTML to catalog_dump.html so we can inspect the structure.

Usage:
    python dump_catalog_html.py <consultant_number> <intouch_password>
"""
import sys
from playwright.sync_api import sync_playwright

CATALOG_URL = "https://order.marykayintouch.com/opos?lang=en_US"
ORDER_URL   = "https://order.marykayintouch.com/orders?lang=en_US"
OUT_FILE    = "catalog_dump.html"


def main(username: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Navigate to order site — triggers login redirect
        print("Navigating to InTouch order site...")
        page.goto(ORDER_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Log in if redirected
        try:
            num_field = page.get_by_role("textbox", name="Consultant Number")
            num_field.wait_for(state="visible", timeout=5000)
            num_field.fill(username)
            page.get_by_role("textbox", name="Password").fill(password)
            page.wait_for_timeout(200)
            page.get_by_text("Log In").click()
            page.wait_for_timeout(4000)
            print("Logged in.")
        except Exception:
            print("Already authenticated or login field not found.")

        # Now navigate to catalog
        print("Loading catalog page...")
        page.goto(CATALOG_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Click Expand All
        print("Clicking Expand All...")
        try:
            page.get_by_text("Expand All").click()
            print("Waiting for catalog to expand...")
            page.wait_for_timeout(8000)
        except Exception as e:
            print(f"Could not click Expand All: {e}")

        # Dump HTML
        html = page.content()
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved {len(html):,} bytes to {OUT_FILE}")

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python dump_catalog_html.py <consultant_number> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
