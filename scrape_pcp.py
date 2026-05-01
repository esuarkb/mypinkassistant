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
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from playwright_automation.login import login_intouch
from auth_core import decrypt_intouch_password
from db import tx, is_postgres

PCP_URL      = "https://applications.marykayintouch.com/pcp/Mailings/Enroll.aspx"
PAGE_SIZE_ID = "ctl00_ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1_cphMain_gp_lstPageSize"
FILTER_ID    = "ctl00_ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1_cphMain_gp_lstCustomerFilter"
NEXT_BTN_ID  = "ctl00_ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1_cphMain_btnNext"

EXTRACT_JS = """
() => {
    const results = [];
    document.querySelectorAll('tr').forEach(tr => {
        const cells = [...tr.querySelectorAll('td')];
        if (cells.length < 4) return;
        const nameLink = cells[0]?.querySelector('a');
        if (!nameLink) return;
        const name = nameLink.innerText.replace(/ /g, ' ').trim();
        if (!name || name.length < 2) return;
        if (name.includes("What's") || name.startsWith('Add a') || name.startsWith('Select All')) return;
        const lang = cells[1]?.innerText.trim() || '';
        if (lang.includes('Preference')) return;
        const enrolledLabel = [...tr.querySelectorAll('b')].find(b => b.innerText.includes('Enrolled'));
        const checkbox = tr.querySelector('input[type=checkbox]');
        const enrolled = !!(enrolledLabel || (checkbox && checkbox.checked));
        results.push({ name, enrolled });
    });
    return results;
}
"""


def current_quarter() -> str:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return f"{today.year}-Q{q}"


def scrape_enrolled(page, username: str, password: str) -> list[dict]:
    login_intouch(page, username, password)

    page.goto(PCP_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    page.select_option(f"#{PAGE_SIZE_ID}", "500")
    page.wait_for_timeout(2000)
    page.select_option(f"#{FILTER_ID}", "ContactKey Enrolled")
    page.wait_for_timeout(2000)

    all_customers: list[dict] = []
    seen_names: set[str] = set()
    page_num = 1

    while True:
        rows = page.evaluate(EXTRACT_JS)
        new_rows = [r for r in rows if r['name'] not in seen_names]
        if not new_rows:
            break

        for r in new_rows:
            seen_names.add(r['name'])
        all_customers.extend(new_rows)
        print(f"    Page {page_num}: {len(new_rows)} enrolled customers")

        next_disabled = page.evaluate(f"""
            () => {{
                const btn = document.getElementById('{NEXT_BTN_ID}');
                if (!btn) return true;
                return btn.disabled || btn.classList.contains('disabled') || btn.getAttribute('disabled') !== null;
            }}
        """)
        if next_disabled:
            break

        try:
            page.click(f"#{NEXT_BTN_ID}")
            page.wait_for_timeout(2500)
            page_num += 1
        except Exception:
            break

    return all_customers


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
                print("  No enrolled customers found — no PCP enrollments or enrollment window not yet open.")
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
