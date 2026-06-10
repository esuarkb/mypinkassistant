"""
Timing test: fetches full order detail (with quantities) for all of Andrea's orders
using direct HTTP calls after a single Playwright login.

Usage:
    python run_order_detail_sync_test.py
"""
import json, os, time, requests
from dotenv import load_dotenv
load_dotenv()
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

ORDER_LIST_URL  = "https://apps.marykayintouch.com/order-list"
APEX_URL        = "https://apps.marykayintouch.com/webruntime/api/apex/execute?language=en-US&asGuest=false&htmlEncode=false"
APEX_CLASSNAME  = "@udd/01pR30000011tgy"

captured_orders = {}
csrf_token = None

def on_response(response):
    global csrf_token
    if "/webruntime/api/apex/execute" not in response.url:
        return
    # Grab CSRF token from request headers
    if not csrf_token:
        try:
            csrf_token = response.request.headers.get("csrf-token")
        except Exception:
            pass
    try:
        body = response.json()
        rv = body.get("returnValue")
        if not rv or not isinstance(rv, list):
            return
        if "OrderItemSummaries" not in (rv[0] if rv else {}):
            return
        for o in rv:
            oid = o.get("Id") or str(id(o))
            captured_orders[oid] = o
        print(f"[OrderList] Captured {len(rv)} orders")
    except Exception:
        pass

print("Starting Playwright session...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    page.on("response", on_response)
    page.goto(ORDER_LIST_URL, wait_until="domcontentloaded")
    for _ in range(30):
        if captured_orders:
            break
        page.wait_for_timeout(500)
    if not captured_orders:
        page.reload(wait_until="domcontentloaded")
        for _ in range(30):
            if captured_orders:
                break
            page.wait_for_timeout(500)
    page.remove_listener("response", on_response)

    if not captured_orders:
        print("No orders captured. Exiting.")
        browser.close()
        exit()

    print(f"\nCaptured {len(captured_orders)} orders. CSRF token: {'found' if csrf_token else 'NOT FOUND'}")
    print(f"Starting detail fetch using Playwright context.request...\n")

    order_ids = list(captured_orders.keys())
    total = len(order_ids)
    success = 0
    failed = 0
    with_quantities = 0
    sample_results = []

    start = time.time()

    for i, order_id in enumerate(order_ids):
        payload = {
            "namespace": "",
            "classname": APEX_CLASSNAME,
            "method": "getOrderSummaryRecordByIds",
            "isContinuation": False,
            "params": {
                "orderSummaryId": order_id,
                "webStoreId": "",
                "isB2CFlow": True
            },
            "cacheable": False
        }
        try:
            r = page.context.request.post(
                APEX_URL,
                data=json.dumps(payload),
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "csrf-token": csrf_token or "",
                    "referer": "https://apps.marykayintouch.com/order-list",
                }
            )
            if r.ok:
                rv = r.json().get("returnValue", {})
                if isinstance(rv, dict) and "productDetails" in rv:
                    success += 1
                    details = rv["productDetails"]
                    has_qty = any(int(d.get("productQuantity", 1)) > 1 for d in details)
                    if has_qty:
                        with_quantities += 1
                    if len(sample_results) < 3:
                        sample_results.append({
                            "order_id": order_id,
                            "customer": f"{rv.get('firstName')} {rv.get('lastName')}",
                            "items": [
                                f"{d['productName']} x{d['productQuantity']}"
                                for d in details
                            ]
                        })
                else:
                    failed += 1
            else:
                failed += 1
                if i < 3:
                    print(f"  HTTP {r.status} on order {i+1}/{total}")
        except Exception as e:
            failed += 1
            if i < 3:
                print(f"  Error on order {i+1}/{total}: {e}")

        if (i + 1) % 25 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            remaining = (total - i - 1) / rate
            print(f"  {i+1}/{total} done — {elapsed:.1f}s elapsed, ~{remaining:.0f}s remaining")

    elapsed = time.time() - start
    print(f"\n--- Results ---")
    print(f"Total orders:      {total}")
    print(f"Success:           {success}")
    print(f"Failed:            {failed}")
    print(f"Orders with qty>1: {with_quantities}")
    print(f"Total time:        {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"Rate:              {total/elapsed:.1f} orders/sec")
    print(f"\nSample results:")
    for s in sample_results:
        print(f"  {s['customer']} ({s['order_id'][:10]}...):")
        for item in s['items']:
            print(f"    - {item}")

    browser.close()
