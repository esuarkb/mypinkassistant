"""
Captures the full request + response for the order detail Apex call
so we can make it directly via HTTP without loading the page.

Usage:
    python dump_order_api.py
"""
import json, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

ORDER_LIST_URL = "https://apps.marykayintouch.com/order-list"
APEX_FRAGMENT  = "/webruntime/api/apex/execute"
OUT_DIR = Path(__file__).parent / "data" / "order_api_dump"
OUT_DIR.mkdir(parents=True, exist_ok=True)

captured_orders = {}
detail_request_log = []

def on_list_response(response):
    if APEX_FRAGMENT not in response.url:
        return
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

def on_detail_request(request):
    if APEX_FRAGMENT not in request.url:
        return
    try:
        detail_request_log.append({
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "post_data": request.post_data,
        })
    except Exception as e:
        print(f"Request capture error: {e}")

def on_detail_response(response):
    if APEX_FRAGMENT not in response.url:
        return
    try:
        body = response.json()
        rv = body.get("returnValue", {})
        if isinstance(rv, dict) and "productDetails" in rv:
            print(f"\n--- productDetails response ---")
            print(json.dumps(rv, indent=2))
    except Exception:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()

    print("Logging in...")
    login_intouch(page, USERNAME, PASSWORD)

    page.on("response", on_list_response)
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
    page.remove_listener("response", on_list_response)

    if not captured_orders:
        print("No orders captured.")
        browser.close()
        exit()

    # Navigate to order detail and capture full request + response
    import base64
    first_order = list(captured_orders.values())[0]
    order_id = first_order.get("Id", "")
    encoded = base64.b64encode(order_id.encode()).decode()
    detail_url = f"https://apps.marykayintouch.com/order-details?orderId={encoded}"
    print(f"\nNavigating to: {detail_url}")

    page.on("request", on_detail_request)
    page.on("response", on_detail_response)
    page.goto(detail_url, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    page.remove_listener("request", on_detail_request)
    page.remove_listener("response", on_detail_response)

    # Save captured requests
    out_file = OUT_DIR / "detail_apex_requests.json"
    with open(out_file, "w") as f:
        json.dump(detail_request_log, f, indent=2)
    print(f"\nSaved {len(detail_request_log)} Apex requests to: {out_file}")

    # Print the one that returned productDetails
    for req in detail_request_log:
        pd = req.get("post_data") or ""
        if pd:
            print(f"\n--- Apex request POST body ---")
            print(pd[:2000])

    # Also grab cookies for direct HTTP calls
    cookies = page.context.cookies()
    cookies_dict = {c["name"]: c["value"] for c in cookies if "marykay" in c.get("domain", "")}
    cookies_file = OUT_DIR / "session_cookies.json"
    with open(cookies_file, "w") as f:
        json.dump(cookies_dict, f, indent=2)
    print(f"\nSession cookies saved to: {cookies_file}")

    browser.close()
    print("\nDone.")
