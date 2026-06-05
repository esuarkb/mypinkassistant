# run_order_test.py
# Full end-to-end test runner for orders.py — runs without pausing.
# Usage: python run_order_test.py

import os
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch
from playwright_automation.orders import open_customer_and_start_order, add_sku_to_bag, finalize_order

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

FIRST_NAME = "Jane"
LAST_NAME = "Doe"
SKU = "10179024"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    open_customer_and_start_order(page, FIRST_NAME, LAST_NAME)
    add_sku_to_bag(page, SKU)
    finalize_order(page)

    print("Order complete.")
    browser.close()
