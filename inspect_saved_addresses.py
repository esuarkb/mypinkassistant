# inspect_saved_addresses.py
# Read-only inspection of the Saved Addresses section on a CDS sales ticket,
# to validate _click_set_primary_for()'s geometric matching against the real
# LWC DOM (built for the PO Box fix, 2026-07-25).
#
# Logs in with INTOUCH_USER/INTOUCH_PASS from .env (Andrea's test account),
# opens the customer, starts a CDS order, adds a SKU, then prints:
#   - every visible button + all 'Set As Primary' buttons with bounding boxes
#   - every street-text match with bounding boxes
#   - a DRY RUN of the matcher: which button it WOULD click and why
# Nothing is clicked unless you pass --click (then it clicks Set As Primary
# for STREET and screenshots the result; the order is never saved either way).
#
# Usage: python inspect_saved_addresses.py [--click]

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import (
    open_customer_and_start_order,
    add_sku_to_bag,
    _click_set_primary_for,
)

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

FIRST_NAME = "Jane"
LAST_NAME = "Poboxtoo"
SKU = "10179024"          # swap if not CDS-eligible right now
STREET = "555 5th St"     # the physical address we expect on a card

DO_CLICK = "--click" in sys.argv

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "data", "saved_address_inspect")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def shot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{datetime.now().strftime('%H%M%S')}_{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  [screenshot] {path}")


def boxes_report(page):
    print("\n--- Visible buttons on page ---")
    for b in page.get_by_role("button").all():
        try:
            if b.is_visible() and b.inner_text().strip():
                print(f"  {b.inner_text().strip()!r}")
        except Exception:
            pass

    btns = page.get_by_role("button", name="Set As Primary")
    n = btns.count()
    print(f"\n--- 'Set As Primary' buttons: {n} ---")
    btn_boxes = []
    for i in range(n):
        bb = btns.nth(i).bounding_box()
        btn_boxes.append(bb)
        print(f"  [{i}] box={bb}")

    texts = page.get_by_text(STREET, exact=False)
    tn = texts.count()
    print(f"\n--- Text matches for {STREET!r}: {tn} ---")
    text_boxes = []
    for i in range(tn):
        tb = texts.nth(i).bounding_box()
        text_boxes.append(tb)
        try:
            snippet = texts.nth(i).inner_text().strip()[:80]
        except Exception:
            snippet = "<no text>"
        print(f"  [{i}] box={tb} text={snippet!r}")

    # PO Box card too, for the full picture
    po = page.get_by_text("PO Box", exact=False)
    print(f"\n--- Text matches for 'PO Box': {po.count()} ---")
    for i in range(po.count()):
        print(f"  [{i}] box={po.nth(i).bounding_box()}")

    # DRY RUN of _click_set_primary_for's scoring
    print("\n--- Matcher dry run ---")
    best_i, best_d = None, None
    for i, bb in enumerate(btn_boxes):
        if not bb:
            continue
        for tb in text_boxes:
            if not tb:
                continue
            d = (abs((bb["y"] + bb["height"] / 2) - (tb["y"] + tb["height"] / 2))
                 + abs((bb["x"] + bb["width"] / 2) - (tb["x"] + tb["width"] / 2)))
            print(f"  button[{i}] <-> street text: distance={d:.0f}")
            if best_d is None or d < best_d:
                best_i, best_d = i, d
    if best_i is None and n == 1:
        print("  (no street boxes — would fall back to the single button)")
        best_i = 0
    print(f"  => matcher would click button index: {best_i}")
    return best_i


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)

    print(f"Opening {FIRST_NAME} {LAST_NAME} and starting CDS order...")
    open_customer_and_start_order(page, FIRST_NAME, LAST_NAME, fulfillment_method="cds")

    print(f"Adding SKU {SKU}...")
    add_sku_to_bag(page, SKU, fulfillment_method="cds")
    page.wait_for_timeout(2000)

    # Bring the Saved Addresses section into view for the screenshot
    try:
        page.get_by_text("Saved Addresses", exact=False).first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception:
        print("  (couldn't scroll to 'Saved Addresses' — section may not be rendered)")

    shot(page, "1_sales_ticket")
    best_i = boxes_report(page)

    if DO_CLICK:
        print(f"\n--click set: running _click_set_primary_for(page, {STREET!r})...")
        clicked = _click_set_primary_for(page, STREET)
        print(f"  clicked: {clicked}")
        page.wait_for_timeout(1500)
        shot(page, "2_after_set_primary")
        boxes_report(page)

    print("\nDone — order NOT saved. Close the browser window when finished looking.")
    page.wait_for_timeout(15000)
    browser.close()
