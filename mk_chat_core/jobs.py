"""Job-queue helpers: insert_job (with autoscaler hook) and the first-sync
queueing that runs after billing activation.
"""
import json

from db import is_postgres

from .dbutil import PH, db_connect


def insert_job(job_type: str, payload: dict, consultant_id: int, priority: int = 0) -> int:
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO jobs (type, payload_json, status, consultant_id, priority)
                VALUES ({PH}, {PH}, 'queued', {PH}, {PH})
                RETURNING id
                """,
                (job_type, json.dumps(payload), int(consultant_id), priority),
            )
            row = cur.fetchone()
            job_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cur.execute(
                f"INSERT INTO jobs (type, payload_json, status, consultant_id, priority) VALUES ({PH}, {PH}, 'queued', {PH}, {PH})",
                (job_type, json.dumps(payload), int(consultant_id), priority),
            )
            job_id = cur.lastrowid

        conn.commit()

        try:
            # REALTIME_TYPES lives in autoscaler.py — the one canonical list
            from autoscaler import REALTIME_TYPES, check_and_scale_up
            if job_type in REALTIME_TYPES:
                check_and_scale_up()
        except Exception as _ae:
            print(f"[Autoscaler] scale-up hook error: {_ae}")

        return int(job_id)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def maybe_queue_initial_customer_import(cur, consultant_id: int) -> bool:
    """
    Queue the first silent MyCustomers import after successful billing activation.
    Returns True if a job was queued, else False.
    """
    cur.execute(
        f"""
        SELECT
            billing_status,
            intouch_username,
            intouch_password_enc,
            initial_sync_completed
        FROM consultants
        WHERE id = {PH}
        LIMIT 1
        """,
        (consultant_id,),
    )
    row = cur.fetchone()
    if not row:
        return False

    if isinstance(row, dict):
        billing_status = (row.get("billing_status") or "").strip().lower()
        intouch_username = (row.get("intouch_username") or "").strip()
        intouch_password_enc = (row.get("intouch_password_enc") or "").strip()
        sync_completed = bool(row.get("initial_sync_completed"))
    else:
        billing_status = (row[0] or "").strip().lower()
        intouch_username = (row[1] or "").strip()
        intouch_password_enc = (row[2] or "").strip()
        sync_completed = bool(row[3])

    if billing_status not in ("active", "trialing"):
        return False

    if sync_completed:
        return False

    if not intouch_username or not intouch_password_enc:
        return False

    # Check the jobs table directly — don't queue if one is already pending or running
    cur.execute(
        f"""
        SELECT 1 FROM jobs
        WHERE consultant_id = {PH}
          AND type = 'INITIAL_SYNC'
          AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (consultant_id,),
    )
    if cur.fetchone():
        return False

    insert_job(
        "INITIAL_SYNC",
        {},
        consultant_id=consultant_id,
        priority=1,
    )

    # Queue PCP sync to run right after INITIAL_SYNC (priority=0 so INITIAL_SYNC always goes first)
    cur.execute(
        f"""
        SELECT 1 FROM jobs
        WHERE consultant_id = {PH}
          AND type = 'PCP_SYNC'
          AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (consultant_id,),
    )
    if not cur.fetchone():
        insert_job("PCP_SYNC", {}, consultant_id=consultant_id, priority=0)

    # Queue REPORT_SYNC alongside PCP_SYNC — order detail backfill + team data
    cur.execute(
        f"""
        SELECT 1 FROM jobs
        WHERE consultant_id = {PH}
          AND type = 'REPORT_SYNC'
          AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (consultant_id,),
    )
    if not cur.fetchone():
        insert_job("REPORT_SYNC", {}, consultant_id=consultant_id, priority=0)

    return True
