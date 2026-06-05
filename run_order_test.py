# run_order_test.py
# Diagnostic end-to-end order test. Takes a screenshot and records all visible
# button names at each step. On first run, saves a baseline. Every run after
# compares against it and flags any changes.
# Usage: python run_order_test.py

import os, json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order, add_sku_to_bag

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

FIRST_NAME = "Jane"
LAST_NAME = "Doe"
SKU = "10179024"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "order_test_screenshots")
BASELINE_FILE = os.path.join(DATA_DIR, "order_test_baseline.json")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

results = {}

def snap(page, step_key, label):
    ts = datetime.now().strftime("%H%M%S")
    path = os.path.join(SCREENSHOT_DIR, f"{ts}_{step_key}.png")
    page.screenshot(path=path)
    buttons = sorted(set(
        b.inner_text().strip()
        for b in page.get_by_role("button").all()
        if b.is_visible() and b.inner_text().strip()
    ))
    results[step_key] = {"label": label, "buttons": buttons}
    print(f"\n[{label}]")
    print(f"  Buttons: {buttons}")
    return buttons

def compare_to_baseline(current, baseline):
    all_steps = sorted(set(list(current.keys()) + list(baseline.keys())))
    issues = []
    for step in all_steps:
        if step not in baseline:
            issues.append(f"  NEW STEP '{step}' (not in baseline)")
            continue
        if step not in current:
            issues.append(f"  MISSING STEP '{step}' (was in baseline)")
            continue
        cur_btns = set(current[step]["buttons"])
        base_btns = set(baseline[step]["buttons"])
        added = cur_btns - base_btns
        removed = base_btns - cur_btns
        if added:
            issues.append(f"  [{step}] NEW buttons: {sorted(added)}")
        if removed:
            issues.append(f"  [{step}] MISSING buttons (possibly renamed): {sorted(removed)}")
    return issues

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)
    snap(page, "01_logged_in", "After login")

    print("Opening customer and starting order...")
    open_customer_and_start_order(page, FIRST_NAME, LAST_NAME)
    snap(page, "02_order_page_loaded", "Order page loaded")

    print("Adding SKU to bag...")
    add_sku_to_bag(page, SKU)
    snap(page, "03_sku_added", "SKU added to bag")

    print("Clicking Save and Review...")
    page.get_by_role("button", name="Save and Review").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Save and Review").click()
    page.wait_for_timeout(2000)
    snap(page, "04_after_save_and_review", "After Save and Review")

    print("Clicking Change To Processed...")
    page.get_by_role("button", name="Change To Processed").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Change To Processed").click()
    page.wait_for_timeout(1000)
    snap(page, "05_confirm_popup", "Confirm popup")

    print("Clicking Yes, Confirm...")
    page.get_by_role("button", name="Yes, Confirm").wait_for(state="visible", timeout=15000)
    page.get_by_role("button", name="Yes, Confirm").click()
    page.wait_for_timeout(2000)
    snap(page, "06_order_complete", "Order complete")

    browser.close()

# Save or compare baseline
if not os.path.exists(BASELINE_FILE):
    with open(BASELINE_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nBaseline saved to {BASELINE_FILE}")
    print("Run again to start detecting changes.")
else:
    with open(BASELINE_FILE) as f:
        baseline = json.load(f)
    issues = compare_to_baseline(results, baseline)
    if issues:
        print("\n*** CHANGES DETECTED vs BASELINE ***")
        for issue in issues:
            print(issue)
        print("\nIf changes are intentional, delete the baseline file to reset it:")
        print(f"  rm {BASELINE_FILE}")
    else:
        print("\nAll buttons match baseline. No changes detected.")
