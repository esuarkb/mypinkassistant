import json
from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
from playwright_automation.login import login_intouch
from auth_core import decrypt_intouch_password
import psycopg2

cfg = dotenv_values('.env.production')
conn = psycopg2.connect(cfg['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT intouch_username, intouch_password_enc FROM consultants WHERE id = 100")
row = cur.fetchone()
conn.close()
username = row[0]
password = decrypt_intouch_password(row[1])

PCP_APP_URL  = "https://apps.marykayintouch.com/enrolled-preferred-customers"
PCP_API_FRAG = "FOReports/api/report?id=customer-pcp-enrolled"

raw_records = []

def on_response(response):
    if PCP_API_FRAG in response.url:
        try:
            data = response.json()
            if isinstance(data, list):
                raw_records.extend(data)
        except Exception as e:
            print(f"Parse error: {e}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    login_intouch(page, username, password)
    page.on("response", on_response)
    page.goto(PCP_APP_URL, wait_until="load", timeout=60000)
    for _ in range(15):
        page.wait_for_timeout(3000)
        if raw_records:
            break
    browser.close()

print(f"Got {len(raw_records)} records")
if raw_records:
    print("\nFirst record fields:")
    print(json.dumps(raw_records[0], indent=2))
    with open("/Users/desktop/pcp_capture_result.json", "w") as f:
        json.dump(raw_records[:5], f, indent=2)
    print("\nFirst 5 saved to /Users/desktop/pcp_capture_result.json")
