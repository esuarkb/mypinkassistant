"""Live test of fill_discount_fields (2026-07-18 discount feature). Opens an
INVENTORY order for Jane Doe (recon account), adds charcoal mask ($26), fills
Discount $5.00 + Sales Tax 8.25%, reads back MK's computed numbers, and CANCELS
— never saves. Verifies: field selectors work, values stick, and MK's tax math
matches _order_money (tax base = discounted subtotal: (26−5)×8.25% = $1.73?
or pre-discount 26×8.25% = $2.15 — this test tells us which)."""
import os
import sys
import re
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order, add_sku_to_bag, fill_discount_fields

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]
SKU = "10094148"      # Clear Proof Deep-Cleansing Charcoal Mask — $26.00
DISCOUNT = 5.00
TAX_PCT = 8.25

with sync_playwright() as p:
    browser = p.chromium.launch(headless="--headed" not in sys.argv)
    page = browser.new_page()
    try:
        login_intouch(page, USERNAME, PASSWORD)
        open_customer_and_start_order(page, "Jane", "Doe", fulfillment_method="inventory")
        add_sku_to_bag(page, SKU, fulfillment_method="inventory")
        page.wait_for_timeout(1500)

        print("\n===== FILL =====")
        failures = fill_discount_fields(page, discount_amount=DISCOUNT, tax_percent=TAX_PCT)
        print(f"fill failures: {failures or 'none ✓'}")
        page.wait_for_timeout(1500)

        print("\n===== READ BACK =====")
        for name in ("discount", "taxPercent"):
            try:
                v = page.locator(f"input[name='{name}']").first.input_value()
                print(f"  input[name='{name}'] value: {v!r}")
            except Exception as e:
                print(f"  input[name='{name}'] read err: {e}")

        # MK's computed tax display sits next to the taxPercent input
        try:
            tax_disp = page.locator(".tax-amount-display").first.inner_text()
            print(f"  MK computed tax display: {tax_disp!r}")
        except Exception as e:
            print(f"  tax display err: {e}")

        # dump every $ figure in the totals panel for the math comparison
        try:
            panel = page.locator(".discount-container").first.locator("xpath=ancestor::div[3]")
            txt = panel.inner_text()
        except Exception:
            txt = page.locator("body").inner_text()
        dollars = re.findall(r"(?:Subtotal|Total|Tax|Discount)[^$%\n]*[$]?\s*-?\d[\d,]*\.?\d*|\$\s*-?\d[\d,]*\.\d{2}", txt)
        print("  money lines on screen:")
        for d in dollars[:15]:
            print(f"    {d.strip()}")

        print(f"\n  OUR math: subtotal $26.00 − ${DISCOUNT:.2f} = $21.00; "
              f"tax(discounted base) = ${21*TAX_PCT/100:.2f}; tax(pre-discount base) = ${26*TAX_PCT/100:.2f}")

        # NEVER save — cancel the draft
        page.get_by_role("button", name="Cancel").first.click()
        page.wait_for_timeout(1500)
        for name in ("Yes", "Yes, Cancel", "Confirm", "Discard"):
            btn = page.get_by_role("button", name=name)
            if btn.count():
                btn.first.click()
                page.wait_for_timeout(800)
                break
        print("\ndraft cancelled (not saved) ✓")
    finally:
        browser.close()
