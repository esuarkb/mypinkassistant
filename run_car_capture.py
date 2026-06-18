# run_car_capture.py — one-shot: login, navigate to career-car page, capture FOReports response, exit.
import json, os, sys
from dotenv import load_dotenv
load_dotenv()
from playwright.sync_api import sync_playwright
from playwright_automation.login import login_intouch

USERNAME = os.environ.get("INTOUCH_USER", "")
PASSWORD = os.environ.get("INTOUCH_PASS", "")
if not USERNAME or not PASSWORD:
    print("Set INTOUCH_USER and INTOUCH_PASS in .env")
    sys.exit(1)

OUTPUT = "/Users/desktop/car_capture_result.json"
_FRAG = "FOReports/api"
captured = []

def _on_response(response):
    if _FRAG not in response.url:
        return
    try:
        data = response.json()
        entry = {"url": response.url, "status": response.status, "data": data}
        captured.append(entry)
        print(f"[CAPTURED] {response.url}  status={response.status}")
        if isinstance(data, list) and data:
            print(f"  First record keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0])}")
        elif isinstance(data, dict):
            print(f"  Keys: {list(data.keys())}")
    except Exception as e:
        print(f"[non-JSON] {response.url}  err={e}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()
    page.on("response", _on_response)

    print(f"Logging in as {USERNAME}...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in. Establishing cross-domain session...")

    page.goto("https://mk.marykayintouch.com/s/consultant-list", wait_until="load", timeout=60000)
    page.wait_for_timeout(3000)

    print("Navigating to director career car detail page...")
    page.goto("https://mk.marykayintouch.com/s/reports/director-career-car-detail", wait_until="load", timeout=60000)

    # Wait up to 30s for a car-related FOReports response
    for i in range(30):
        page.wait_for_timeout(1000)
        car_hits = [c for c in captured if "car" in c["url"].lower()]
        if car_hits:
            print(f"Got car data after {i+1}s")
            break
        if i % 5 == 4:
            print(f"  Still waiting... ({i+1}s, {len(captured)} total captures)")

    # Also try career-car page if nothing yet
    if not any("car" in c["url"].lower() for c in captured):
        print("No car data from detail page, trying /s/career-car...")
        page.goto("https://mk.marykayintouch.com/s/career-car", wait_until="load", timeout=60000)
        for i in range(20):
            page.wait_for_timeout(1000)
            if any("car" in c["url"].lower() for c in captured):
                break

    browser.close()

with open(OUTPUT, "w") as f:
    json.dump(captured, f, indent=2, default=str)
print(f"\nSaved {len(captured)} captures to {OUTPUT}")
if captured:
    for c in captured:
        if "car" in c["url"].lower():
            print(f"\n=== CAR ENDPOINT ===")
            print(f"URL: {c['url']}")
            d = c["data"]
            if isinstance(d, list) and d:
                print(f"Records: {len(d)}")
                print(f"First record:\n{json.dumps(d[0], indent=2, default=str)}")
            elif isinstance(d, dict):
                print(f"Response:\n{json.dumps(d, indent=2, default=str)}")
