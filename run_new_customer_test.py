# run_new_customer_test.py
# Diagnostic end-to-end new customer test. Takes a screenshot and records all
# visible button names at each step. On first run, saves a baseline. Every run
# after compares against it and flags any changes.
# Usage: python run_new_customer_test.py

import os, json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_automation.login import login_intouch
from playwright_automation.new_customer import ensure_mycustomers_ready, has_address, add_address_on_detail_page

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

CUSTOMER = {
    "First Name": "Testy",
    "Last Name": "Jones",
    "Phone": "5551231234",
    "Email": "test@gmail.com",
    "Birthday": "2002-12-10",
    "Street": "555 5th St",
    "City": "Arab",
    "State": "Alabama",
    "Postal Code": "35976",
}

MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "new_customer_test_screenshots")
BASELINE_FILE = os.path.join(DATA_DIR, "new_customer_test_baseline.json")
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
    page.goto(MYCUSTOMERS_URL)
    ensure_mycustomers_ready(page)
    snap(page, "01_customer_list", "Customer list ready")

    # Open new customer form
    print("Opening new customer form...")
    page.get_by_role("button", name="New Customer").click()
    page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(2000)
    snap(page, "02_new_customer_form", "New customer form open")

    # Fill basic info
    print("Filling basic info...")
    page.get_by_role("textbox", name="First Name").fill(CUSTOMER["First Name"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Last Name").fill(CUSTOMER["Last Name"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Email Address (Optional)").fill(CUSTOMER["Email"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(CUSTOMER["Phone"])
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Birthday (Optional)").fill(CUSTOMER["Birthday"])
    page.wait_for_timeout(100)
    snap(page, "03_form_filled", "Form filled before save")

    # Save
    print("Saving new customer...")
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(1000)
    snap(page, "04_after_save", "After Save New Customer")

    # Address
    print("Opening address dialog...")
    add_address_btn = page.locator("c-cmt-no-info-available").get_by_role("button", name="Add New Address")
    first_name_field = page.locator('[id^="AddressFirstName-"]')
    for _ in range(4):
        add_address_btn.click()
        page.wait_for_timeout(500)
        try:
            first_name_field.wait_for(state="visible", timeout=800)
            break
        except PlaywrightTimeoutError:
            pass
    snap(page, "05_address_dialog_open", "Address dialog open")

    # Fill address
    print("Filling address...")
    first_name_field.fill(CUSTOMER["First Name"])
    page.wait_for_timeout(100)
    page.locator('[id^="AddressLastName-"]').fill(CUSTOMER["Last Name"])
    page.wait_for_timeout(100)
    page.locator('[id^="Street-"]').fill(CUSTOMER["Street"])
    page.wait_for_timeout(100)
    page.locator('[id^="City-"]').fill(CUSTOMER["City"])
    page.wait_for_timeout(100)
    page.locator('[id^="PostalCode-"]').fill(CUSTOMER["Postal Code"])
    page.wait_for_timeout(100)
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Select an option").click()
    page.wait_for_timeout(700)
    dialog.get_by_role("option", name=CUSTOMER["State"]).click()
    page.wait_for_timeout(700)
    snap(page, "06_address_filled", "Address filled before save")

    print("Saving address...")
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    try:
        first_name_field.wait_for(state="hidden", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1000)
    snap(page, "07_after_address_saved", "After address saved")

    # Subscriptions
    print("Opening subscriptions dialog...")
    subscriptions = page.locator("c-cmt-my-customer-details-subscriptions")
    subscriptions.wait_for(state="visible", timeout=20000)
    sub_btn = subscriptions.get_by_role("button")
    dialog_toggle = page.locator("c-cmt-custom-toggle").nth(0).locator("label")
    for attempt in range(3):
        if not dialog_toggle.is_visible():
            sub_btn.click()
            page.wait_for_timeout(500)
        try:
            dialog_toggle.wait_for(state="visible", timeout=4000)
            break
        except PlaywrightTimeoutError:
            pass
    snap(page, "08_subscriptions_dialog", "Subscriptions dialog open")

    # Toggle subscriptions on
    print("Enabling subscriptions...")
    sub_dialog = page.get_by_role("dialog")
    for nth in (0, 1):
        label = sub_dialog.locator("c-cmt-custom-toggle").nth(nth).locator("label")
        toggle_input = sub_dialog.locator("c-cmt-custom-toggle").nth(nth).locator("input.toggle-input")
        for _ in range(3):
            label.click()
            page.wait_for_timeout(500)
            if toggle_input.is_checked():
                break
        page.wait_for_timeout(300)
    snap(page, "09_subscriptions_toggled", "Subscriptions toggled on")

    print("Saving subscriptions...")
    sub_dialog.get_by_role("button", name="Save & Exit").click()
    sub_dialog.wait_for(state="hidden", timeout=8000)
    page.wait_for_timeout(1000)
    snap(page, "10_complete", "Customer creation complete")

    ensure_mycustomers_ready(page, timeout_ms=30000)
    print("\nCustomer created successfully.")
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
        print("\nTo reset baseline after an intentional fix:")
        print(f"  rm \"{BASELINE_FILE}\"")
    else:
        print("\nAll buttons match baseline. No changes detected.")
