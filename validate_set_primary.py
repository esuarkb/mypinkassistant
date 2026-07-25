# validate_set_primary.py
# One-shot validation of the full CDS PO Box repair sequence on Jane Poboxtoo
# (Andrea's test customer), then REVERTS so the next chat E2E test starts from
# the true failing state (PO Box primary, no street card).
#
# Sequence: login -> CDS order -> add SKU -> fill_cds_address (adds 555 5th St)
# -> _click_set_primary_for("555 5th St") -> verify -> revert primary to the
# PO Box -> report delete-button names (deletion left to Brian) -> Cancel the
# draft ticket. Screenshots at every stage in data/saved_address_inspect/.
#
# Usage: python validate_set_primary.py

import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import (
    open_customer_and_start_order,
    add_sku_to_bag,
    fill_cds_address,
    _click_set_primary_for,
)

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

FIRST_NAME, LAST_NAME = "Jane", "Poboxtoo"
SKU = "10179024"
STREET, CITY, STATE, ZIP = "555 5th St", "Arab", "Alabama", "35976"

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "data", "saved_address_inspect")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def shot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{datetime.now().strftime('%H%M%S')}_{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  [screenshot] {path}")

def sap_count(page):
    return page.get_by_role("button", name="Set As Primary").count()

def visible_buttons(page):
    out = []
    for b in page.get_by_role("button").all():
        try:
            if b.is_visible() and b.inner_text().strip():
                out.append(b.inner_text().strip())
        except Exception:
            pass
    return out

checks = []
def check(label, ok):
    checks.append((label, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)

    print("Opening Jane Poboxtoo, CDS order, adding SKU...")
    open_customer_and_start_order(page, FIRST_NAME, LAST_NAME, fulfillment_method="cds")
    add_sku_to_bag(page, SKU, fulfillment_method="cds")
    page.wait_for_timeout(2000)

    print("\n[1] Baseline: PO Box only")
    check("no 'Set As Primary' buttons before add", sap_count(page) == 0)
    shot(page, "1_baseline")

    print("\n[2] fill_cds_address — adding the street address (the worker's exact code path)")
    fill_cds_address(page, STREET, CITY, STATE, ZIP, first_name=FIRST_NAME, last_name=LAST_NAME)
    page.wait_for_timeout(1000)
    n = sap_count(page)
    check("exactly one 'Set As Primary' button after add", n == 1)
    check(f"street card '{STREET}' visible", page.get_by_text(STREET, exact=False).count() > 0)
    shot(page, "2_after_add")

    print("\n[3] _click_set_primary_for(street) — the new step 6")
    clicked = _click_set_primary_for(page, STREET)
    check("returned True (clicked)", clicked is True)
    page.wait_for_timeout(1000)
    # after the swap the PO Box card should now expose 'Set As Primary'
    check("PO Box card now shows 'Set As Primary' (badge moved)", sap_count(page) == 1)
    shot(page, "3_street_primary")

    print("\n[4] Revert: PO Box back to Primary (also re-validates the matcher on a different card)")
    reverted = _click_set_primary_for(page, "PO Box")
    check("revert click returned True", reverted is True)
    page.wait_for_timeout(1000)
    shot(page, "4_reverted")

    print("\n[5] Buttons on page now (looking for the trash/delete name for the extra card):")
    for name in visible_buttons(page):
        print(f"    {name!r}")

    print("\n[6] Cancel the draft ticket")
    try:
        page.get_by_role("button", name="Cancel").first.click()
        page.wait_for_timeout(1000)
        # some flows confirm the cancel in a dialog
        dlg = page.get_by_role("dialog")
        if dlg.count() > 0:
            for label in ("Yes", "Yes, Cancel", "Confirm", "Continue", "OK"):
                b = dlg.get_by_role("button", name=label)
                if b.count() > 0:
                    b.first.click()
                    break
        page.wait_for_timeout(1500)
        shot(page, "5_after_cancel")
    except Exception as e:
        print(f"    cancel attempt: {e}")

    print("\n===== RESULTS =====")
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("\nNOTE: the '555 5th St' card is left on Jane's profile (delete it by hand")
    print("      if you want a fully clean slate — it is NOT primary, so the next")
    print("      E2E test will still hit the PO Box error and exercise the flow;")
    print("      fill_cds_address will just add a second copy).")
    page.wait_for_timeout(10000)
    browser.close()
