import os
import sqlite3
import uuid
from pathlib import Path
from typing import Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"

# How long a consultant lock is valid (seconds) in case a worker crashes.
LOCK_TTL_SECONDS = 15 * 60  # 15 minutes

WORKER_ID = os.environ.get("MK_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"


def _conn():
    # autocommit off; we use transactions
    return sqlite3.connect(str(DB_PATH), timeout=30)


def ensure_lock_table():
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS consultant_locks (
            consultant_id INTEGER PRIMARY KEY,
            locked_by TEXT NOT NULL,
            locked_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


def _now_sql() -> str:
    return "datetime('now')"


def claim_next_consultant() -> Optional[int]:
    """
    Claims ONE consultant_id that has queued jobs, ensuring only one worker processes that consultant at a time.
    Returns consultant_id or None if nothing available.
    """
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        # Find the next consultant who has queued jobs
        cur.execute(
            """
            SELECT consultant_id
            FROM jobs
            WHERE status='queued' AND consultant_id IS NOT NULL
            ORDER BY id
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            conn.commit()
            return None

        cid = int(row[0])

        # Clear expired lock (if any)
        cur.execute(
            """
            DELETE FROM consultant_locks
            WHERE consultant_id = ?
              AND locked_at != ''
              AND (strftime('%s','now') - strftime('%s', locked_at)) > ?
            """,
            (cid, LOCK_TTL_SECONDS),
        )

        # Try to acquire the lock
        cur.execute(
            """
            INSERT OR IGNORE INTO consultant_locks (consultant_id, locked_by, locked_at)
            VALUES (?, ?, datetime('now'))
            """,
            (cid, WORKER_ID),
        )

        # Did we get it?
        cur.execute(
            "SELECT locked_by FROM consultant_locks WHERE consultant_id=?",
            (cid,),
        )
        lock_row = cur.fetchone()
        if not lock_row or lock_row[0] != WORKER_ID:
            # someone else has it
            conn.commit()
            return None

        conn.commit()
        return cid

    finally:
        conn.close()


def refresh_consultant_lock(consultant_id: int) -> None:
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            UPDATE consultant_locks
            SET locked_at=datetime('now')
            WHERE consultant_id=? AND locked_by=?
            """,
            (int(consultant_id), WORKER_ID),
        )
        conn.commit()
    finally:
        conn.close()


def release_consultant(consultant_id: int) -> None:
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "DELETE FROM consultant_locks WHERE consultant_id=? AND locked_by=?",
            (int(consultant_id), WORKER_ID),
        )
        conn.commit()
    finally:
        conn.close()


def claim_next_job_for_consultant(consultant_id: int) -> Optional[Tuple[int, str, str]]:
    """
    Claims the next queued job for this consultant, in id order.
    Returns (job_id, type, payload_json) or None.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute(
            """
            SELECT id, type, payload_json
            FROM jobs
            WHERE consultant_id=? AND status='queued'
            ORDER BY id
            LIMIT 1
            """,
            (int(consultant_id),),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None

        job_id, job_type, payload_json = int(row[0]), str(row[1]), str(row[2])

        # Mark running + attempts + timestamps
        cur.execute(
            """
            UPDATE jobs
            SET status='running',
                error='',
                status_msg='Working…',
                attempts=attempts + 1,
                claimed_by=?,
                claimed_at=COALESCE(NULLIF(claimed_at,''), datetime('now')),
                started_at=datetime('now')
            WHERE id=? AND status='queued'
            """,
            (WORKER_ID, job_id),
        )

        # If update didn't happen, someone else claimed it
        if cur.rowcount != 1:
            conn.commit()
            return None

        conn.commit()
        return (job_id, job_type, payload_json)

    finally:
        conn.close()


def mark_job_done(job_id: int, msg: str = "Complete ✅") -> None:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            UPDATE jobs
            SET status='done',
                error='',
                status_msg=?,
                finished_at=datetime('now')
            WHERE id=?
            """,
            (msg, int(job_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_job_failed(job_id: int, error: str, msg: str = "Failed ❌") -> None:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            UPDATE jobs
            SET status='failed',
                error=?,
                status_msg=?,
                finished_at=datetime('now')
            WHERE id=?
            """,
            (str(error)[:2000], msg, int(job_id)),
        )
        conn.commit()
    finally:
        conn.close()
