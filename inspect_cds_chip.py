"""Read-only inspection: dump the 'no-CDS' chip HTML for a non-CDS-eligible SKU.

Why: the worker's step-10 guard detects the chip via `img[src*="noCdsChip"]`,
but MK now renders it as a styled "⊘ CDS" pill (weed/incident 2026-07-15,
Wendy's Trina Sheppard order failed on Lash Love Mascara - I ♥ Black 10041481).
This logs into InTouch, opens a CDS order, searches the SKU, and prints the
actual chip markup + candidate selectors so we can fix the guard precisely.

NEVER adds/saves — opens the order draft and cancels. Run headless (default)
or `--headed` to watch. Uses INTOUCH_USER/INTOUCH_PASS (recon account).
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]
TEST_CUSTOMER = ("Jane", "Doe")   # existing test customer in the recon account
SKU = os.environ.get("INSPECT_SKU", "10041481")


def main() -> int:
    headed = "--headed" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        try:
            login_intouch(page, USERNAME, PASSWORD)
            # CDS order — the context where the no-CDS chip disables Add to Bag
            open_customer_and_start_order(page, TEST_CUSTOMER[0], TEST_CUSTOMER[1],
                                          fulfillment_method="cds")

            # search the non-CDS SKU (retry once — InTouch search is flaky first try)
            found = False
            for attempt in (1, 2):
                try:
                    box = page.get_by_role("searchbox", name="Note Title")
                    box.fill(""); page.wait_for_timeout(300); box.fill(SKU)
                    page.locator(f"text={SKU}").first.wait_for(timeout=12000)
                    found = True
                    break
                except PlaywrightTimeoutError:
                    print(f"!! SKU {SKU} no result (attempt {attempt})")
            if not found:
                print("ABORT: SKU never appeared in search")
                browser.close()
                return 1
            page.wait_for_timeout(1200)

            print("\n===== DIAGNOSIS =====")
            # 1) old (broken) selector
            old = page.locator('img[src*="noCdsChip"]')
            print(f"OLD selector img[src*=\"noCdsChip\"] count: {old.count()}  (expect 0 = broken)")

            # 2) Add to Bag button state
            btn = page.get_by_role("button", name="Add to Bag")
            if btn.count():
                try:
                    print(f"Add to Bag disabled: {btn.first.is_disabled()}")
                except Exception as e:
                    print(f"Add to Bag state err: {e}")
            else:
                print("Add to Bag: not found")

            # 3) the chip itself — dump every element whose text is exactly 'CDS'
            cds = page.get_by_text("CDS", exact=True)
            print(f"\nElements with exact text 'CDS': {cds.count()}")
            for i in range(min(cds.count(), 4)):
                el = cds.nth(i)
                try:
                    own = el.evaluate("e => e.outerHTML")
                    par = el.evaluate("e => e.parentElement ? e.parentElement.outerHTML : ''")
                    print(f"\n--- CDS element #{i} outerHTML:\n{own[:600]}")
                    print(f"--- its parent outerHTML:\n{par[:800]}")
                except Exception as e:
                    print(f"  (dump err #{i}: {e})")

            # 4) candidate selectors to test
            print("\n===== CANDIDATE SELECTOR COUNTS =====")
            for sel in [
                'img[src*="noCdsChip"]',          # old
                'img[src*="Cds" i]',
                'img[alt*="CDS" i]',
                '[class*="cds" i]',
                'text=/^\\s*CDS\\s*$/',
                'span:has-text("CDS")',
            ]:
                try:
                    print(f"  {sel!r}: {page.locator(sel).count()}")
                except Exception as e:
                    print(f"  {sel!r}: ERR {e}")

            # cancel the draft — never save
            try:
                page.get_by_role("button", name="Cancel").first.click()
                page.wait_for_timeout(1000)
            except Exception:
                pass
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
