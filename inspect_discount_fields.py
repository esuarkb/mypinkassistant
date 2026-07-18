"""Read-only inspection: dump MK's NEW discount/shipping/other/tax fields on the
MyCustomers order entry screen (2026-07-18, discount feature build).

Per Brian: fields show on INVENTORY orders only (not CDS). Expected on the form:
  - Discount   ($ / % toggle; $ capped at subtotal, % capped at 100)
  - Shipping   (free amount)
  - Other      (ignore for V1)
  - Sales Tax  (% rate, capped 100)

This logs in as the recon account, opens an inventory order for Jane Doe, adds
the charcoal mask (10094148), then dumps every candidate input/toggle with its
attributes + surrounding markup so we can wire fill_discount_fields precisely.
NEVER saves — cancels the draft. Run headless (default) or `--headed`.
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order, add_sku_to_bag

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]
SKU = "10094148"  # Clear Proof Deep-Cleansing Charcoal Mask


def main() -> int:
    headed = "--headed" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        try:
            login_intouch(page, USERNAME, PASSWORD)
            open_customer_and_start_order(page, "Jane", "Doe", fulfillment_method="inventory")
            add_sku_to_bag(page, SKU, fulfillment_method="inventory")
            page.wait_for_timeout(2000)

            print("\n===== OLD SELECTOR CHECK =====")
            for sel in ["input[name='discount']", "input[name='shipping']"]:
                print(f"  {sel!r}: count={page.locator(sel).count()}")

            print("\n===== ALL INPUTS ON SCREEN =====")
            inputs = page.locator("input")
            for i in range(inputs.count()):
                el = inputs.nth(i)
                try:
                    attrs = el.evaluate(
                        "e => ({name: e.name, id: e.id, type: e.type, "
                        "aria: e.getAttribute('aria-label'), ph: e.placeholder, "
                        "value: e.value, cls: (e.className||'').slice(0,60), "
                        "visible: !!(e.offsetWidth || e.offsetHeight)})"
                    )
                    if attrs.get("visible"):
                        print(f"  [{i}] {attrs}")
                except Exception:
                    pass

            print("\n===== FIELD CONTAINERS (Discount / Shipping / Other / Tax) =====")
            for label in ["Discount", "Shipping", "Other", "Sales Tax", "Tax"]:
                loc = page.get_by_text(label, exact=False)
                n = loc.count()
                print(f"\n--- text {label!r}: {n} hit(s)")
                for i in range(min(n, 3)):
                    try:
                        html = loc.nth(i).evaluate(
                            "e => (e.closest('lightning-input, lightning-radio-group, "
                            "div.slds-form-element, div[class*=field], tr, li') || e.parentElement)"
                            ".outerHTML"
                        )
                        print(f"  #{i}: {html[:900]}")
                    except Exception as ex:
                        print(f"  #{i}: dump err {ex}")

            print("\n===== $/% TOGGLE CANDIDATES =====")
            for sel in ["button:has-text('$')", "button:has-text('%')",
                        "lightning-button-menu", "[role='radiogroup']",
                        "select", "lightning-combobox"]:
                try:
                    print(f"  {sel!r}: count={page.locator(sel).count()}")
                except Exception as ex:
                    print(f"  {sel!r}: ERR {ex}")

            # never save — cancel the draft
            try:
                page.get_by_role("button", name="Cancel").first.click()
                page.wait_for_timeout(1500)
                # confirm dialog if one appears
                for name in ("Yes", "Yes, Cancel", "Confirm", "Discard"):
                    btn = page.get_by_role("button", name=name)
                    if btn.count():
                        btn.first.click()
                        page.wait_for_timeout(800)
                        break
                print("\ndraft cancelled (not saved) ✓")
            except Exception as e:
                print(f"\ncancel note: {e}")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
