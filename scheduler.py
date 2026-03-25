# scheduler.py
#
# Queues nightly IMPORT_CUSTOMERS and IMPORT_INVENTORY_ORDERS jobs
# for every active consultant with InTouch credentials.
#
# Run via Render Cron Job at 0 9 * * * (3 AM CST / 9 AM UTC).
# Safe to run manually for testing.

import os
from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres
from mk_chat_core import insert_job

PH = "%s" if is_postgres() else "?"

# Suppress scheduling for consultants with this many consecutive login failures
LOGIN_FAILURE_LIMIT = 2


def _has_pending_job(cur, consultant_id: int, job_type: str) -> bool:
    """Return True if a queued or running job of this type already exists."""
    cur.execute(
        f"""
        SELECT 1 FROM jobs
        WHERE consultant_id = {PH}
          AND type = {PH}
          AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (consultant_id, job_type),
    )
    return cur.fetchone() is not None


def _has_inventory_watermark(cur, consultant_id: int) -> bool:
    """Return True if the consultant has at least one import history record."""
    cur.execute(
        f"SELECT 1 FROM inventory_intouch_imports WHERE consultant_id = {PH} LIMIT 1",
        (consultant_id,),
    )
    return cur.fetchone() is not None


def run() -> None:
    conn = connect()
    cur = conn.cursor()

    try:
        cur.execute(
            f"""
            SELECT id, email, consecutive_login_failures
            FROM consultants
            WHERE billing_status IN ('active', 'trialing')
              AND intouch_username != ''
              AND intouch_password_enc != ''
            """
        )
        consultants = cur.fetchall()

        queued_customers = 0
        queued_inventory = 0
        skipped_failures = 0
        skipped_pending = 0

        for row in consultants:
            if isinstance(row, dict):
                cid = row["id"]
                email = row["email"]
                failures = int(row.get("consecutive_login_failures") or 0)
            else:
                cid, email, failures = row[0], row[1], int(row[2] or 0)

            # Skip consultants with too many consecutive login failures
            if failures >= LOGIN_FAILURE_LIMIT:
                print(f"[Scheduler] Skipping {email} — {failures} consecutive login failure(s)")
                skipped_failures += 1
                continue

            # Queue IMPORT_CUSTOMERS if not already pending
            if not _has_pending_job(cur, cid, "IMPORT_CUSTOMERS"):
                insert_job("IMPORT_CUSTOMERS", {}, consultant_id=cid)
                queued_customers += 1
            else:
                skipped_pending += 1

            # Queue IMPORT_INVENTORY_ORDERS if not already pending
            if not _has_pending_job(cur, cid, "IMPORT_INVENTORY_ORDERS"):
                if _has_inventory_watermark(cur, cid):
                    # Normal nightly import — only new orders
                    insert_job(
                        "IMPORT_INVENTORY_ORDERS",
                        {"date_range": "days90"},
                        consultant_id=cid,
                    )
                else:
                    # First run — set watermark only, no SKUs added
                    insert_job(
                        "IMPORT_INVENTORY_ORDERS",
                        {"date_range": "lastTwelveMonths", "seed_only": True},
                        consultant_id=cid,
                    )
                queued_inventory += 1
            else:
                skipped_pending += 1

        print(
            f"[Scheduler] Done — "
            f"queued {queued_customers} customer import(s), "
            f"{queued_inventory} inventory job(s), "
            f"skipped {skipped_failures} (login failures), "
            f"skipped {skipped_pending} (already pending)"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    run()
