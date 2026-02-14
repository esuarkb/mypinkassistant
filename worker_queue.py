## full worker_queue replacement 2-14 11:09 am

import os
import uuid
from typing import Optional, Tuple

from db import connect, is_postgres

# How long a consultant lock is valid (seconds) in case a worker crashes.
LOCK_TTL_SECONDS = 15 * 60  # 15 minutes

WORKER_ID = os.environ.get("MK_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
PH = "%s" if is_postgres() else "?"


def _conn():
    # autocommit off; we use transactions explicitly in a few spots
    return connect()


def ensure_lock_table():
    """
    Ensure consultant_locks exists.
    Keep column names consistent across DBs: locked_by, locked_at.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS consultant_locks (
                    consultant_id BIGINT PRIMARY KEY,
                    locked_by TEXT NOT NULL,
                    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS consultant_locks (
                    consultant_id INTEGER PRIMARY KEY,
                    locked_by TEXT NOT NULL,
                    locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _cleanup_expired_lock(cur, cid: int):
    """
    Delete expired lock row (if present).
    """
    if is_postgres():
        cur.execute(
            """
            DELETE FROM consultant_locks
            WHERE consultant_id = %s
              AND locked_at < (NOW() - (%s * INTERVAL '1 second'))
            """,
            (int(cid), int(LOCK_TTL_SECONDS)),
        )
    else:
        # SQLite: compare text timestamps using datetime('now', '-N seconds')
        cur.execute(
            """
            DELETE FROM consultant_locks
            WHERE consultant_id = ?
              AND locked_at < datetime('now', ?)
            """,
            (int(cid), f"-{int(LOCK_TTL_SECONDS)} seconds"),
        )


def claim_next_consultant() -> Optional[int]:
    """
    Claims ONE consultant_id that has queued jobs, ensuring only one worker processes that consultant at a time.
    Returns consultant_id or None if nothing available.
    """
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()

    try:
        # Start a transaction
        cur.execute("BEGIN")

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
        if not row:
            conn.commit()
            return None

        # psycopg dict_row returns dict-like, sqlite returns tuple
        cid = row["consultant_id"] if isinstance(row, dict) else row[0]
        if cid is None:
            conn.commit()
            return None
        cid = int(cid)

        # Clear expired lock (if any)
        _cleanup_expired_lock(cur, cid)

        # Try to acquire the lock
        if is_postgres():
            cur.execute(
                """
                INSERT INTO consultant_locks (consultant_id, locked_by)
                VALUES (%s, %s)
                ON CONFLICT (consultant_id) DO NOTHING
                RETURNING locked_by
                """,
                (cid, WORKER_ID),
            )
            got = cur.fetchone()
            if not got:
                conn.commit()
                return None
            locked_by = got["locked_by"] if isinstance(got, dict) else got[0]
            if locked_by != WORKER_ID:
                conn.commit()
                return None

        else:
            # SQLite
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO consultant_locks (consultant_id, locked_by, locked_at)
                    VALUES (?, ?, datetime('now'))
                    """,
                    (cid, WORKER_ID),
                )
            except Exception:
                conn.rollback()
                return None

            cur.execute(
                "SELECT locked_by FROM consultant_locks WHERE consultant_id=?",
                (cid,),
            )
            lock_row = cur.fetchone()
            if not lock_row or lock_row[0] != WORKER_ID:
                conn.commit()
                return None

        conn.commit()
        return cid

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def refresh_consultant_lock(consultant_id: int) -> None:
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        if is_postgres():
            cur.execute(
                """
                UPDATE consultant_locks
                SET locked_at = NOW()
                WHERE consultant_id = %s AND locked_by = %s
                """,
                (int(consultant_id), WORKER_ID),
            )
        else:
            cur.execute(
                """
                UPDATE consultant_locks
                SET locked_at = datetime('now')
                WHERE consultant_id = ? AND locked_by = ?
                """,
                (int(consultant_id), WORKER_ID),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def release_consultant(consultant_id: int) -> None:
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(
            f"DELETE FROM consultant_locks WHERE consultant_id={PH} AND locked_by={PH}",
            (int(consultant_id), WORKER_ID),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def claim_next_job_for_consultant(consultant_id: int) -> Optional[Tuple[int, str, str]]:
    """
    Claims the next queued job for this consultant, in id order.
    Returns (job_id, type, payload_json) or None.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        if is_postgres():
            # Atomic claim on Postgres (prevents two workers grabbing same job)
            cur.execute("BEGIN")
            cur.execute(
                """
                UPDATE jobs
                SET status='running',
                    error='',
                    status_msg='Working…',
                    attempts=attempts + 1,
                    claimed_by=%s,
                    claimed_at=COALESCE(claimed_at, NOW()),
                    started_at=NOW()
                WHERE id = (
                    SELECT id
                    FROM jobs
                    WHERE consultant_id=%s AND status='queued'
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, type, payload_json
                """,
                (WORKER_ID, int(consultant_id)),
            )
            row = cur.fetchone()
            conn.commit()

            if not row:
                return None

            if isinstance(row, dict):
                return (int(row["id"]), str(row["type"]), str(row["payload_json"]))
            return (int(row[0]), str(row[1]), str(row[2]))

        else:
            # SQLite
            cur.execute("BEGIN")
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
            if cur.rowcount != 1:
                conn.commit()
                return None

            conn.commit()
            return (job_id, job_type, payload_json)

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def mark_job_done(job_id: int, msg: str = "Complete ✅") -> None:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        if is_postgres():
            cur.execute(
                """
                UPDATE jobs
                SET status='done',
                    error='',
                    status_msg=%s,
                    finished_at=NOW()
                WHERE id=%s
                """,
                (msg, int(job_id)),
            )
        else:
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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def mark_job_failed(job_id: int, error: str, msg: str = "Failed ❌") -> None:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        if is_postgres():
            cur.execute(
                """
                UPDATE jobs
                SET status='failed',
                    error=%s,
                    status_msg=%s,
                    finished_at=NOW()
                WHERE id=%s
                """,
                (str(error)[:2000], msg, int(job_id)),
            )
        else:
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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
