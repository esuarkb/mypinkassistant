"""
Intercepts all apex API calls made when loading a customer detail page.
Goal: find out if notes (and any other fields missing from the list API)
come through a separate per-customer API call.

Usage:
    python dump_customer_detail_api.py <intouch_username> <intouch_password>

The script logs in, opens the customer list, clicks the first customer,
then waits for all API calls to settle and prints every apex response it sees.
It saves any JSON that looks note-related to dump_customer_detail_api_*.json.
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
            short = url[url.find(_APEX):][:200]
            try:
                body = response.json()
                rv = body.get("returnValue")
                if isinstance(rv, list):
                    count = len(rv)
                    first_keys = list(rv[0].keys()) if rv else []
                    print(f"\n  [LIST] count={count} keys={first_keys[:8]}")
                elif isinstance(rv, dict):
                    print(f"\n  [DICT] keys={list(rv.keys())[:12]}")
                else:
                    print(f"\n  [OTHER] type={type(rv).__name__} val={str(rv)[:80]}")
                print(f"    URL: {short}")
                captured.append({"url": url, "body": body})
            except Exception as e:
                print(f"  [PARSE ERROR] {short}: {e}")

        page.on("response", on_response)

        # --- Login ---
        print("Logging in...")
        from playwright_automation.login import login_intouch
        login_intouch(page, username, password)

        # --- Load customer list ---
        print("\nLoading customer list...")
        page.goto(CUSTOMER_LIST_URL, wait_until="domcontentloaded")
        try:
            page.get_by_role("button", name="New Customer").wait_for(timeout=30000)
            print("Customer list ready.")
        except PlaywrightTimeoutError:
            print("WARNING: page may not be fully loaded.")

        page.wait_for_timeout(3000)

        # --- Search for Carol Krause (has a test note) and click her name ---
        SEARCH_NAME = "Carol Krause"
        print(f"\nSearching for '{SEARCH_NAME}'...")
        try:
            search = page.get_by_role("searchbox").first
            if not search.count():
                search = page.locator("input[type='search'], input[placeholder*='Search'], input[placeholder*='search']").first
            search.fill(SEARCH_NAME)
            page.wait_for_timeout(3000)
            print(f"  Typed '{SEARCH_NAME}' in search box.")
        except Exception as e:
            print(f"  Could not find search box: {e}")

        # Dump search results HTML to inspect selectors
        Path("dump_search_results.html").write_text(page.content(), encoding="utf-8")
        print("  Saved dump_search_results.html for selector inspection.")

        # Click the customer NAME — avoid action buttons like "New Order"
        # The name is typically a <p> or <span> with the customer's name text inside a clickable container
        clicked = False
        for selector in [
            "c-cmt-my-customer-list-container .customer-name",
            "c-cmt-my-customer-list-container p.name",
            "c-cmt-my-customer-list-container .name",
            "c-cmt-my-customer-list-container [class*='name']",
        ]:
            try:
                el = page.locator(selector).first
                if el.count() and el.is_visible():
                    el.click()
                    clicked = True
                    print(f"  Clicked name using: {selector}")
                    break
            except Exception:
                pass

        if not clicked:
            # Try clicking "Carol" text that is NOT inside a button labeled "New Order"
            try:
                # get all elements containing "Carol" and pick the one that's not a New Order button
                els = page.get_by_text("Carol", exact=False).all()
                for el in els:
                    try:
                        tag = el.evaluate("el => el.tagName.toLowerCase()")
                        txt = el.inner_text().strip()
                        print(f"    candidate: <{tag}> text={txt!r}")
                        if tag not in ("button", "input") and "order" not in txt.lower():
                            el.click()
                            clicked = True
                            print(f"  Clicked <{tag}> with text {txt!r}")
                            break
                    except Exception:
                        pass
            except Exception as e:
                print(f"  Text search failed: {e}")

        page.wait_for_timeout(3000)

        # Click the Notes tab on the customer detail panel
        print("  Looking for Notes tab...")
        try:
            notes_tab = page.get_by_role("tab", name="Notes")
            if not notes_tab.count():
                notes_tab = page.get_by_text("Notes", exact=True).first
            notes_tab.click()
            print("  Clicked Notes tab.")
        except Exception as e:
            print(f"  Could not click Notes tab: {e}")

        # Wait for notes API calls to settle
        print("Waiting for Notes API calls to settle (8s)...")
        page.wait_for_timeout(8000)

        # Save page HTML for reference
        Path("dump_customer_detail_page.html").write_text(page.content(), encoding="utf-8")
        print("Saved dump_customer_detail_page.html")

        # --- Report findings ---
        print(f"\n\n{'='*60}")
        print(f"Total apex responses captured: {len(captured)}")
        print(f"{'='*60}")

        note_related = []
        for i, c in enumerate(captured):
            rv = c["body"].get("returnValue")
            body_str = json.dumps(c["body"]).lower()

            is_note_related = any(kw in body_str for kw in ["note", "notetitle", "notebody", "002r3"])

            print(f"\n--- Response {i} ---")
            print(f"URL: {c['url'][c['url'].find(_APEX):][:150]}")
            if isinstance(rv, list) and rv:
                print(f"Type: list ({len(rv)} items)")
                print(f"Keys: {list(rv[0].keys())}")
                if is_note_related:
                    print("*** NOTE-RELATED ***")
                    print(json.dumps(rv[:2], indent=2)[:1000])
            elif isinstance(rv, dict):
                print(f"Type: dict")
                print(f"Keys: {list(rv.keys())}")
                if is_note_related:
                    print("*** NOTE-RELATED ***")
                    print(json.dumps(rv, indent=2)[:1000])
            else:
                print(f"Type: {type(rv).__name__} = {str(rv)[:100]}")

            if is_note_related:
                note_related.append(c)
                out = Path(f"dump_customer_detail_api_{i:02d}.json")
                out.write_text(json.dumps(c["body"], indent=2))
                print(f"Saved → {out}")

        if not note_related:
            print("\n\nNo note-related API responses found.")
            print("Notes may only be available via HTML scraping, not via API.")
        else:
            print(f"\n\nFound {len(note_related)} note-related response(s) — see dump_customer_detail_api_*.json")

        # Save ALL responses for full inspection
        all_out = Path("dump_customer_detail_api_ALL.json")
        all_out.write_text(json.dumps([c["body"] for c in captured], indent=2))
        print(f"All responses saved → {all_out}")

        input("\nPress Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python dump_customer_detail_api.py <username> <password>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
