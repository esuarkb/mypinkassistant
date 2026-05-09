# autoscaler.py
"""
Render worker autoscaler — scales the background worker service up or down
via the Render API based on job queue depth.

Scale-up threshold: QUEUE_SCALE_UP_AT queued jobs → spin up WORKER_MAX instances.
Scale-down: called directly by worker.py after a job completes and queue is empty.

Required env vars:
  RENDER_API_KEY              — Render API key (Account Settings → API Keys)
  RENDER_WORKER_SERVICE_ID    — worker service ID (e.g. srv-xxxxxxxxxxxx)
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

_API_BASE = "https://api.render.com/v1"
_API_KEY = os.getenv("RENDER_API_KEY", "")
_SERVICE_ID = os.getenv("RENDER_WORKER_SERVICE_ID", "")

WORKER_MIN = 1  # baseline — always running
WORKER_MAX = 3  # cap for now; raise as subscriber count grows

# Real-time job types (exclude FULL_SYNC — it's low priority and runs nightly)
_REALTIME_TYPES = ("NEW_ORDER_ROW", "NEW_CUSTOMER", "INITIAL_SYNC",
                   "IMPORT_CUSTOMERS", "IMPORT_INVENTORY_ORDERS", "IMPORT_ORDER_HISTORY")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }


def _scale(num_instances: int) -> bool:
    """Call the Render API to set the worker instance count. Returns True on success."""
    if not _API_KEY or not _SERVICE_ID:
        print("[Autoscaler] ERROR: RENDER_API_KEY or RENDER_WORKER_SERVICE_ID not set")
        return False
    url = f"{_API_BASE}/services/{_SERVICE_ID}/scale"
    resp = requests.post(url, headers=_headers(), json={"numInstances": num_instances}, timeout=10)
    if resp.status_code in (200, 201, 202):
        print(f"[Autoscaler] Scaled to {num_instances} instance(s)")
        return True
    print(f"[Autoscaler] Scale call failed: {resp.status_code} {resp.text[:200]}")
    return False


def scale_up() -> bool:
    """Scale to WORKER_MAX instances."""
    return _scale(WORKER_MAX)


def scale_down() -> bool:
    """Scale back to WORKER_MIN instances."""
    return _scale(WORKER_MIN)


def current_instance_count() -> int | None:
    """Return the current number of running instances, or None on error."""
    if not _API_KEY or not _SERVICE_ID:
        return None
    url = f"{_API_BASE}/services/{_SERVICE_ID}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        return data.get("serviceDetails", {}).get("numInstances")
    print(f"[Autoscaler] Failed to get instance count: {resp.status_code} {resp.text[:200]}")
    return None


def _waiting_consultant_count() -> int:
    """
    Count distinct consultants who have a queued real-time job but no running job.
    These are consultants actively waiting for a free worker.
    FULL_SYNC is excluded — it's low-priority nightly work, not interactive.
    """
    from db import tx
    with tx() as (conn, cur):
        is_sqlite = "sqlite" in type(cur).__module__.lower()
        PH = "?" if is_sqlite else "%s"
        placeholders = ", ".join([PH] * len(_REALTIME_TYPES))
        cur.execute(
            f"""SELECT COUNT(DISTINCT consultant_id) FROM jobs
                WHERE status = {PH}
                  AND type IN ({placeholders})
                  AND consultant_id IS NOT NULL
                  AND consultant_id NOT IN (
                      SELECT DISTINCT consultant_id FROM jobs WHERE status = {PH}
                  )""",
            ("queued", *_REALTIME_TYPES, "running"),
        )
        row = cur.fetchone()
        return int(row[0] if not isinstance(row, dict) else list(row.values())[0]) if row else 0


def _any_jobs_active() -> bool:
    """Return True if any jobs are queued or running (for scale-down guard)."""
    from db import tx
    with tx() as (conn, cur):
        is_sqlite = "sqlite" in type(cur).__module__.lower()
        PH = "?" if is_sqlite else "%s"
        cur.execute(
            f"SELECT 1 FROM jobs WHERE status IN ({PH}, {PH}) LIMIT 1",
            ("queued", "running"),
        )
        return cur.fetchone() is not None


def check_and_scale_up() -> bool:
    """
    Called when a new real-time job is enqueued (from app.py).
    Scales up the moment any consultant is waiting for a free worker.
    """
    waiting = _waiting_consultant_count()
    print(f"[Autoscaler] check_and_scale_up: {waiting} consultant(s) waiting for a worker")
    if waiting >= 1:
        current = current_instance_count()
        if current is not None and current < WORKER_MAX:
            return _scale(min(WORKER_MAX, current + 1))
    return False


def check_and_scale_down() -> bool:
    """
    Called after a worker finishes a job (from worker.py).
    Scales down only when no jobs are queued or running at all.
    """
    active = _any_jobs_active()
    print(f"[Autoscaler] check_and_scale_down: {'jobs still active' if active else 'queue empty'}")
    if not active:
        current = current_instance_count()
        if current is not None and current > WORKER_MIN:
            return scale_down()
    return False


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "up":
        scale_up()
    elif cmd == "down":
        scale_down()
    elif cmd == "status":
        count = current_instance_count()
        waiting = _waiting_consultant_count()
        active = _any_jobs_active()
        print(f"[Autoscaler] instances={count}  consultants_waiting={waiting}  any_active={active}")
    elif cmd == "check-up":
        check_and_scale_up()
    elif cmd == "check-down":
        check_and_scale_down()
    else:
        print("Usage: python autoscaler.py [up|down|status|check-up|check-down]")
