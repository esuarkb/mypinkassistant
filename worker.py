# worker.py
import json
import time

from playwright.sync_api import sync_playwright

from auth_core import get_consultant_intouch_creds
from worker_queue import (
    WORKER_ID,
    claim_next_consultant,
    claim_next_job_for_consultant,
    mark_job_done,
    mark_job_failed,
    refresh_consultant_lock,
    release_consultant,
)

from playwright_automation.login import login_intouch
from playwright_automation.new_customer import open_mycustomers, create_customer_basic
from playwright_automation.new_customer_address import add_customer_address
from playwright_automation.orders import process_order_batch

# How long to keep the browser open after the last job (seconds)
IDLE_GRACE_SECONDS = 90

# Max order rows we’ll batch for a single customer in one go
MAX_ORDER_BATCH = 30


def _same_customer(a: dict, b: dict) -> bool:
    return (
        str(a.get("First Name", "")).strip() == str(b.get("First Name", "")).strip()
        and str(a.get("Last Name", "")).strip() == str(b.get("Last Name", "")).strip()
    )


def _missing_creds_message() -> str:
    return "Missing Intouch credentials. Please open Settings and save your Intouch username + password."


def main():
    print(f"✅ Worker starting: {WORKER_ID}")

    with sync_playwright() as pw:
        while True:
            cid = claim_next_consultant()
            if not cid:
                time.sleep(1)
                continue

            try:
                refresh_consultant_lock(cid)

                username, password = get_consultant_intouch_creds(cid)
                username = (username or "").strip()
                password = (password or "").strip()

                # ✅ NEW: if consultant has no creds, fail their queued jobs and move on
                if not username or not password:
                    msg = _missing_creds_message()

                    # Fail ALL queued jobs for this consultant so they don't block the queue
                    while True:
                        refresh_consultant_lock(cid)
                        claimed = claim_next_job_for_consultant(cid)
                        if not claimed:
                            break
                        job_id, job_type, _payload_json = claimed
                        mark_job_failed(job_id, msg)

                    # Release and move on
                    continue

                browser = pw.chromium.launch(headless=False)
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
                        # idle window
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
                            open_mycustomers(page)
                            create_customer_basic(page, payload)

                            # Address entry should be safe/no-op if missing
                            add_customer_address(page, payload)

                            full_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            mark_job_done(job_id, f"Customer {full_name} complete! ✅")


                        # -------------------------
                        # NEW_ORDER_ROW (batch by customer)
                        # -------------------------
                        elif job_type == "NEW_ORDER_ROW":
                            batch_job_ids = [job_id]
                            batch_rows = [payload]

                            # Try to pull additional queued rows for SAME customer
                            while len(batch_rows) < MAX_ORDER_BATCH:
                                nxt = claim_next_job_for_consultant(cid)
                                if not nxt:
                                    break

                                nxt_id, nxt_type, nxt_payload_json = nxt

                                # If we accidentally claimed another type, fail it clearly and stop batching
                                if nxt_type != "NEW_ORDER_ROW":
                                    mark_job_failed(
                                        nxt_id,
                                        "Worker batching limitation: unexpected job type during order batch.",
                                    )
                                    break

                                nxt_payload = json.loads(nxt_payload_json)

                                # If it’s a different customer, stop batching and fail this one (rare in normal use)
                                if not _same_customer(nxt_payload, batch_rows[0]):
                                    mark_job_failed(
                                        nxt_id,
                                        "Worker batching limitation: mixed customers in a single batch. Try again.",
                                    )
                                    break

                                batch_job_ids.append(nxt_id)
                                batch_rows.append(nxt_payload)

                            # Place the order for this batch
                            process_order_batch(page, batch_rows)

                            # If success, mark all rows done
                            for jid in batch_job_ids:
                                customer_name = f"{batch_rows[0].get('First Name','')} {batch_rows[0].get('Last Name','')}".strip()
                                mark_job_done(jid, f"Order for {customer_name} complete! ✅")

                        # -------------------------
                        # Unknown job type
                        # -------------------------
                        else:
                            mark_job_failed(job_id, f"Unknown job type: {job_type}")

                    except Exception as e:
                        mark_job_failed(job_id, str(e))

                # Close consultant session browser
                context.close()
                browser.close()

            finally:
                release_consultant(cid)


if __name__ == "__main__":
    main()
