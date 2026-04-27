# scheduler.py
#
# Queues nightly FULL_SYNC jobs for every active consultant with InTouch credentials.
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

# Consultant emails that should never get IMPORT_INVENTORY_ORDERS queued.
# briankrause is a screenshot/test account that shares InTouch credentials
# with akrause.marykay@gmail.com — importing for both would double inventory.
SKIP_INVENTORY_IMPORT = {"briankrause@gmail.com"}


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

        queued = 0
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

            if _has_pending_job(cur, cid, "FULL_SYNC"):
                skipped_pending += 1
                continue

            if email in SKIP_INVENTORY_IMPORT:
                print(f"[Scheduler] Skipping inventory for {email} (screenshot/test account)")
                inventory_payload = {"skip_inventory": True}
            elif _has_inventory_watermark(cur, cid):
                inventory_payload = {"date_range": "days90"}
            else:
                inventory_payload = {"date_range": "lastTwelveMonths", "seed_only": True}

            insert_job("FULL_SYNC", {"source": "scheduler", **inventory_payload}, consultant_id=cid, priority=-1)
            queued += 1

        print(
            f"[Scheduler] Done — "
            f"queued {queued} FULL_SYNC job(s), "
            f"skipped {skipped_failures} (login failures), "
            f"skipped {skipped_pending} (already pending)"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    run()
