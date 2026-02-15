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
    mark_job_done,
    mark_job_failed,
    refresh_consultant_lock,
    release_consultant,
)

from playwright_automation.login import login_intouch
from playwright_automation.new_customer import open_mycustomers, create_customer_basic
#from playwright_automation.new_customer_address import add_customer_address
from playwright_automation.orders import process_order_batch

# How long to keep the browser open after the last job (seconds)
IDLE_GRACE_SECONDS = 90


def _missing_creds_message() -> str:
    return "Missing Intouch credentials. Please open Settings and save your Intouch username + password."


def main():
    print(f"✅ Worker starting: {WORKER_ID}")

    # Default to headless on Render
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

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

                    # move on to next consultant
                    continue

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
                            #add_customer_address(page, payload)

                            full_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            mark_job_done(job_id, f"Customer {full_name} complete! ✅")

                        # -------------------------
                        # NEW_ORDER_ROW (NO batching)
                        # -------------------------
                        elif job_type == "NEW_ORDER_ROW":
                            # Process ONE order row at a time
                            process_order_batch(page, [payload])

                            customer_name = f"{payload.get('First Name','')} {payload.get('Last Name','')}".strip()
                            mark_job_done(job_id, f"Order for {customer_name} complete! ✅")

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