## change to better batching process for orders

# worker.py
import os
import json
import time

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
from playwright_automation.orders import process_order_batch

# How long to keep the browser open after the last job (seconds)
IDLE_GRACE_SECONDS = 90

# Order batching controls (tweak via env vars without code changes)
MAX_ORDER_ROWS_PER_BATCH = int(os.getenv("MAX_ORDER_ROWS_PER_BATCH", "25"))
ORDER_BATCH_GRACE_MS = int(os.getenv("ORDER_BATCH_GRACE_MS", "800"))  # brief window to catch rapid-fire items


def _missing_creds_message() -> str:
    return "Missing Intouch credentials. Please open Settings and save your Intouch username + password."


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _same_customer(a: dict, b: dict) -> bool:
    return _norm(a.get("First Name", "")) == _norm(b.get("First Name", "")) and _norm(a.get("Last Name", "")) == _norm(
        b.get("Last Name", "")
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
            mark_job_failed(job_id2, "Invalid payload_json for order row")
            continue

        if not _same_customer(first_payload, payload2):
            # Not the same customer — put it back and stop batching
            requeue_job(job_id2, "Queued")
            break

        out.append((job_id2, payload2))

    return out


def main():
    print(f"✅ Worker starting: {WORKER_ID}")

    with sync_playwright() as pw:
        while True:
            cid = claim_next_consultant()
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

                # If consultant has no creds, fail their queued jobs and move on
                if not username or not password:
                    msg = _missing_creds_message()

                    while True:
                        refresh_consultant_lock(cid)
                        claimed = claim_next_job_for_consultant(cid)
                        if not claimed:
                            break

                        job_id, _job_type, _payload_json = claimed
                        mark_job_failed(job_id, msg)

                    continue

                # Headless only if explicitly set to true
                HEADLESS = os.getenv("HEADLESS", "").lower() == "true"
                print("HEADLESS env:", os.getenv("HEADLESS"))
                print("HEADLESS resolved:", HEADLESS)

                browser = pw.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                context = browser.new_context()
                page = context.new_page()

                # Login once for this consultant session
                login_intouch(page, username, password)

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
                            create_customer_basic(page, payload)

                            full_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            mark_job_done(job_id, f"Customer {full_name} complete! ✅")

                        # -------------------------
                        # NEW_ORDER_ROW (✅ batching)
                        # -------------------------
                        elif job_type == "NEW_ORDER_ROW":
                            # Grab more queued order rows for the same customer (if any)
                            extra = _claim_more_order_rows_for_same_customer(cid, payload)

                            rows = [payload] + [p for (_jid, p) in extra]
                            job_ids = [job_id] + [jid for (jid, _p) in extra]

                            # Process one MyCustomers order containing all SKUs
                            process_order_batch(page, rows)

                            customer_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            for jid in job_ids:
                                mark_job_done(jid, f"Order for {customer_name} complete! ✅")

                        # -------------------------
                        # Unknown job type
                        # -------------------------
                        else:
                            mark_job_failed(job_id, f"Unknown job type: {job_type}")

                    except Exception as e:
                        mark_job_failed(job_id, str(e))

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