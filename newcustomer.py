import json
import sqlite3
from collections import OrderedDict
from pathlib import Path

from playwright.sync_api import Playwright, sync_playwright, TimeoutError as PWTimeoutError

# Pull Intouch creds (decrypt) from your consultants table
from auth_core import get_consultant_intouch_creds

# ---------------------
# SETTINGS
# ---------------------
# Set True if you want to WATCH it fill the form without actually saving anything.
DRY_RUN = False

# SQLite DB path (relative to this script)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"


# ---------------------
# SQLite helpers
# ---------------------
def fetch_customer_jobs():
    """
    Returns a list of (job_id, consultant_id, customer_dict) for queued NEW_CUSTOMER jobs.
    customer_dict keys expected by Playwright:
    "First Name", "Last Name", "Email", "Phone", "Street", "City", "State", "Postal Code"
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, consultant_id, payload_json
        FROM jobs
        WHERE type=? AND status=?
        ORDER BY id ASC
        """,
        ("NEW_CUSTOMER", "queued"),
    )
    rows = cur.fetchall()
    conn.close()

    jobs = []
    for job_id, consultant_id, payload_json in rows:
        if consultant_id is None:
            # If anything older slipped in without consultant_id, fail fast with a clear error
            jobs.append((job_id, None, {"_error": "Missing consultant_id on job. Update mk_chat_core + re-queue."}))
        else:
            jobs.append((job_id, int(consultant_id), json.loads(payload_json)))
    return jobs


def mark_job_done(job_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET status=?, error='' WHERE id=?", ("done", job_id))
    conn.commit()
    conn.close()


def mark_job_failed(job_id: int, error: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET status=?, error=? WHERE id=?", ("failed", error, job_id))
    conn.commit()
    conn.close()


# ---------------------
# Formatting helpers
# ---------------------
def format_street(street: str) -> str:
    """
    Light normalization so '555 5th st' -> '555 5th St'
    (Does not try to be perfect USPS formatting.)
    """
    s = (street or "").strip()
    if not s:
        return ""

    repl = {
        " st": " St",
        " rd": " Rd",
        " ave": " Ave",
        " blvd": " Blvd",
        " dr": " Dr",
        " ln": " Ln",
        " ct": " Ct",
        " cir": " Cir",
        " pkwy": " Pkwy",
        " hwy": " Hwy",
        " pl": " Pl",
        " ter": " Ter",
        " way": " Way",
        " trl": " Trl",
    }

    low = s.lower()
    for k, v in repl.items():
        if low.endswith(k):
            # replace only the ending token
            s = s[:-len(k)] + v
            return s

    # If they typed the whole thing lowercase, title-case words, but preserve numbers.
    # This is intentionally conservative.
    if s == low:
        s = " ".join([w if any(ch.isdigit() for ch in w) else w.capitalize() for w in s.split()])
    return s


def has_address(customer: dict) -> bool:
    street = (customer.get("Street") or "").strip()
    city = (customer.get("City") or "").strip()
    state = (customer.get("State") or "").strip()
    postal = (customer.get("Postal Code") or "").strip()
    return any([street, city, state, postal])


# ---------------------
# Playwright runner
# ---------------------
def ensure_mycustomers_ready(page) -> None:
    """
    Simple readiness check: the MyCustomers page should have a 'New Customer' button.
    If login fails, we won't reach this reliably.
    """
    try:
        page.get_by_role("button", name="New Customer").wait_for(state="visible", timeout=8000)
    except PWTimeoutError:
        raise Exception("MyCustomers not ready: 'New Customer' button not found. (Login likely failed.)")


def login_and_open_mycustomers(page, username: str, password: str) -> None:
    # Go to login page
    page.goto("https://mk.marykayintouch.com/s/login/")
    page.wait_for_timeout(1000)

    # Fill login
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.wait_for_timeout(200)
    page.get_by_role("textbox", name="Password").fill(password)
    page.wait_for_timeout(200)

    # Click login (text is sometimes 'Log In' or similar)
    page.get_by_text("Log In").click()
    page.wait_for_timeout(7000)

    # Navigate to MyCustomers (this is your known-working flow)
    page.goto("https://applications.marykayintouch.com/mycustomers")
    page.wait_for_timeout(3000)

    # Confirm page is usable
    ensure_mycustomers_ready(page)


def run_customer_entry(page, customer: dict) -> None:
    """
    Enters ONE customer into MyCustomers using your existing field/key expectations.
    Skips address entry if no address provided.
    """
    # Add customer button
    page.wait_for_timeout(800)
    page.get_by_role("button", name="New Customer").click()
    page.wait_for_timeout(3000)

    # Fill in customer info
    page.get_by_role("textbox", name="First Name").fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(500)
    page.get_by_role("textbox", name="Last Name").fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(500)
    page.get_by_role("textbox", name="Email Address (Optional)").fill(str(customer.get("Email", "")))
    page.wait_for_timeout(500)
    page.get_by_role("textbox", name="Mobile Phone Number (Optional)").fill(str(customer.get("Phone", "")))
    page.wait_for_timeout(500)

    if DRY_RUN:
        print("🟡 DRY_RUN=True: Stopping before saving customer.")
        return

    # Save customer
    page.get_by_role("button", name="Save New Customer").click()
    page.wait_for_timeout(8000)

    # If there's no street, do NOT open the address dialog (avoids hanging)
    #if not has_address(customer):
    #    print("🟡 No street address provided — skipping address entry.")
    #    return


    # Click the first Add New Address button to open the half-window dialog
    page.get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(2500)

    # Address fields (IDs are hardcoded in your working script)
    page.locator("#AddressFirstName-32").fill(str(customer.get("First Name", "")))
    page.wait_for_timeout(500)
    page.locator("#AddressLastName-32").fill(str(customer.get("Last Name", "")))
    page.wait_for_timeout(500)

    street = format_street(str(customer.get("Street", "")))
    page.locator("#Street-32").fill(street)
    page.wait_for_timeout(500)

    page.locator("#City-32").fill(str(customer.get("City", "")))
    page.wait_for_timeout(500)

    page.locator("#PostalCode-32").fill(str(customer.get("Postal Code", "")))
    page.wait_for_timeout(500)

    # Select state from dropdown (only if provided)
    state = str(customer.get("State", "")).strip()
    if state:
        page.get_by_role("button", name="Select an option").click()
        page.wait_for_timeout(700)
        page.get_by_role("option", name=state).click()
        page.wait_for_timeout(700)

    # Click the Add New Address button inside the dialog to save
    page.get_by_role("dialog").get_by_role("button", name="Add New Address").click()
    page.wait_for_timeout(1500)


# ---------------------
# Main
# ---------------------
def group_by_consultant(jobs):
    grouped = OrderedDict()
    for job_id, consultant_id, payload in jobs:
        grouped.setdefault(consultant_id, []).append((job_id, payload))
    return grouped


if __name__ == "__main__":
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Could not find SQLite DB at: {DB_PATH}\n"
            f"Create it by running db_setup.py and make sure it creates data/mk.db"
        )

    customer_jobs = fetch_customer_jobs()

    if not customer_jobs:
        print("No queued NEW_CUSTOMER jobs found in SQLite.")
        raise SystemExit(0)

    # Group by consultant_id so we never mix accounts in one browser session
    grouped = group_by_consultant(customer_jobs)

    with sync_playwright() as playwright:
        for consultant_id, jobs in grouped.items():
            # If any old jobs are missing consultant_id, fail them cleanly
            if consultant_id is None:
                for job_id, payload in jobs:
                    err = payload.get("_error") or "Missing consultant_id on job."
                    mark_job_failed(job_id, err)
                    print(f"❌ Job {job_id} failed: {err}")
                continue

            try:
                username, password = get_consultant_intouch_creds(consultant_id)
                if not username or not password:
                    raise Exception(
                        "Intouch credentials not set. Go to Settings and enter Intouch username + password."
                    )

                # Fresh browser session per consultant (NO cross-contamination)
                browser = playwright.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()

                # Login + open MyCustomers
                login_and_open_mycustomers(page, username, password)

            except Exception as e:
                # If login fails, mark ALL this consultant's queued customer jobs failed
                for job_id, _payload in jobs:
                    mark_job_failed(job_id, str(e))
                    print(f"❌ Job {job_id} failed: {e}")
                try:
                    context.close()
                    browser.close()
                except Exception:
                    pass
                continue

            # Process this consultant's jobs in FIFO order
            for job_id, customer in jobs:
                try:
                    run_customer_entry(page, customer)
                    mark_job_done(job_id)
                    print(f"✅ Job {job_id} done: {customer.get('First Name','')} {customer.get('Last Name','')}")
                except Exception as e:
                    mark_job_failed(job_id, str(e))
                    print(f"❌ Job {job_id} failed: {e}")

            # Close browser before moving to the next consultant
            try:
                context.close()
                browser.close()
            except Exception:
                pass
