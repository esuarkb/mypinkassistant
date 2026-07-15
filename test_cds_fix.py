"""Live test of the CDS no-CDS-eligible fix (2026-07-15). Read-only: opens a CDS
order for Jane Doe, adds an eligible item, tries a non-CDS item (must SKIP fast,
not hang 30s), then CANCELS — never saves. Andrea/recon account."""
import os
import sys
import time
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order, add_sku_to_bag, SkuNotCdsEligible

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

ELIGIBLE = "10179024"    # Oil-Free Eye Makeup Remover — CDS eligible (added fine for Wendy)
NON_CDS = "10041481"     # Lash Love Mascara - I ♥ Black — NOT CDS eligible

with sync_playwright() as p:
    browser = p.chromium.launch(headless="--headed" not in sys.argv)
    page = browser.new_page()
    try:
        login_intouch(page, USERNAME, PASSWORD)
        open_customer_and_start_order(page, "Jane", "Doe", fulfillment_method="cds")

        print("\n===== TEST =====")
        t = time.time()
        try:
            add_sku_to_bag(page, ELIGIBLE, fulfillment_method="cds")
            print(f"{ELIGIBLE} (eligible):  ADDED in {time.time()-t:.1f}s   ✓ expected add")
        except SkuNotCdsEligible as e:
            print(f"{ELIGIBLE} (eligible):  ✗ FALSE SKIP — {e}")

        t = time.time()
        try:
            add_sku_to_bag(page, NON_CDS, fulfillment_method="cds")
            print(f"{NON_CDS} (non-CDS):   ✗ WRONGLY ADDED (should skip)")
        except SkuNotCdsEligible as e:
            print(f"{NON_CDS} (non-CDS):   SKIPPED in {time.time()-t:.1f}s   ✓ — {e}")

        # NEVER save — cancel the draft
        try:
            page.get_by_role("button", name="Cancel").first.click()
            page.wait_for_timeout(1000)
            print("draft cancelled (not saved) ✓")
        except Exception as e:
            print(f"cancel note: {e}")
    finally:
        browser.close()
