# worker_queue.py
import os
import uuid
from typing import Optional, Tuple
import time

RETENTION_EVERY_SECONDS = 15 * 60  # run every 15 minutes (change if you want)
_last_retention_run = 0.0

from db import connect, is_postgres, paramify

# How long a consultant lock is valid (seconds) in case a worker crashes.
LOCK_TTL_SECONDS = 5 * 60  # 5 minutes

WORKER_ID = os.environ.get("MK_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"

# Placeholder style differs:
# - SQLite: ?
# - Postgres (psycopg): %s
PH = "%s" if is_postgres() else "?"


def _conn():
    # autocommit off; we use transactions
    return connect()


def _row_get(row, key: str, idx: int):
    """Works whether row is tuple/list (sqlite) or dict-like (psycopg dict_row)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[idx]


def ensure_lock_table():
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


def reap_stale_running_jobs_and_locks(ttl_seconds: int = LOCK_TTL_SECONDS) -> None:
    """
    If a worker crashes mid-job, jobs can remain 'running' forever.
    This reaps stale running jobs and consultant locks so the queue recovers.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        if is_postgres():
            # Fail stale running jobs
            cur.execute(
                """
                UPDATE jobs
                SET status='failed',
                    status_msg='Failed ❌',
                    error=CASE
                        WHEN COALESCE(error,'') = '' THEN 'reset: stale running job'
                        ELSE LEFT(error,1800) || ' | reset: stale running job'
                    END,
                    finished_at=NOW()
                WHERE status='running'
                  AND started_at IS NOT NULL
                  AND started_at < (NOW() - (%s * INTERVAL '1 second'))
                """,
                (int(ttl_seconds),),
            )

            # Clear stale consultant locks
            cur.execute(
                """
                DELETE FROM consultant_locks
                WHERE locked_at < (NOW() - (%s * INTERVAL '1 second'))
                """,
                (int(ttl_seconds),),
            )
        else:
            # SQLite (timestamps stored as TEXT, compare via epoch seconds)
            cur.execute(
                """
                UPDATE jobs
                SET status='failed',
                    status_msg='Failed ❌',
                    error=CASE
                        WHEN IFNULL(error,'') = '' THEN 'reset: stale running job'
                        ELSE SUBSTR(error,1,1800) || ' | reset: stale running job'
                    END,
                    finished_at=datetime('now')
                WHERE status='running'
                  AND started_at IS NOT NULL
                  AND (strftime('%s','now') - strftime('%s', started_at)) > ?
                """,
                (int(ttl_seconds),),
            )

            cur.execute(
                """
                DELETE FROM consultant_locks
                WHERE locked_at IS NOT NULL
                  AND (strftime('%s','now') - strftime('%s', locked_at)) > ?
                """,
                (int(ttl_seconds),),
            )

        conn.commit()
        
        # Run retention cleanup occasionally (NOT every loop)
        global _last_retention_run
        now = time.time()
        if (now - _last_retention_run) >= RETENTION_EVERY_SECONDS:
            try:
                retention_cleanup()
            except Exception as e:
                print(f"[Retention ERROR - non-fatal] {e}")
        _last_retention_run = now
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def retention_cleanup(redact_hours: int = 24, delete_days: int = 90):
    """
    Redact PII after `redact_hours`.
    Delete old jobs entirely after `delete_days`.

    Safe for both SQLite and Postgres.
    """

    conn = connect()
    cur = conn.cursor()

    try:
        if is_postgres():
            # ---------------------------
            # REDACT (Postgres)
            # ---------------------------
            cur.execute("""
                UPDATE jobs
                SET payload_json = '{}',
                    error = '',
                    status_msg = COALESCE(NULLIF(status_msg,''), 'Redacted')
                WHERE status IN ('done','failed')
                AND payload_json <> '{}'
                AND COALESCE(finished_at, created_at)
                        < (NOW() - make_interval(hours => %s))
            """, (int(redact_hours),))

            redacted = cur.rowcount

            # ---------------------------
            # DELETE (Postgres)
            # ---------------------------
            cur.execute("""
                DELETE FROM jobs
                WHERE COALESCE(finished_at, created_at)
                    < (NOW() - make_interval(days => %s))
            """, (int(delete_days),))

            deleted = cur.rowcount

        else:
            # ---------------------------
            # REDACT (SQLite)
            # ---------------------------
            cur.execute("""
                UPDATE jobs
                SET payload_json='{}',
                    error='',
                    status_msg=CASE
                        WHEN status_msg IS NULL OR status_msg='' THEN 'Redacted'
                        ELSE status_msg
                    END
                WHERE status IN ('done','failed')
                  AND payload_json <> '{}'
                  AND (
                      strftime('%s','now') - strftime('%s',
                        COALESCE(NULLIF(finished_at,''), NULLIF(created_at,''))
                      )
                  ) > ?
            """, (redact_hours * 3600,))

            redacted = cur.rowcount

            # ---------------------------
            # DELETE (SQLite)
            # ---------------------------
            cur.execute("""
                DELETE FROM jobs
                WHERE (
                    strftime('%s','now') - strftime('%s',
                      COALESCE(NULLIF(finished_at,''), NULLIF(created_at,''))
                    )
                ) > ?
            """, (delete_days * 24 * 3600,))

            deleted = cur.rowcount

        conn.commit()
        if redacted or deleted:
            print(f"[Retention] Redacted: {redacted} | Deleted: {deleted}")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[Retention ERROR] {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def _begin(cur):
    # SQLite supports BEGIN IMMEDIATE, Postgres doesn't need it (BEGIN is fine)
    if is_postgres():
        cur.execute("BEGIN")
    else:
        cur.execute("BEGIN IMMEDIATE")


def _now_expr():
    return "NOW()" if is_postgres() else "datetime('now')"


def _lock_expiry_delete_sql():
    if is_postgres():
        # locked_at older than NOW() - interval
        return f"""
            DELETE FROM consultant_locks
            WHERE consultant_id = {PH}
              AND locked_at < (NOW() - ({PH} || ' seconds')::interval)
        """
    else:
        # sqlite epoch seconds comparison
        return """
            DELETE FROM consultant_locks
            WHERE consultant_id = ?
              AND locked_at != ''
              AND (strftime('%s','now') - strftime('%s', locked_at)) > ?
        """


def _insert_lock_sql():
    if is_postgres():
        return f"""
            INSERT INTO consultant_locks (consultant_id, locked_by, locked_at)
            VALUES ({PH}, {PH}, { _now_expr() })
            ON CONFLICT (consultant_id) DO NOTHING
        """
    else:
        return """
            INSERT OR IGNORE INTO consultant_locks (consultant_id, locked_by, locked_at)
            VALUES (?, ?, datetime('now'))
        """


def claim_next_consultant() -> Optional[int]:
    """
    Claims ONE consultant_id that has queued jobs, ensuring only one worker processes that consultant at a time.
    Returns consultant_id or None if nothing available.
    """
    ensure_lock_table()
    conn = _conn()
    cur = conn.cursor()

    try:
        _begin(cur)

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

        cid = _row_get(row, "consultant_id", 0)
        if cid is None:
            conn.commit()
            return None
        cid = int(cid)

        # Clear expired lock (if any)
        cur.execute(_lock_expiry_delete_sql(), (cid, LOCK_TTL_SECONDS))

        # Try to acquire lock
        cur.execute(_insert_lock_sql(), (cid, WORKER_ID))

        # Did we get it?
        cur.execute(f"SELECT locked_by FROM consultant_locks WHERE consultant_id={PH}", (cid,))
        lock_row = cur.fetchone()
        locked_by = _row_get(lock_row, "locked_by", 0)

        if locked_by != WORKER_ID:
            conn.commit()
            return None

        conn.commit()
        return cid

    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def refresh_consultant_lock(consultant_id: int) -> None:
    ensure_lock_table()
    reap_stale_running_jobs_and_locks()
    conn = _conn()
    cur = conn.cursor()
    try:
        _begin(cur)
        cur.execute(
            f"""
            UPDATE consultant_locks
            SET locked_at={_now_expr()}
            WHERE consultant_id={PH} AND locked_by={PH}
            """,
            (int(consultant_id), WORKER_ID),
        )
        conn.commit()
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
        _begin(cur)
        cur.execute(
            f"DELETE FROM consultant_locks WHERE consultant_id={PH} AND locked_by={PH}",
            (int(consultant_id), WORKER_ID),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


# -------------------------
# Job claiming (simple + safe)
# -------------------------

def _claim_next_job_for_consultant_filtered(
    consultant_id: int,
    only_type: Optional[str] = None,
) -> Optional[Tuple[int, str, str]]:
    """
    Core job claimer.
    - FIFO by id (per consultant)
    - Strong "customer barrier":
        If there exists ANY NEW_CUSTOMER job (queued OR running) whose id is
        LESS than the next queued NEW_ORDER_ROW id, we will ONLY claim NEW_CUSTOMER
        jobs until they are finished. This prevents orders from running before the
        customer exists in MyCustomers.
    - If only_type is provided, only claims that type.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        _begin(cur)

        cid = int(consultant_id)

        # ---------------------------------------------------------
        # 🚧 Strong customer barrier (works even if customer is queued)
        #
        # If:
        #   min_customer_id (queued/running NEW_CUSTOMER) < min_order_id (queued NEW_ORDER_ROW)
        # Then:
        #   only claim NEW_CUSTOMER until the barrier is gone.
        # ---------------------------------------------------------
        customer_barrier_active = False
        if not only_type:
            # Oldest NEW_CUSTOMER that is queued OR running
            cur.execute(
                f"""
                SELECT MIN(id)
                FROM jobs
                WHERE consultant_id={PH}
                  AND status IN ('queued','running')
                  AND type='NEW_CUSTOMER'
                """,
                (cid,),
            )
            row = cur.fetchone()
            min_customer_id = row[0] if row else None

            # Oldest queued NEW_ORDER_ROW
            cur.execute(
                f"""
                SELECT MIN(id)
                FROM jobs
                WHERE consultant_id={PH}
                  AND status='queued'
                  AND type='NEW_ORDER_ROW'
                """,
                (cid,),
            )
            row = cur.fetchone()
            min_order_id = row[0] if row else None

            if min_customer_id is not None and min_order_id is not None:
                customer_barrier_active = int(min_customer_id) < int(min_order_id)

        # ---------------------------------------------------------
        # Pick the next job to claim
        # ---------------------------------------------------------
        if only_type:
            # Explicitly restricted to one type
            cur.execute(
                f"""
                SELECT id, type, payload_json
                FROM jobs
                WHERE consultant_id={PH}
                  AND status='queued'
                  AND type={PH}
                ORDER BY id
                LIMIT 1
                """,
                (cid, only_type),
            )
        else:
            if customer_barrier_active:
                # While barrier is active, ONLY pull queued NEW_CUSTOMER jobs
                cur.execute(
                    f"""
                    SELECT id, type, payload_json
                    FROM jobs
                    WHERE consultant_id={PH}
                      AND status='queued'
                      AND type='NEW_CUSTOMER'
                    ORDER BY id
                    LIMIT 1
                    """,
                    (cid,),
                )
            else:
                # Normal FIFO: oldest queued job first (customer or order)
                cur.execute(
                    f"""
                    SELECT id, type, payload_json
                    FROM jobs
                    WHERE consultant_id={PH}
                      AND status='queued'
                    ORDER BY id
                    LIMIT 1
                    """,
                    (cid,),
                )

        row = cur.fetchone()
        if not row:
            conn.commit()
            return None

        job_id = int(_row_get(row, "id", 0))
        job_type = str(_row_get(row, "type", 1))
        payload_json = str(_row_get(row, "payload_json", 2))

        # ---------------------------------------------------------
        # Mark running + attempts + timestamps
        # ---------------------------------------------------------
        if is_postgres():
            cur.execute(
                f"""
                UPDATE jobs
                SET status='running',
                    error='',
                    status_msg='Working…',
                    attempts=attempts + 1,
                    claimed_by={PH},
                    claimed_at=COALESCE(claimed_at, NOW()),
                    started_at=NOW()
                WHERE id={PH}
                  AND status='queued'
                """,
                (WORKER_ID, job_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE jobs
                SET status='running',
                    error='',
                    status_msg='Working…',
                    attempts=attempts + 1,
                    claimed_by={PH},
                    claimed_at=COALESCE(NULLIF(claimed_at,''), datetime('now')),
                    started_at=datetime('now')
                WHERE id={PH}
                  AND status='queued'
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
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def claim_next_job_for_consultant(consultant_id: int) -> Optional[Tuple[int, str, str]]:
    """
    Claims the next queued job for this consultant (respects FIFO + customer barrier).
    """
    return _claim_next_job_for_consultant_filtered(consultant_id, only_type=None)


def claim_next_order_row_for_consultant(consultant_id: int) -> Optional[Tuple[int, str, str]]:
    """
    Claims ONLY NEW_ORDER_ROW (if you ever re-add batching).
    Note: This bypasses the "customer barrier" ONLY if you call it directly.
    """
    return _claim_next_job_for_consultant_filtered(consultant_id, only_type="NEW_ORDER_ROW")

def requeue_job(job_id: int, msg: str = "Queued") -> None:
    """
    Put a job back into the queue.
    Used when we accidentally claimed an order row that we decided not to process yet
    (e.g., batching rows and the next row is for a different customer).
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        _begin(cur)

        if is_postgres():
            cur.execute(
                f"""
                UPDATE jobs
                SET status='queued',
                    status_msg={PH},
                    error='',
                    claimed_by=NULL,
                    claimed_at=NULL,
                    started_at=NULL
                WHERE id={PH}
                """,
                (msg, int(job_id)),
            )
        else:
            cur.execute(
                f"""
                UPDATE jobs
                SET status='queued',
                    status_msg={PH},
                    error='',
                    claimed_by='',
                    claimed_at='',
                    started_at=''
                WHERE id={PH}
                """,
                (msg, int(job_id)),
            )

        conn.commit()
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
        _begin(cur)
        cur.execute(
            f"""
            UPDATE jobs
            SET status='done',
                error='',
                status_msg={PH},
                finished_at={_now_expr()}
            WHERE id={PH}
            """,
            (msg, int(job_id)),
        )
        conn.commit()
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
        _begin(cur)
        cur.execute(
            f"""
            UPDATE jobs
            SET status='failed',
                error={PH},
                status_msg={PH},
                finished_at={_now_expr()}
            WHERE id={PH}
            """,
            (str(error)[:2000], msg, int(job_id)),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
