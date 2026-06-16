"""
Scrape the InTouch Preferred Customer Program enrollment page for every
active consultant and store a quarterly snapshot in pcp_enrollments.

Usage:
    python scrape_pcp.py [--quarter 2026-Q2] [--consultant-id N]

The quarter label defaults to the current calendar quarter derived from
today's date (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec).
Run once per quarter after enrollment closes.
"""
import sys
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright

from playwright_automation.login import login_intouch
from auth_core import decrypt_intouch_password
from db import tx, is_postgres

PCP_APP_URL  = "https://apps.marykayintouch.com/enrolled-preferred-customers"
PCP_API_FRAG = "FOReports/api/report?id=customer-pcp-enrolled"


def current_quarter() -> str:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return f"{today.year}-Q{q}"


def scrape_enrolled(page, username: str, password: str, skip_login: bool = False) -> list[dict]:
    if not skip_login:
        login_intouch(page, username, password)

    raw_records: list[dict] = []

    def _on_response(response):
        if PCP_API_FRAG in response.url:
            try:
                data = response.json()
                if isinstance(data, list):
                    raw_records.extend(data)
            except Exception as e:
                print(f"[PcpSync] API response parse error: {e}")

    page.on("response", _on_response)
    try:
        page.goto(PCP_APP_URL, wait_until="load", timeout=60000)
        if "Alerts.aspx" in page.url or "TermsAndConditions" in page.url:
            raise RuntimeError("PCP Terms & Conditions not yet accepted in InTouch")

        # Wait up to 45s for the FOReports API call to fire and return
        for _ in range(15):
            page.wait_for_timeout(3000)
            if raw_records:
                break
    finally:
        page.remove_listener("response", _on_response)

    print(f"[PcpSync] {len(raw_records)} enrolled customers from API")
    return [
        {"name": f"{r['firstName']} {r['lastName']}", "enrolled": True}
        for r in raw_records
        if r.get("firstName") and r.get("lastName")
    ]


def get_consultants(cur, consultant_id: int | None) -> list:
    PH = "%s" if is_postgres() else "?"
    if consultant_id:
        cur.execute(f"""
            SELECT id, email, intouch_username, intouch_password_enc
            FROM consultants
            WHERE id = {PH} AND intouch_username IS NOT NULL AND intouch_password_enc IS NOT NULL
        """, (consultant_id,))
    else:
        cur.execute("""
            SELECT id, email, intouch_username, intouch_password_enc
            FROM consultants
            WHERE intouch_username IS NOT NULL
              AND intouch_password_enc IS NOT NULL
              AND intouch_password_enc != ''
              AND billing_status IN ('active', 'trialing')
            ORDER BY id
        """)
    return cur.fetchall()


def save_to_db(cur, enrolled: list[dict], consultant_id: int, quarter: str) -> int:
    PH = "%s" if is_postgres() else "?"
    now = "NOW()" if is_postgres() else "datetime('now')"
    upserted = 0
    for c in enrolled:
        cur.execute(f"""
            INSERT INTO pcp_enrollments (consultant_id, pcp_name, quarter, enrolled, customer_id, scraped_at)
            VALUES (
                {PH}, {PH}, {PH}, {PH},
                (SELECT id FROM customers
                 WHERE consultant_id = {PH}
                 AND first_name || ' ' || last_name = {PH}
                 LIMIT 1),
                {now}
            )
            ON CONFLICT (consultant_id, pcp_name, quarter)
            DO UPDATE SET
                enrolled    = EXCLUDED.enrolled,
                customer_id = EXCLUDED.customer_id,
                scraped_at  = {now}
        """, (consultant_id, c['name'], quarter, c['enrolled'], consultant_id, c['name']))
        upserted += 1

    # Remove anyone no longer on this quarter's list — each quarter is a complete snapshot
    if enrolled:
        scraped_names = [c['name'] for c in enrolled]
        if is_postgres():
            cur.execute(
                f"DELETE FROM pcp_enrollments WHERE consultant_id = {PH} AND quarter = {PH} AND pcp_name != ALL({PH})",
                (consultant_id, quarter, scraped_names)
            )
        else:
            placeholders = ",".join("?" * len(scraped_names))
            cur.execute(
                f"DELETE FROM pcp_enrollments WHERE consultant_id = ? AND quarter = ? AND pcp_name NOT IN ({placeholders})",
                [consultant_id, quarter] + scraped_names
            )

    return upserted


def main():
    args = sys.argv[1:]

    quarter = current_quarter()
    if "--quarter" in args:
        idx = args.index("--quarter")
        quarter = args[idx + 1]

    consultant_id = None
    if "--consultant-id" in args:
        idx = args.index("--consultant-id")
        consultant_id = int(args[idx + 1])

    with tx() as (conn, cur):
        consultants = get_consultants(cur, consultant_id)

    db_type = "Postgres" if is_postgres() else "SQLite"
    print(f"Quarter: {quarter}  |  DB: {db_type}  |  Consultants to process: {len(consultants)}")

    if not consultants:
        print("No consultants found.")
        return

    total_enrolled = 0
    total_saved = 0

    with sync_playwright() as p:
        for c in consultants:
            cid   = c[0] if not hasattr(c, 'get') else c['id']
            email = c[1] if not hasattr(c, 'get') else c['email']
            uname = c[2] if not hasattr(c, 'get') else c['intouch_username']
            penc  = c[3] if not hasattr(c, 'get') else c['intouch_password_enc']

            print(f"\n[Consultant {cid}] {email} ({uname})")

            try:
                password = decrypt_intouch_password(penc)
            except Exception as e:
                print(f"  Could not decrypt password: {e} — skipping")
                continue

            try:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                enrolled = scrape_enrolled(page, uname, password)
                browser.close()
            except Exception as e:
                print(f"  Scrape failed: {e} — skipping")
                try:
                    browser.close()
                except Exception:
                    pass
                continue

            if not enrolled:
                print("  No enrolled customers found — enrollment window may not be open.")
                continue

            with tx() as (conn, cur):
                saved = save_to_db(cur, enrolled, cid, quarter)

            print(f"  Enrolled: {len(enrolled)}  |  Saved: {saved}")
            total_enrolled += len(enrolled)
            total_saved += saved

    print(f"\n{'='*50}")
    print(f"PCP Snapshot complete — {quarter}")
    print(f"DB             : {db_type}")
    print(f"Consultants    : {len(consultants)}")
    print(f"Total enrolled : {total_enrolled}")
    print(f"Total saved    : {total_saved}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
