"""
Intercepts the customer-list page API calls to find the endpoint that returns
full customer data (with Salesforce IDs, tags, etc).

Usage:
    python dump_customer_api.py <intouch_username> <intouch_password>
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

CUSTOMER_LIST_URL = "https://apps.marykayintouch.com/customer-list"
_APEX = "/webruntime/api/apex/execute"


def main(username: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        captured = []

        def on_response(response):
            url = response.url
            if _APEX not in url:
                return
            short = url[url.find(_APEX):][:150]
            try:
                body = response.json()
                rv = body.get("returnValue")
                count = len(rv) if isinstance(rv, list) else "not a list"
                first_keys = list(rv[0].keys())[:6] if isinstance(rv, list) and rv else []
                print(f"\n  [RESPONSE] count={count}")
                print(f"    URL: {short}")
                print(f"    keys: {first_keys}")
                captured.append({"url": url, "body": body, "count": count})
            except Exception as e:
                print(f"  [RESPONSE] {short} — parse error: {e}")

        page.on("response", on_response)

        print("Logging in...")
        from playwright_automation.login import login_intouch
        login_intouch(page, username, password)
        print("Logged in. Waiting 20s for customer-list API calls...")

        page.goto(CUSTOMER_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(20000)

        print(f"\n\nCaptured {len(captured)} apex responses total.")

        # Save any response that looks like customer data
        for i, c in enumerate(captured):
            rv = c["body"].get("returnValue")
            if not isinstance(rv, list) or not rv:
                continue
            keys = set(rv[0].keys())
            if any(k in keys for k in ("firstName", "tags", "ibcAccountId", "personEmail")):
                out = Path(f"dump_customer_api_{i:02d}.json")
                out.write_text(json.dumps(c["body"], indent=2))
                print(f"\nSaved customer data → {out}")
                print(f"  URL: {c['url']}")
                print(f"  Records: {c['count']}")
                print(f"  Sample keys: {list(rv[0].keys())}")

        input("\nPress Enter to close...")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python dump_customer_api.py <username> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
