## change to better batching process for orders

# worker.py
import os
import json
import time
import requests
import traceback
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
from pathlib import Path
from db import connect, is_postgres, get_system_setting

from emailer import send_wrong_credentials_email, send_login_failure_alert_email
from playwright_automation.customer_export import download_customer_export
from customer_import_parser import parse_customer_export_xlsx
from customer_import_store import import_customers_from_rows

PB_API_KEY = os.getenv("PB_API_KEY", "").strip()
PB_CONTACT_ID = os.getenv("PB_CONTACT_ID", "").strip()

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "60"))
_last_alert_time = 0.0
_last_outage_alert_time = 0.0


def send_failure_text(message: str) -> None:
    global _last_alert_time

    if not PB_API_KEY or not PB_CONTACT_ID:
        print("[Worker] Missing PB credentials")
        return

    now = time.time()
    seconds_since_last = now - _last_alert_time

    if seconds_since_last < ALERT_COOLDOWN_SECONDS:
        remaining = int(ALERT_COOLDOWN_SECONDS - seconds_since_last)
        print(f"[Worker] PB alert suppressed ({remaining}s cooldown remaining)")
        return

    url = f"https://app.projectbroadcast.com/api/v1/contacts/{PB_CONTACT_ID}/send"

    headers = {
        "x-api-key": PB_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "text": message[:1500]
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        print("[Worker] PB alert status:", r.status_code)
        print("[Worker] PB alert response:", r.text)

        if r.ok:
            _last_alert_time = now

    except Exception as e:
        print("[Worker] Failed to send PB alert:", e)

from playwright.sync_api import sync_playwright

from auth_core import get_consultant_intouch_creds
from worker_queue import (
    WORKER_ID,
    claim_next_consultant,
    claim_next_job_for_consultant,
    claim_next_order_row_for_consultant,  # ✅ needed for batching
    requeue_job,                          # ✅ needed to safely put back other-customer rows
    mark_job_done,
    mark_job_failed,
    refresh_consultant_lock,
    release_consultant,
)

from playwright_automation.login import login_intouch
from playwright_automation.new_customer import create_customer_basic
from playwright_automation.orders import process_order_batch, SkuNotCdsEligible
from playwright_automation.inventory_import import import_inventory_orders
from inventory_import_store import ensure_import_table
for _startup_attempt in range(5):
    try:
        ensure_import_table()
        break
    except Exception as _startup_err:
        print(f"[Worker] DB not ready yet (attempt {_startup_attempt + 1}/5): {_startup_err}")
        if _startup_attempt < 4:
            time.sleep(10)
        else:
            print("[Worker] DB unavailable after 5 attempts — exiting for restart")
            raise

# How long to keep the browser open after the last job (seconds)
IDLE_GRACE_SECONDS = 45

class _RequeueSilently(Exception):
    """Raised to skip failure handling when a job has been requeued for a silent retry."""

# Order batching controls (tweak via env vars without code changes)
MAX_ORDER_ROWS_PER_BATCH = int(os.getenv("MAX_ORDER_ROWS_PER_BATCH", "25"))
ORDER_BATCH_GRACE_MS = int(os.getenv("ORDER_BATCH_GRACE_MS", "800"))  # brief window to catch rapid-fire items


def _missing_creds_message() -> str:
    return "Missing Intouch credentials. Please open Settings and save your Intouch username + password."

def _fail_all_queued_jobs_for_consultant(cid: int, msg: str) -> None:
    """
    Drain this consultant's queued jobs and mark them failed with a user-friendly message.
    Assumes this worker already holds the consultant lock.
    """
    while True:
        refresh_consultant_lock(cid)
        claimed = claim_next_job_for_consultant(cid)
        if not claimed:
            break
        job_id, _job_type, _payload_json = claimed
        mark_job_failed(job_id, msg)

def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _same_customer(a: dict, b: dict) -> bool:
    return (
        _norm(a.get("First Name", "")) == _norm(b.get("First Name", ""))
        and _norm(a.get("Last Name", "")) == _norm(b.get("Last Name", ""))
        and _norm(a.get("fulfillment_method", "inventory")) == _norm(b.get("fulfillment_method", "inventory"))
    )


def _claim_more_order_rows_for_same_customer(cid: int, first_payload: dict):
    """
    Claims additional NEW_ORDER_ROW jobs for the same customer (FIFO),
    up to MAX_ORDER_ROWS_PER_BATCH.
    If we accidentally claim an order for a different customer, we requeue it and stop.
    Returns: list of tuples [(job_id, payload_dict), ...]
    """
    out = []
    deadline = time.time() + (ORDER_BATCH_GRACE_MS / 1000.0)

    while len(out) < (MAX_ORDER_ROWS_PER_BATCH - 1):
        # Small grace window so if user submits multiple items quickly,
        # we have a chance to catch them in the same batch.
        if time.time() < deadline:
            time.sleep(0.05)

        refresh_consultant_lock(cid)

        claimed = claim_next_order_row_for_consultant(cid)
        if not claimed:
            break

        job_id2, job_type2, payload_json2 = claimed
        if job_type2 != "NEW_ORDER_ROW":
            # Should never happen because this claim function is type-filtered,
            # but fail safe:
            requeue_job(job_id2, "Queued")
            break

        try:
            payload2 = json.loads(payload_json2)
        except Exception:
            mark_job_failed(job_id2, "Something unexpected happened. Please refresh the page and try again.")
            continue

        if not _same_customer(first_payload, payload2):
            # Not the same customer — put it back and stop batching
            requeue_job(job_id2, "Queued")
            break

        out.append((job_id2, payload2))

    return out


PH_W = "%s" if is_postgres() else "?"


def _record_login_failure(cid: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE consultants
            SET consecutive_login_failures = consecutive_login_failures + 1,
                last_login_failure_at = {PH_W}
            WHERE id = {PH_W}
            """,
            (now, cid),
        )
        conn.commit()
    finally:
        conn.close()


def _is_intouch_outage() -> bool:
    """Return True if 2+ different consultants have failed login in the last 30 minutes."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    conn = connect()
    try:
        cur = conn.cursor()
        PH_L = "%s" if is_postgres() else "?"
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT id) FROM consultants
            WHERE last_login_failure_at >= {PH_L}
              AND consecutive_login_failures >= 1
            """,
            (cutoff,),
        )
        row = cur.fetchone()
        count = row[0] if row else 0
        return count >= 2
    finally:
        conn.close()


def _reset_login_failures(cid: int) -> None:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE consultants
            SET consecutive_login_failures = 0,
                last_login_failure_at = NULL
            WHERE id = {PH_W}
            """,
            (cid,),
        )
        conn.commit()
    finally:
        conn.close()


def main():
    print(f"✅ Worker starting: {WORKER_ID}")
    #send_failure_text("✅ Test alert from MyPinkAssistant worker")

    with sync_playwright() as pw:
        while True:
            try:
                paused = (get_system_setting("queue_paused", "0") or "0").strip() == "1"
            except Exception:
                paused = False
            if paused:
                print("[Worker] Queue paused — sleeping")
                time.sleep(5)
                continue

            try:
                cid = claim_next_consultant()
            except Exception as _claim_err:
                print(f"[Worker] DB error claiming consultant — will retry: {_claim_err}")
                time.sleep(10)
                continue
            if not cid:
                time.sleep(1)
                continue

            browser = None
            context = None

            try:
                refresh_consultant_lock(cid)

                username, password = get_consultant_intouch_creds(cid)
                username = (username or "").strip()
                password = (password or "").strip()

                # Fetch consultant name/email for alerts
                _c_info_conn = connect()
                try:
                    _c_info_cur = _c_info_conn.cursor()
                    _c_info_cur.execute(
                        f"SELECT first_name, last_name, email, language FROM consultants WHERE id = {PH_W}",
                        (cid,),
                    )
                    _c_info_row = _c_info_cur.fetchone()
                finally:
                    _c_info_conn.close()
                if _c_info_row:
                    _c_first = (_c_info_row[0] if not isinstance(_c_info_row, dict) else _c_info_row["first_name"]) or ""
                    _c_last = (_c_info_row[1] if not isinstance(_c_info_row, dict) else _c_info_row["last_name"]) or ""
                    _c_email = (_c_info_row[2] if not isinstance(_c_info_row, dict) else _c_info_row["email"]) or ""
                    _c_lang = (_c_info_row[3] if not isinstance(_c_info_row, dict) else _c_info_row["language"]) or "en"
                else:
                    _c_first = _c_last = _c_email = ""
                    _c_lang = "en"
                _c_name = f"{_c_first} {_c_last}".strip() or f"ID {cid}"

                # Headless only if explicitly set to true
                HEADLESS = os.getenv("HEADLESS", "").lower() == "true"
                print("HEADLESS env:", os.getenv("HEADLESS"))
                print("HEADLESS resolved:", HEADLESS)

                browser = pw.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    reduced_motion="reduce",
                    locale="en-US",
                    timezone_id="America/Chicago",
                )
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = context.new_page()
                

                # Login once for this consultant session
                try:
                    login_intouch(page, username, password)
                    _reset_login_failures(cid)
                except Exception as e:
                    err = str(e)

                    friendly = (
                        "InTouch login failed. Please check your InTouch username/password in Settings "
                        "and try again."
                    )

                    _record_login_failure(cid)

                    if _is_intouch_outage():
                        global _last_outage_alert_time
                        if time.time() - _last_outage_alert_time > 3600:
                            send_failure_text(
                                f"🚨 InTouch outage detected — multiple consultants failing login. Suppressing individual alerts."
                            )
                            _last_outage_alert_time = time.time()
                    else:
                        try:
                            admin_email = (os.getenv("MK_ADMIN_EMAILS") or "").split(",")[0].strip()
                            if admin_email:
                                send_login_failure_alert_email(admin_email, cid, _c_name, _c_email, err)
                        except Exception as alert_err:
                            print(f"[Worker] Failed to send login failure email: {alert_err}")

                    # Send credentials email on first failure only, unless InTouch is down
                    try:
                        failures_now = None
                        conn_tmp = connect()
                        try:
                            cur_tmp = conn_tmp.cursor()
                            PH_TMP = "%s" if is_postgres() else "?"
                            cur_tmp.execute(
                                f"SELECT consecutive_login_failures, last_login_failure_at FROM consultants WHERE id = {PH_TMP}",
                                (cid,),
                            )
                            row_tmp = cur_tmp.fetchone()
                        finally:
                            conn_tmp.close()

                        if row_tmp:
                            failures_now = int((row_tmp[0] if not isinstance(row_tmp, dict) else row_tmp["consecutive_login_failures"]) or 0)
                            last_failure_at = row_tmp[1] if not isinstance(row_tmp, dict) else row_tmp["last_login_failure_at"]

                            is_bad_creds = "invalid username or password" in err.lower()

                            # Send credentials email at most once per 24 hours
                            _creds_email_sent = False
                            if last_failure_at and failures_now > 1:
                                if isinstance(last_failure_at, str):
                                    last_failure_at = datetime.fromisoformat(last_failure_at.replace("Z", "+00:00"))
                                if last_failure_at.tzinfo is None:
                                    last_failure_at = last_failure_at.replace(tzinfo=timezone.utc)
                                hours_since = (datetime.now(timezone.utc) - last_failure_at).total_seconds() / 3600
                                _creds_email_sent = hours_since < 24

                            if is_bad_creds and not _is_intouch_outage() and not _creds_email_sent:
                                send_wrong_credentials_email(_c_email, _c_first or "", lang=_c_lang)
                                print(f"[Worker] Credentials email sent to consultant_id={cid}")
                            elif not is_bad_creds:
                                print(f"[Worker] Login failed but not a credentials error — suppressing credentials email for consultant_id={cid}")
                            elif _is_intouch_outage():
                                print(f"[Worker] InTouch outage detected — suppressing credentials email for consultant_id={cid}")
                    except Exception as email_err:
                        print(f"[Worker] Failed to send credentials email: {email_err}")

                    while True:
                        refresh_consultant_lock(cid)
                        claimed = claim_next_job_for_consultant(cid)
                        if not claimed:
                            break
                        job_id, _job_type, _payload_json = claimed
                        mark_job_failed(job_id, err, friendly)

                    print(f"[Worker] Login failed for consultant_id={cid}: {err}")
                    continue

                last_job_time = time.time()

                # Keep processing until idle
                while True:
                    refresh_consultant_lock(cid)

                    claimed = claim_next_job_for_consultant(cid)
                    if not claimed:
                        if time.time() - last_job_time > IDLE_GRACE_SECONDS:
                            break
                        time.sleep(0.5)
                        continue

                    job_id, job_type, payload_json = claimed
                    last_job_time = time.time()

                    try:
                        payload = json.loads(payload_json)

                        # -------------------------
                        # NEW_CUSTOMER
                        # -------------------------
                        if job_type == "NEW_CUSTOMER":
                            page.goto("https://apps.marykayintouch.com/customer-list")
                            subscription_ok = create_customer_basic(page, payload)

                            full_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            sub_note = "" if subscription_ok else " (subscription toggle failed — verify opt-in in InTouch)"
                            mark_job_done(job_id, f"Customer {full_name} complete! ✅{sub_note}")

                        # -------------------------
                        # NEW_ORDER_ROW (✅ batching)
                        # -------------------------
                        elif job_type == "NEW_ORDER_ROW":
                            # Default to just this one job in case batching fails early
                            job_ids = [job_id]

                            # Grab more queued order rows for the same customer (if any)
                            extra = _claim_more_order_rows_for_same_customer(cid, payload)

                            rows = [payload] + [p for (_jid, p) in extra]
                            job_ids = [job_id] + [jid for (jid, _p) in extra]

                            # Process one MyCustomers order containing all SKUs
                            skipped_msg = None
                            try:
                                process_order_batch(page, rows)
                            except SkuNotCdsEligible as e:
                                skipped_msg = str(e)

                            customer_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            fulfillment = payload.get("fulfillment_method", "inventory")
                            leave_pending = bool(payload.get("leave_pending", False))
                            if skipped_msg:
                                done_msg = f"CDS order for {customer_name} saved, but some items were skipped: {skipped_msg}"
                            elif fulfillment == "cds":
                                done_msg = f"CDS order for {customer_name} saved — pending in MyCustomers. ✅"
                            elif leave_pending:
                                done_msg = f"Order for {customer_name} saved as pending. ✅"
                            else:
                                done_msg = f"Order for {customer_name} complete! ✅"
                            for jid in job_ids:
                                mark_job_done(jid, done_msg)

                        # -------------------------
                        # IMPORT_CUSTOMERS
                        # -------------------------
                        elif job_type == "IMPORT_CUSTOMERS":
                            import_path = Path(f"/tmp/customer_import_{cid}.xlsx")

                            # Step 1: download export from MyCustomers
                            saved_path = download_customer_export(page, str(import_path))

                            # No customers in MyCustomers yet — nothing to import
                            if saved_path is None:
                                mark_job_done(job_id, "No customers found in MyCustomers — import skipped.")
                                continue

                            # Step 2: parse file into structured rows
                            rows = parse_customer_export_xlsx(saved_path)

                            # Step 3: insert/update database
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                summary = import_customers_from_rows(
                                    cur,
                                    consultant_id=cid,
                                    rows=rows
                                )
                                conn.commit()
                            finally:
                                conn.close()

                            # Step 4: mark success
                            mark_job_done(
                                job_id,
                                f"Customer import complete! Added {summary['inserted']}, updated {summary['updated']}."
                            )

                        # -------------------------
                        # IMPORT_INVENTORY_ORDERS
                        # -------------------------
                        elif job_type == "IMPORT_INVENTORY_ORDERS":
                            date_range = payload.get("date_range", "days90")
                            seed_only = bool(payload.get("seed_only", False))
                            result = import_inventory_orders(
                                page,
                                consultant_id=cid,
                                username=username,
                                password=password,
                                date_range=date_range,
                                seed_only=seed_only,
                            )
                            if seed_only:
                                mark_job_done(job_id, "Inventory watermark set — new orders will be imported nightly.")
                            else:
                                n = len(result["imported"])
                                skus = len(result["sku_totals"])
                                mark_job_done(
                                    job_id,
                                    f"Inventory import complete — {n} new order(s), {skus} SKU(s) added."
                                )

                        # -------------------------
                        # Unknown job type
                        # -------------------------
                        else:
                            mark_job_failed(job_id, "Something unexpected happened. Please refresh the page and try again.")

                    except _RequeueSilently:
                        pass  # jobs already requeued above; skip alert + mark_failed

                    except Exception as e:
                        raw_err = str(e)

                        # Default user-facing message should be safe and non-technical
                        err_text = "Something went wrong submitting this. Please try again."

                        if "Timeout" in raw_err and "New Customer" in raw_err:
                            err_text = (
                                "Could not reach MyCustomers after login. "
                                "Please verify your InTouch credentials in Settings and try again."
                            )

                        elif "Customer not found" in raw_err:
                            # Check if this customer was just created via a NEW_CUSTOMER job
                            # in the last 10 minutes. If so, InTouch may not have indexed them
                            # yet — requeue silently instead of failing.
                            if job_type == "NEW_ORDER_ROW":
                                cust_first = (payload.get("First Name") or "").strip().lower()
                                cust_last  = (payload.get("Last Name")  or "").strip().lower()
                                try:
                                    _rc_conn = connect()
                                    _rc_cur = _rc_conn.cursor()
                                    # Check attempt count for the first job — if > 1 this
                                    # has already been retried once; don't loop forever.
                                    _rc_cur.execute(
                                        f"SELECT attempts FROM jobs WHERE id={PH_W}",
                                        (job_ids[0],),
                                    )
                                    _att_row = _rc_cur.fetchone()
                                    _attempts = int(_att_row[0]) if _att_row else 99

                                    _recent = None
                                    if _attempts <= 1:
                                        if is_postgres():
                                            _rc_cur.execute(
                                                f"""
                                                SELECT id FROM jobs
                                                WHERE consultant_id = {PH_W}
                                                  AND type = 'NEW_CUSTOMER'
                                                  AND status = 'done'
                                                  AND finished_at >= NOW() - INTERVAL '10 minutes'
                                                  AND LOWER(payload_json::text) LIKE {PH_W}
                                                LIMIT 1
                                                """,
                                                (cid, f"%{cust_first}%"),
                                            )
                                        else:
                                            _rc_cur.execute(
                                                f"""
                                                SELECT id FROM jobs
                                                WHERE consultant_id = {PH_W}
                                                  AND type = 'NEW_CUSTOMER'
                                                  AND status = 'done'
                                                  AND finished_at >= datetime('now', '-600 seconds')
                                                  AND LOWER(payload_json) LIKE {PH_W}
                                                LIMIT 1
                                                """,
                                                (cid, f"%{cust_first}%"),
                                            )
                                        _recent = _rc_cur.fetchone()
                                    _rc_conn.close()
                                except Exception:
                                    _recent = None

                                if _recent:
                                    print(
                                        f"[Worker] Customer not found for job(s) {job_ids} "
                                        f"but NEW_CUSTOMER ran recently — requeueing silently."
                                    )
                                    for jid in job_ids:
                                        requeue_job(jid, "Queued")
                                    # Skip the failure alert + mark_job_failed below
                                    raise _RequeueSilently()

                            err_text = raw_err

                        elif "Change Delivery Status Icon" in raw_err or "Add to Bag" in raw_err:
                            err_text = (
                                "MyPinkAssistant could not submit this order because Mary Kay needs the customer's "
                                "address to be confirmed in MyCustomers. Please open that customer in MyCustomers, "
                                "verify or re-save the address, and then try the order again."
                            )

                        elif "Invalid payload_json" in raw_err or "Unknown job type" in raw_err:
                            err_text = "Something unexpected happened. Please try again."

                        customer_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                        item_desc = payload.get("Item Description", "") or payload.get("Product", "") or ""

                        send_failure_text(
                            f"🚨 MyPinkAssistant Worker Failure\n\n"
                            f"Type: Job Failure\n"
                            f"Consultant: {_c_name} ({_c_email}) ID {cid}\n"
                            f"Job ID: {job_id}\n"
                            f"Job Type: {job_type}\n"
                            f"Customer: {customer_name or 'Unknown'}\n"
                            f"Item: {item_desc or 'N/A'}\n"
                            f"Error: {raw_err}"
                        )

                        print(f"[Worker] Job {job_id} type={job_type} FAILED: {raw_err}")

                        if job_type == "NEW_ORDER_ROW":
                            for jid in job_ids:
                                mark_job_failed(jid, raw_err, err_text)
                        else:
                            mark_job_failed(job_id, raw_err, err_text)

            finally:
                # Always clean up and release the consultant lock
                try:
                    if context is not None:
                        context.close()
                except Exception:
                    pass

                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass

                release_consultant(cid)


if __name__ == "__main__":
    main()