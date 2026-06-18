# run_car_award_test.py
# Navigates to mk.marykayintouch.com/s/reports, intercepts all FOReports API
# calls that fire (including car award), and prints the raw JSON responses.
# Usage: python run_car_award_test.py

import json
import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

from playwright_automation.login import login_intouch

USERNAME = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("INTOUCH_USER", "")
PASSWORD = os.environ.get("INTOUCH_PASS", "")

if not USERNAME or not PASSWORD:
    print("Set INTOUCH_USER and INTOUCH_PASS in .env or pass username as arg")
    sys.exit(1)

_FOREPORTS_FRAG = "FOReports/api"
captured = []
all_requests = []
OUTPUT_FILE = "/Users/desktop/car_award_captured.json"
REQUESTS_FILE = "/Users/desktop/car_all_requests.txt"

def _on_response(response):
    url = response.url
    # Log ALL requests to the requests file so we can see Guidelines URL etc.
    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{response.status} {url}\n")
    # Capture FOReports JSON responses
    if _FOREPORTS_FRAG in url:
        try:
            data = response.json()
            entry = {"url": url, "status": response.status, "data": data}
            captured.append(entry)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(captured, f, indent=2, default=str)
            sys.stdout.write(f"\n[CAPTURED] {url}  status={response.status}\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(f"\n[CAPTURED non-JSON] {url}  err={e}\n")
            sys.stdout.flush()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()
    page.on("response", _on_response)

    print(f"Logging in as {USERNAME}...")
    login_intouch(page, USERNAME, PASSWORD)
    print("Logged in.")

    # Establish cross-domain session first
    print("\nEstablishing cross-domain session via consultant-list...")
    page.goto("https://mk.marykayintouch.com/s/consultant-list", wait_until="load", timeout=60000)
    page.wait_for_timeout(3000)

    print("\nNavigating to career car guidelines page...")
    page.goto("https://mk.marykayintouch.com/s/career-car", wait_until="load", timeout=60000)

    # Wait for initial load
    for _ in range(8):
        page.wait_for_timeout(3000)
        if len(captured) >= 2:
            break

    page.screenshot(path="/Users/desktop/car_page_1.png")
    print("  [screenshot: car_page_1.png]")

    # Wait for FOReports data to load and render
    for _ in range(10):
        page.wait_for_timeout(3000)
        if len(captured) >= 3:
            break
    page.wait_for_timeout(3000)  # extra settle time for rendering
    # Try main frame first, then all iframes
    all_text = []
    all_text.append("=== MAIN FRAME ===")
    all_text.append(page.evaluate("() => document.body.innerText"))

    for i, frame in enumerate(page.frames):
        if frame == page.main_frame:
            continue
        try:
            txt = frame.evaluate("() => document.body ? document.body.innerText : ''")
            if txt and len(txt.strip()) > 50:
                all_text.append(f"\n=== FRAME {i} ({frame.url[:80]}) ===")
                all_text.append(txt)
                # Also grab Guidelines link from this frame
                try:
                    g = frame.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a'));
                            const gl = links.find(l => l.textContent.trim() === 'Guidelines');
                            return gl ? gl.href : null;
                        }
                    """)
                    if g:
                        all_text.append(f"  [Guidelines href: {g}]")
                except Exception:
                    pass
        except Exception as e:
            all_text.append(f"\n=== FRAME {i} error: {e} ===")

    combined = "\n".join(all_text)
    with open("/Users/desktop/car_page_text.txt", "w") as f:
        f.write(combined)
    sys.stdout.write(f"  [page text saved ({len(combined)} chars): car_page_text.txt]\n")
    sys.stdout.flush()

    # Full page screenshot
    page.screenshot(path="/Users/desktop/car_page_full.png", full_page=True)
    sys.stdout.write("  [full page screenshot saved]\n")
    sys.stdout.flush()

    # Keep browser open for manual exploration
    print("\nBrowser open — click 'CAR PROGRAM' nav, Guidelines, scroll around.")
    print("Press Ctrl+C when done.\n")
    shot_count = 1
    try:
        while True:
            page.wait_for_timeout(5000)
            shot_count += 1
            page.screenshot(path=f"/Users/desktop/car_page_{shot_count}.png", full_page=True)
            # Also re-extract text in case page changed
            txt = page.evaluate("() => document.body.innerText")
            with open(f"/Users/desktop/car_page_text_{shot_count}.txt", "w") as f:
                f.write(txt)
            sys.stdout.write(f"  [shot {shot_count}, {len(captured)} captures]\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass

    browser.close()

print("\nDone.")
