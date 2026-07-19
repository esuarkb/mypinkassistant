## change to better batching process for orders

# worker.py
import os
import json
import time
import signal
import requests
import traceback
from dotenv import load_dotenv
load_dotenv(override=True)

from datetime import datetime, timezone
from pathlib import Path
from db import connect, is_postgres, get_system_setting

from emailer import send_wrong_credentials_email, send_login_failure_alert_email, send_sku_not_found_email
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

    # Mirror every worker alert as a web push (2026-07-12): this is the
    # worker's LOCAL copy of send_failure_text (it does not import alerts.py),
    # so the push mirror lives here too. Push fires BEFORE the SMS cooldown
    # check — push has no cost/window, so it should never be suppressed by
    # the SMS-specific cooldown. Push problems must never break the SMS path.
    try:
        from push_notify import send_push_to_admins
        send_push_to_admins("🚨 MPA Failure", message, url="/admin")
    except Exception as _pe:
        print("[Worker] Push mirror failed:", _pe)

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


_last_report_alert_time = 0.0
_REPORT_ALERT_COOLDOWN_SECONDS = 6 * 3600


def _alert_report_fetch_errors(cid: int, summary: dict) -> None:
    """
    Report-sync fetches degraded (error ≠ empty — see report_sync._foreposts_get).
    The job still completes; this sends ONE EMAIL naming the failing report(s).
    EMAIL-ONLY since 2026-07-12 (Brian's call after push alerts shipped):
    degraded reports are stale-data housekeeping, not wake-the-Watch urgent —
    no push, no SMS. 6h cooldown per worker process so a global FOReports
    outage during the nightly sweep doesn't fire one email per consultant.
    """
    global _last_report_alert_time
    errs = (summary or {}).get("fetch_errors") or []
    if not errs:
        return
    print(f"[ReportSync] fetch errors for consultant_id={cid}: {errs}")
    now = time.time()
    if now - _last_report_alert_time < _REPORT_ALERT_COOLDOWN_SECONDS:
        print("[ReportSync] fetch-error email suppressed (6h cooldown)")
        return
    _last_report_alert_time = now
    from emailer import send_admin_alert_email
    send_admin_alert_email(
        "MPA Report Sync Degraded",
        "⚠️ MyPinkAssistant Report Sync Degraded\n\n"
        f"Consultant ID: {cid}\n"
        "Job completed, but these report fetches FAILED (team data may be stale):\n"
        + "\n".join(f"• {e}" for e in errs[:6])
    )


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

from playwright_automation import step_log
from playwright_automation.login import login_intouch
from playwright_automation.new_customer import create_customer_basic
from playwright_automation.orders import process_order_batch, SkuNotCdsEligible
from playwright_automation.inventory_import import import_inventory_orders
from inventory_import_store import ensure_import_table
from playwright_automation.order_history_import import fetch_order_history
from playwright_automation.order_detail_sync import fetch_order_details
from order_history_import_store import import_order_history, update_order_item_quantities
from playwright_automation.customer_api_import import fetch_customer_list
from customer_api_import_store import import_customers_from_api
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


def _load_predecessor_map() -> dict[str, str]:
    """Return {new_sku: old_sku} for SKUs that have a known predecessor in the catalog."""
    import csv as _csv
    catalog_path = Path(__file__).parent / "catalog" / "en.csv"
    result: dict[str, str] = {}
    if not catalog_path.exists():
        return result
    try:
        with open(catalog_path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                pred = (row.get("predecessor_sku") or "").strip()
                if pred:
                    result[row["sku"].strip()] = pred
    except Exception:
        pass
    return result

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
    """Return True if 2+ established consultants have failed login in the last 30 minutes.
    Excludes consultants who haven't completed initial sync — their failures are likely
    bad credentials entered at signup, not an InTouch outage."""
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
              AND initial_sync_completed = TRUE
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


_shutdown = False

def _handle_sigterm(signum, frame):
    global _shutdown
    print("[Worker] SIGTERM received — finishing current job then exiting")
    _shutdown = True

signal.signal(signal.SIGTERM, _handle_sigterm)


def main():
    print(f"✅ Worker starting: {WORKER_ID}")
    #send_failure_text("✅ Test alert from MyPinkAssistant worker")

    with sync_playwright() as pw:
        while not _shutdown:
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

            # Claim-time scale-up recheck: this worker is about to go busy on
            # one consultant — if OTHERS are still waiting, bring up more
            # instances now. Complements the insert_job hook (which can miss:
            # API blip, cooldown), so a backlog self-heals on every claim
            # instead of waiting for the next job insert.
            try:
                from autoscaler import check_and_scale_up, check_and_scale_nightly
                check_and_scale_up()
                check_and_scale_nightly()
            except Exception as _ae:
                print(f"[Autoscaler] claim-time recheck error: {_ae}")

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
                    # login_intouch has step markers too — say which login step died
                    _login_step = step_log.last_step()
                    if _login_step:
                        err = f"{err} [died at {_login_step}]"

                    if "invalid username or password" in err.lower() or "missing intouch credentials" in err.lower():
                        friendly = (
                            "InTouch login failed. Please check your InTouch username/password in Settings "
                            "and try again."
                        )
                    else:
                        friendly = "Something unexpected happened. Please try again."

                    # Silently retry transient login errors once before failing.
                    # Login runs before any job is claimed for this consultant, so
                    # there is no job to requeue — gate the retry on the consultant's
                    # consecutive_login_failures instead and leave the jobs queued.
                    # (A successful login resets the counter via _reset_login_failures.)
                    _transient = ("ERR_ABORTED", "net::", "ERR_CONNECTION", "ERR_TIMED_OUT",
                                  "ERR_NAME_NOT_RESOLVED", "is interrupted", "Timeout")
                    if any(s in err for s in _transient):
                        try:
                            _ln_conn = connect()
                            _ln_cur = _ln_conn.cursor()
                            _ln_cur.execute(
                                f"SELECT consecutive_login_failures FROM consultants WHERE id={PH_W}",
                                (cid,),
                            )
                            _ln_row = _ln_cur.fetchone()
                            if _ln_row is None:
                                _ln_failures = 99
                            else:
                                _ln_val = _ln_row.get("consecutive_login_failures") if isinstance(_ln_row, dict) else _ln_row[0]
                                _ln_failures = int(_ln_val or 0)
                            _ln_conn.close()
                        except Exception:
                            _ln_failures = 99
                        if _ln_failures == 0:
                            _record_login_failure(cid)
                            print(f"[Worker] Login transient error for consultant_id={cid} — leaving jobs queued to retry next pass.")
                            continue  # finally block closes browser + releases lock; jobs stay queued

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
                            admin_email = "support@mypinkassistant.com"
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
                    if _shutdown:
                        break

                    refresh_consultant_lock(cid)

                    claimed = claim_next_job_for_consultant(cid)
                    if not claimed:
                        if time.time() - last_job_time > IDLE_GRACE_SECONDS:
                            break
                        time.sleep(0.5)
                        continue

                    job_id, job_type, payload_json = claimed
                    last_job_time = time.time()
                    step_log.set_job(job_id)  # tag step lines + reset last-step for this job

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
                            fill_failures = []
                            try:
                                fill_failures = process_order_batch(page, rows) or []
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
                            if fill_failures:
                                # discount/tax field could not be filled — order saved
                                # WITHOUT it; never silently drop (2026-07-13 bug class)
                                _ff = " and ".join(fill_failures)
                                done_msg += f" ⚠️ The {_ff} could not be applied — please add it to the order in MyCustomers."
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
                            mark_job_done(job_id, "Customer import complete!")

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
                        # IMPORT_ORDER_HISTORY
                        # -------------------------
                        elif job_type == "IMPORT_ORDER_HISTORY":
                            raw_orders, _csrf = fetch_order_history(page)
                            print(f"[ImportOrderHistory] fetch returned {len(raw_orders)} orders")
                            if raw_orders:
                                print(f"[ImportOrderHistory] sample order keys: {list(raw_orders[0].keys())[:6]}")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                summary = import_order_history(cur, consultant_id=cid, raw_orders=raw_orders)
                                conn.commit()
                            finally:
                                conn.close()
                            mark_job_done(job_id, "Order history import complete.")

                        # -------------------------
                        # IMPORT_CUSTOMERS_API
                        # -------------------------
                        elif job_type == "IMPORT_CUSTOMERS_API":
                            raw_customers = fetch_customer_list(page)
                            print(f"[CustomerApiImport] fetch returned {len(raw_customers)} customers")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                summary = import_customers_from_api(cur, consultant_id=cid, raw_customers=raw_customers)
                                conn.commit()
                            finally:
                                conn.close()
                            mark_job_done(job_id, "Customer import complete!")

                        # -------------------------
                        # INITIAL_SYNC (onboarding: customers + orders, one login)
                        # -------------------------
                        elif job_type == "INITIAL_SYNC":
                            # Customers
                            raw_customers = fetch_customer_list(page)
                            print(f"[InitialSync] fetch returned {len(raw_customers)} customers")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                _cust_summary = import_customers_from_api(cur, consultant_id=cid, raw_customers=raw_customers)
                                conn.commit()
                            finally:
                                conn.close()
                            # Orders
                            raw_orders, _ = fetch_order_history(page)
                            print(f"[InitialSync] fetch returned {len(raw_orders)} orders")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                _ord_summary = import_order_history(cur, consultant_id=cid, raw_orders=raw_orders)
                                conn.commit()
                            finally:
                                conn.close()
                            _cust_count = _cust_summary.get("inserted", 0) + _cust_summary.get("updated", 0)
                            _ord_count = _ord_summary.get("inserted", 0)
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                cur.execute(f"SELECT COUNT(*) FROM customers WHERE consultant_id={PH_W} AND source_status='active'", (cid,))
                                _active_count = (cur.fetchone() or [0])[0]
                            finally:
                                conn.close()
                            mark_job_done(job_id, f"Customer & order import complete! {_cust_count} customers ({_active_count} active), {_ord_count} orders imported.")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                cur.execute(
                                    f"UPDATE consultants SET initial_sync_completed = TRUE WHERE id = {PH_W}",
                                    (cid,),
                                )
                                conn.commit()
                            finally:
                                conn.close()

                        # -------------------------
                        # FULL_SYNC (nightly: customers + orders + inventory, one login)
                        # -------------------------
                        elif job_type == "FULL_SYNC":
                            # Customers
                            raw_customers = fetch_customer_list(page)
                            print(f"[FullSync] fetch returned {len(raw_customers)} customers")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                import_customers_from_api(cur, consultant_id=cid, raw_customers=raw_customers)
                                conn.commit()
                            finally:
                                conn.close()
                            # Orders
                            raw_orders, _csrf_token = fetch_order_history(page)
                            print(f"[FullSync] fetch returned {len(raw_orders)} orders")
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                import_order_history(cur, consultant_id=cid, raw_orders=raw_orders)
                                conn.commit()
                            finally:
                                conn.close()
                            # Order detail sync — 7-day window to catch recent quantity changes
                            _non_archived = [
                                (o["Id"], (o.get("OrderedDate_f__c") or o.get("OrderedDate") or "")[:10])
                                for o in raw_orders if o.get("Id") and not o.get("IsArchived_cb__c")
                            ]
                            if _non_archived and _csrf_token:
                                _detail_map = fetch_order_details(page, _non_archived, _csrf_token, days=7)
                                if _detail_map:
                                    conn = connect()
                                    try:
                                        cur = conn.cursor()
                                        update_order_item_quantities(cur, consultant_id=cid, order_details_map=_detail_map)
                                        conn.commit()
                                    finally:
                                        conn.close()
                            # Reports (team data, challenge tracking, registrations)
                            # Runs before inventory — inventory visits applications.marykayintouch.com
                            # via a different auth path which would contaminate the FOReports session
                            try:
                                from playwright_automation.report_sync import run_report_sync as _run_reports
                                from db import is_postgres as _isp
                                _rph = "%s" if _isp() else "?"
                                conn = connect()
                                try:
                                    cur = conn.cursor()
                                    _rs = _run_reports(page, cur, cid, ph=_rph)
                                    conn.commit()
                                finally:
                                    conn.close()
                                print(f"[FullSync] Report sync: {_rs}")
                                _alert_report_fetch_errors(cid, _rs)
                            except Exception as _re:
                                print(f"[FullSync] Report sync failed (non-fatal): {_re}")
                            # Inventory last (skipped for accounts sharing InTouch creds)
                            if not payload.get("skip_inventory"):
                                date_range = payload.get("date_range", "days90")
                                seed_only = bool(payload.get("seed_only", False))
                                import_inventory_orders(
                                    page,
                                    consultant_id=cid,
                                    username=username,
                                    password=password,
                                    date_range=date_range,
                                    seed_only=seed_only,
                                )
                            mark_job_done(job_id, "Nightly sync complete.")

                        # -------------------------
                        # PCP_SYNC (queued at onboarding and quarterly)
                        # -------------------------
                        elif job_type == "PCP_SYNC":
                            from scrape_pcp import scrape_enrolled as _pcp_scrape, save_to_db as _pcp_save, current_quarter as _pcp_quarter
                            _pcp_enrolled = 0
                            _pcp_msg = "0 enrolled customers."
                            try:
                                enrolled = _pcp_scrape(page, username, password, skip_login=True)
                                if enrolled:
                                    conn = connect()
                                    try:
                                        cur = conn.cursor()
                                        _pcp_save(cur, enrolled, cid, _pcp_quarter())
                                        conn.commit()
                                    finally:
                                        conn.close()
                                    _pcp_enrolled = len(enrolled)
                                    _pcp_msg = f"{_pcp_enrolled} enrolled customers."
                            except RuntimeError:
                                _pcp_msg = "T&C not yet accepted."
                            except Exception as _pcp_err:
                                _err_str = str(_pcp_err)
                                if "TermsAndConditions" in _err_str or "Alerts.aspx" in _err_str:
                                    _pcp_msg = "T&C not yet accepted."
                                else:
                                    _pcp_msg = f"PCP sync failed — {_pcp_err}"
                                    print(f"[PcpSync] {_pcp_msg}")
                            mark_job_done(job_id, _pcp_msg)

                        # -------------------------
                        # REPORT_SYNC (order detail backfill + team/unit member data sync)
                        # -------------------------
                        elif job_type == "REPORT_SYNC":
                            # Order detail sync — full backfill of all non-archived orders
                            try:
                                _od_orders, _od_csrf = fetch_order_history(page)
                                _non_archived = [
                                    (o["Id"], (o.get("OrderedDate_f__c") or o.get("OrderedDate") or "")[:10])
                                    for o in _od_orders if o.get("Id") and not o.get("IsArchived_cb__c")
                                ]
                                if _non_archived and _od_csrf:
                                    print(f"[ReportSync] starting order detail sync for {len(_non_archived)} orders")
                                    _detail_map = fetch_order_details(page, _non_archived, _od_csrf)
                                    if _detail_map:
                                        conn = connect()
                                        try:
                                            cur = conn.cursor()
                                            update_order_item_quantities(cur, consultant_id=cid, order_details_map=_detail_map)
                                            conn.commit()
                                        finally:
                                            conn.close()
                            except Exception as _od_err:
                                print(f"[ReportSync] Order detail sync failed (non-fatal): {_od_err}")
                            # Team/unit member data sync
                            from playwright_automation.report_sync import run_report_sync
                            _ph = "%s" if is_postgres() else "?"
                            conn = connect()
                            try:
                                cur = conn.cursor()
                                summary = run_report_sync(page, cur, cid, ph=_ph)
                                conn.commit()
                            finally:
                                conn.close()
                            _alert_report_fetch_errors(cid, summary)
                            _member_count = summary["members"]
                            mark_job_done(job_id, f"{_member_count} unit members." if _member_count else "0 unit members.")

                        # -------------------------
                        # Unknown job type
                        # -------------------------
                        else:
                            mark_job_failed(job_id, "Something unexpected happened. Please refresh the page and try again.")

                    except _RequeueSilently:
                        pass  # jobs already requeued above; skip alert + mark_failed

                    except Exception as e:
                        raw_err = str(e)
                        # Step-level context (playwright_automation/step_log.py):
                        # name the exact script step that was running so the jobs
                        # table + SMS alert say WHERE the script died, not just
                        # a bare locator traceback
                        _last_step = step_log.last_step()
                        if _last_step:
                            raw_err = f"{raw_err} [died at {_last_step}]"

                        # Auto-retry transient InTouch timeouts (up to 3 attempts total)
                        # Exclude post-save/post-confirm timeouts — job already completed in InTouch
                        if "Timeout" in raw_err and "Post-save" not in raw_err and "Post-confirm" not in raw_err:
                            try:
                                _rt_conn = connect()
                                _rt_cur = _rt_conn.cursor()
                                _first_jid = job_ids[0] if job_type == "NEW_ORDER_ROW" else job_id
                                _rt_cur.execute(f"SELECT attempts FROM jobs WHERE id={PH_W}", (_first_jid,))
                                _att_row = _rt_cur.fetchone()
                                _attempts = int(_att_row[0]) if _att_row else 99
                                _rt_conn.close()
                            except Exception:
                                _attempts = 99

                            if _attempts <= 2:
                                _retry_ids = job_ids if job_type == "NEW_ORDER_ROW" else [job_id]
                                print(f"[Worker] Timeout on job(s) {_retry_ids} (attempt {_attempts}/3) — requeueing for retry.")
                                for jid in _retry_ids:
                                    requeue_job(jid, "Queued")
                                continue

                            # After 3 failed attempts, try predecessor SKU fallback for orders.
                            # Only swap the specific failing SKU (extracted from the error message)
                            # so other jobs in the batch retain their swap slot for future rounds.
                            if job_type == "NEW_ORDER_ROW":
                                _pred_map = _load_predecessor_map()
                                if _pred_map:
                                    import re as _re
                                    _sku_match = _re.search(r'locator\("text=(\d+)"\)', raw_err)
                                    _failing_sku = _sku_match.group(1) if _sku_match else None
                                    _sw_jobs: list[tuple[int, str]] = []
                                    _swapped_any = False
                                    try:
                                        _sw_conn = connect()
                                        _sw_cur = _sw_conn.cursor()
                                        for _jid in job_ids:
                                            _sw_cur.execute(f"SELECT payload_json FROM jobs WHERE id={PH_W}", (_jid,))
                                            _prow = _sw_cur.fetchone()
                                            _pjson = (_prow[0] if _prow and not hasattr(_prow, "get") else (_prow.get("payload_json") if _prow else "{}")) or "{}"
                                            _p = json.loads(_pjson)
                                            _cur_sku = (_p.get("SKU") or "").strip()
                                            # Only swap the job whose SKU matches the failing SKU
                                            if _cur_sku == _failing_sku and not _p.get("_sku_swapped"):
                                                _old_sku = _pred_map.get(_cur_sku)
                                                if _old_sku:
                                                    _p["SKU"] = _old_sku
                                                    _p["_sku_swapped"] = True
                                                    _swapped_any = True
                                                    print(f"[Worker] Predecessor fallback: {_cur_sku} → {_old_sku} on job {_jid}")
                                            _sw_jobs.append((_jid, json.dumps(_p)))
                                        if _swapped_any:
                                            for _jid, _new_pjson in _sw_jobs:
                                                if is_postgres():
                                                    _sw_cur.execute(f"UPDATE jobs SET status='queued', error='', status_msg='Retrying with predecessor SKU…', attempts=0, claimed_by=NULL, claimed_at=NULL, started_at=NULL, payload_json={PH_W} WHERE id={PH_W}", (_new_pjson, _jid))
                                                else:
                                                    _sw_cur.execute(f"UPDATE jobs SET status='queued', error='', status_msg='Retrying with predecessor SKU…', attempts=0, claimed_by='', claimed_at='', started_at='', payload_json={PH_W} WHERE id={PH_W}", (_new_pjson, _jid))
                                            _sw_conn.commit()
                                            print(f"[Worker] Predecessor fallback — requeued {len(_sw_jobs)} job(s)")
                                            continue

                                        elif _failing_sku:
                                            # No predecessor. Fail every job with the bad SKU,
                                            # requeue the rest so the order goes through without it.
                                            _bad_jids = [_jid for _jid, _pjson in _sw_jobs
                                                         if (json.loads(_pjson).get("SKU") or "").strip() == _failing_sku]
                                            _good_jids = [_jid for _jid, _pjson in _sw_jobs
                                                          if (json.loads(_pjson).get("SKU") or "").strip() != _failing_sku]
                                            if _bad_jids:
                                                # Look up product name from catalog CSV (also tells us
                                                # whether the SKU is a current product — hoisted above the
                                                # user message so the wording can be honest, 2026-07-19)
                                                _prod_name = _failing_sku
                                                _in_catalog = False
                                                try:
                                                    import csv as _csv
                                                    _cat_path = Path(__file__).resolve().parent / "catalog" / "en.csv"
                                                    with open(_cat_path, newline="") as _cf:
                                                        for _crow in _csv.reader(_cf):
                                                            if _crow and _crow[0].strip() == _failing_sku:
                                                                _prod_name = _crow[1].strip() if len(_crow) > 1 else _failing_sku
                                                                _in_catalog = True
                                                                break
                                                except Exception:
                                                    pass
                                                # SKU in our catalog = current product (catalog mirrors the
                                                # OPOS scrape; discontinued SKUs fall out of it) → the search
                                                # miss was transient InTouch flakiness or MyCustomers index
                                                # lag, NOT discontinuation. Only claim "discontinued" when
                                                # the SKU is truly absent from the catalog.
                                                if _in_catalog:
                                                    _bad_user_msg = (
                                                        f"SKU {_failing_sku} couldn't be added right now — "
                                                        f"please try again in a few minutes."
                                                    )
                                                else:
                                                    _bad_user_msg = (
                                                        f"SKU {_failing_sku} couldn't be found in MyCustomers "
                                                        f"and may be discontinued."
                                                    )
                                                for _jid in _bad_jids:
                                                    mark_job_failed(_jid, raw_err, _bad_user_msg)
                                                if _good_jids:
                                                    for _jid in _good_jids:
                                                        if is_postgres():
                                                            _sw_cur.execute(f"UPDATE jobs SET status='queued', error='', status_msg='Requeued after removing unavailable SKU', attempts=0, claimed_by=NULL, claimed_at=NULL, started_at=NULL WHERE id={PH_W}", (_jid,))
                                                        else:
                                                            _sw_cur.execute(f"UPDATE jobs SET status='queued', error='', status_msg='Requeued after removing unavailable SKU', attempts=0, claimed_by='', claimed_at='', started_at='' WHERE id={PH_W}", (_jid,))
                                                    _sw_conn.commit()
                                                    print(f"[Worker] SKU {_failing_sku} not found — failed {len(_bad_jids)} job(s), requeued {len(_good_jids)} job(s)")
                                                # Email admin (_prod_name from catalog lookup above)
                                                try:
                                                    _admin_email = "support@mypinkassistant.com"
                                                    if _admin_email:
                                                        _cust_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                                                        send_sku_not_found_email(
                                                            to_email=_admin_email,
                                                            consultant_name=_c_name,
                                                            consultant_email=_c_email,
                                                            consultant_id=cid,
                                                            sku=_failing_sku,
                                                            product_name=_prod_name,
                                                            customer_name=_cust_name,
                                                            requeued_count=len(_good_jids),
                                                        )
                                                except Exception as _mail_err:
                                                    print(f"[Worker] SKU not found email failed: {_mail_err}")
                                                # Write a local_only record so this sale persists through nightly sync
                                                try:
                                                    _ls_conn = connect()
                                                    _ls_cur = _ls_conn.cursor()
                                                    PH_LS = "%s" if is_postgres() else "?"
                                                    _ls_first = payload.get("First Name", "").strip()
                                                    _ls_last = payload.get("Last Name", "").strip()
                                                    _ls_cur.execute(
                                                        f"""SELECT id FROM customers
                                                            WHERE consultant_id = {PH_LS}
                                                              AND LOWER(first_name) = LOWER({PH_LS})
                                                              AND LOWER(last_name) = LOWER({PH_LS})
                                                            ORDER BY id DESC LIMIT 1""",
                                                        (cid, _ls_first, _ls_last),
                                                    )
                                                    _ls_cust_row = _ls_cur.fetchone()
                                                    if _ls_cust_row:
                                                        _ls_customer_id = int(_ls_cust_row[0] if not isinstance(_ls_cust_row, dict) else _ls_cust_row["id"])
                                                        _ls_price = 0.0
                                                        try:
                                                            import csv as _csv_ls
                                                            with open(Path(__file__).resolve().parent / "catalog" / "en.csv", newline="") as _cf_ls:
                                                                for _crow_ls in _csv_ls.reader(_cf_ls):
                                                                    if _crow_ls and _crow_ls[0].strip() == _failing_sku:
                                                                        try:
                                                                            _ls_price = float(_crow_ls[2]) if len(_crow_ls) > 2 and _crow_ls[2] else 0.0
                                                                        except Exception:
                                                                            pass
                                                                        break
                                                        except Exception:
                                                            pass
                                                        _ls_today = datetime.now(timezone.utc).date().isoformat()
                                                        if is_postgres():
                                                            _ls_cur.execute(
                                                                f"""INSERT INTO orders
                                                                    (consultant_id, customer_id, order_date, total, source, intouch_order_id, discount_amount, tax_amount, created_at)
                                                                    VALUES ({PH_LS},{PH_LS},{PH_LS},{PH_LS},'local_only',NULL,0,0,NOW())
                                                                    RETURNING id""",
                                                                (cid, _ls_customer_id, _ls_today, _ls_price),
                                                            )
                                                            _ls_order_id = int(_ls_cur.fetchone()[0])
                                                        else:
                                                            _ls_cur.execute(
                                                                f"""INSERT INTO orders
                                                                    (consultant_id, customer_id, order_date, total, source, intouch_order_id, discount_amount, tax_amount, created_at)
                                                                    VALUES ({PH_LS},{PH_LS},{PH_LS},{PH_LS},'local_only',NULL,0,0,datetime('now'))""",
                                                                (cid, _ls_customer_id, _ls_today, _ls_price),
                                                            )
                                                            _ls_order_id = int(_ls_cur.lastrowid)
                                                        if is_postgres():
                                                            _ls_cur.execute(
                                                                """INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
                                                                   VALUES (%s,%s,%s,%s,1,0,NOW())""",
                                                                (_ls_order_id, _failing_sku, _prod_name, _ls_price),
                                                            )
                                                        else:
                                                            _ls_cur.execute(
                                                                """INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity, discount_amount, created_at)
                                                                   VALUES (?,?,?,?,1,0,datetime('now'))""",
                                                                (_ls_order_id, _failing_sku, _prod_name, _ls_price),
                                                            )
                                                        _ls_conn.commit()
                                                        print(f"[Worker] local_only record written: SKU={_failing_sku} customer_id={_ls_customer_id} order_id={_ls_order_id}")
                                                    else:
                                                        print(f"[Worker] local_only: customer not found for '{_ls_first} {_ls_last}', skipping")
                                                except Exception as _ls_err:
                                                    print(f"[Worker] local_only write failed: {_ls_err}")
                                                finally:
                                                    try:
                                                        _ls_conn.close()
                                                    except Exception:
                                                        pass
                                                continue
                                    except Exception as _sw_err:
                                        print(f"[Worker] Predecessor swap error: {_sw_err}")
                                    finally:
                                        try:
                                            _sw_conn.close()
                                        except Exception:
                                            pass

                        # Default user-facing message should be safe and non-technical
                        err_text = "Something went wrong submitting this. Please try again."

                        if raw_err.startswith("InTouch:"):
                            err_text = raw_err

                        elif "Post-save" in raw_err:
                            err_text = (
                                "Customer was saved to MyCustomers, but we couldn't confirm it completed. "
                                "Please verify in MyCustomers before trying again."
                            )

                        elif "Post-confirm" in raw_err:
                            err_text = (
                                "Order was placed in MyCustomers, but we couldn't confirm it completed. "
                                "Please verify in MyCustomers before trying again."
                            )

                        elif "Timeout" in raw_err and "New Customer" in raw_err:
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

                        elif "Change To Processed" in raw_err:
                            err_text = (
                                "Your order was saved in MyCustomers but couldn't be confirmed as processed. "
                                "Please check MyCustomers to verify the order is there before trying again."
                            )

                        elif "Add to Bag" in raw_err:
                            err_text = "Something went wrong adding an item to the bag. Please verify the order in MyCustomers."

                        elif "Invalid payload_json" in raw_err or "Unknown job type" in raw_err:
                            err_text = "Something unexpected happened. Please try again."

                        # Auto-retry transient InTouch network errors on FULL_SYNC (one extra attempt)
                        if job_type == "FULL_SYNC" and any(s in raw_err for s in ("ERR_ABORTED", "net::", "ERR_CONNECTION", "ERR_TIMED_OUT", "ERR_NAME_NOT_RESOLVED")):
                            try:
                                _fs_conn = connect()
                                _fs_cur = _fs_conn.cursor()
                                _fs_cur.execute(f"SELECT attempts FROM jobs WHERE id={PH_W}", (job_id,))
                                _fs_row = _fs_cur.fetchone()
                                _fs_attempts = int(_fs_row[0]) if _fs_row else 99
                                _fs_conn.close()
                            except Exception:
                                _fs_attempts = 99
                            if _fs_attempts <= 1:
                                print(f"[Worker] FULL_SYNC job {job_id} transient network error (attempt {_fs_attempts}) — requeueing for retry.")
                                requeue_job(job_id, "Queued")
                                continue

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
                step_log.clear()
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

                try:
                    from autoscaler import check_and_scale_down
                    check_and_scale_down()
                except Exception as _ae:
                    print(f"[Autoscaler] scale-down hook error: {_ae}")


if __name__ == "__main__":
    main()