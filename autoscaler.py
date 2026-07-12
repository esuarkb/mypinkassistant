# autoscaler.py
"""
Render worker autoscaler — scales the background worker service up or down
via the Render API based on job queue depth.

Scale-up triggers (both call check_and_scale_up):
  1. insert_job (mk_chat_core/jobs.py) — the moment a realtime job is queued
  2. worker.py claim-time recheck — every time a worker claims a consultant,
     so a backlog self-heals even if the insert-time call missed (API blip,
     scale-down cooldown)
Scale-down: worker.py after a job completes and the queue is fully empty.

Instance bounds come from system_settings with the module constants as
fallback: "worker_max" (cap) and "worker_min" (floor — raise it to keep
extra workers running, e.g. through the overnight sync window; scale-down
targets it, so no code change is needed).

The automatic hooks NO-OP when running on local SQLite so dev testing can
never scale the production service (manual CLI up/down still works).

Required env vars:
  RENDER_API_KEY              — Render API key (Account Settings → API Keys)
  RENDER_WORKER_SERVICE_ID    — worker service ID (e.g. srv-xxxxxxxxxxxx)
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

_API_BASE = "https://api.render.com/v1"
_API_KEY = os.getenv("RENDER_API_KEY", "")
_SERVICE_ID = os.getenv("RENDER_WORKER_SERVICE_ID", "")

WORKER_MIN = 1  # baseline — always running
WORKER_MAX = 3  # cap for now; raise as subscriber count grows

# Nightly FULL_SYNC sweep scaling (2026-07-04): one worker syncs ~50
# consultants/hour (measured ~55s each), so the sweep stays under ~1 hour at
# any subscriber count with ceil(queued/50) workers. Cap is separate from the
# realtime cap; override via system_settings "worker_max_nightly". Extra
# instances exist only for the sweep — the normal empty-queue scale-down
# returns to worker_min afterwards.
WORKER_MAX_NIGHTLY = 4
FULLSYNC_CONSULTANTS_PER_WORKER = 50

# Real-time job types (exclude FULL_SYNC — it's low priority and runs nightly).
# THE canonical list — mk_chat_core/jobs.py imports it for the insert_job hook,
# so a new realtime job type only ever needs to be added here.
REALTIME_TYPES = ("NEW_ORDER_ROW", "NEW_CUSTOMER", "INITIAL_SYNC",
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
    """Scale to the configured max instances (system_settings worker_max)."""
    return _scale(_get_worker_max())


def scale_down() -> bool:
    """Scale back to the configured min instances (system_settings worker_min)."""
    return _scale(_get_worker_min())


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
        placeholders = ", ".join([PH] * len(REALTIME_TYPES))
        # NOT EXISTS, not NOT IN: a single NULL consultant_id on any running
        # job would make NOT IN evaluate unknown for every row and silently
        # report 0 waiting (= scale-up disabled with no error anywhere).
        cur.execute(
            f"""SELECT COUNT(DISTINCT j.consultant_id) FROM jobs j
                WHERE j.status = {PH}
                  AND j.type IN ({placeholders})
                  AND j.consultant_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM jobs r
                      WHERE r.status = {PH}
                        AND r.consultant_id = j.consultant_id
                  )""",
            ("queued", *REALTIME_TYPES, "running"),
        )
        row = cur.fetchone()
        return int(row[0] if not isinstance(row, dict) else list(row.values())[0]) if row else 0


def _running_consultant_count() -> int:
    """Count distinct consultants with a currently running job (locked to a worker)."""
    from db import tx
    with tx() as (conn, cur):
        is_sqlite = "sqlite" in type(cur).__module__.lower()
        PH = "?" if is_sqlite else "%s"
        cur.execute(
            f"SELECT COUNT(DISTINCT consultant_id) FROM jobs WHERE status = {PH}",
            ("running",)
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


def _get_worker_max() -> int:
    """Read WORKER_MAX from system_settings, fallback to module constant."""
    try:
        from db import get_system_setting
        val = get_system_setting("worker_max", str(WORKER_MAX))
        return max(1, int(val or WORKER_MAX))
    except Exception:
        return WORKER_MAX


def _get_worker_max_nightly() -> int:
    """Nightly sweep cap. Precedence (2026-07-11, Brian's call): an explicit
    "worker_max_nightly" settings row if one ever exists (escape hatch, no
    admin UI) → the admin-page "worker_max" setting (one knob drives both —
    ceil(queued/50) is already demand-based, the cap is only a brake; at
    worker_max=8 it doesn't bind until ~400 subscribers) → module constant."""
    try:
        from db import get_system_setting
        val = get_system_setting("worker_max_nightly", "")
        if val and str(val).strip():
            return max(1, int(val))
        val = get_system_setting("worker_max", str(WORKER_MAX_NIGHTLY))
        return max(1, int(val or WORKER_MAX_NIGHTLY))
    except Exception:
        return WORKER_MAX_NIGHTLY


def _queued_fullsync_count() -> int:
    """Count distinct consultants with a queued FULL_SYNC job."""
    from db import tx
    with tx() as (conn, cur):
        is_sqlite = "sqlite" in type(cur).__module__.lower()
        PH = "?" if is_sqlite else "%s"
        cur.execute(
            f"SELECT COUNT(DISTINCT consultant_id) FROM jobs "
            f"WHERE status = {PH} AND type = {PH} AND consultant_id IS NOT NULL",
            ("queued", "FULL_SYNC"),
        )
        row = cur.fetchone()
        return int(row[0] if not isinstance(row, dict) else list(row.values())[0]) if row else 0


def _nightly_target(queued_fullsync: int, cap: int) -> int:
    """Workers needed for the sweep: ceil(queued/50), capped. Pure — unit-testable."""
    if queued_fullsync <= 0:
        return 0
    needed = -(-queued_fullsync // FULLSYNC_CONSULTANTS_PER_WORKER)  # ceil
    return min(needed, max(1, cap))


def _get_worker_min() -> int:
    """Read WORKER_MIN from system_settings ("worker_min"), fallback to the
    module constant. Scale-down never goes below this, so raising it (e.g.
    to keep 2 workers through the overnight sync window as subscriber count
    grows) is just a settings write — no code change needed here."""
    try:
        from db import get_system_setting
        val = get_system_setting("worker_min", str(WORKER_MIN))
        return max(1, int(val or WORKER_MIN))
    except Exception:
        return WORKER_MIN


_SCALE_DOWN_COOLDOWN = 60  # seconds to suppress scale-up after a scale-down


def _get_last_scale_down() -> float:
    """Return epoch timestamp of the last scale-down, or 0 if never."""
    try:
        from db import get_system_setting
        return float(get_system_setting("last_scale_down_at", "0") or "0")
    except Exception:
        return 0.0


def _record_scale_down() -> None:
    try:
        from db import set_system_setting
        set_system_setting("last_scale_down_at", str(time.time()))
    except Exception:
        pass


def _is_local_env() -> bool:
    """True when running against local SQLite (dev iMac). The automatic
    hooks must never scale the PROD worker from a local test run — the
    queue they inspect is the local one, but the Render API call would
    hit production. Manual CLI commands (up/down) are not guarded."""
    try:
        from db import is_postgres
        return not is_postgres()
    except Exception:
        return False


def check_and_scale_up() -> bool:
    """
    Called when a new real-time job is enqueued (from app.py).
    Scales up the moment any consultant is waiting for a free worker.
    Suppressed during cooldown after a recent scale-down.
    """
    if _is_local_env():
        return False

    elapsed = time.time() - _get_last_scale_down()
    if elapsed < _SCALE_DOWN_COOLDOWN:
        print(f"[Autoscaler] scale-up suppressed — {int(_SCALE_DOWN_COOLDOWN - elapsed)}s cooldown remaining")
        return False

    worker_max = _get_worker_max()
    waiting = _waiting_consultant_count()
    print(f"[Autoscaler] check_and_scale_up: {waiting} consultant(s) waiting for a worker (max={worker_max})")
    if waiting >= 1:
        current = current_instance_count()
        if current is not None:
            running = _running_consultant_count()
            target = min(worker_max, running + waiting + 1)
            if current < target:
                return _scale(target)
    return False


def check_and_scale_nightly() -> bool:
    """
    Scale up for the nightly FULL_SYNC sweep: ceil(queued FULL_SYNCs / 50)
    workers, capped by worker_max_nightly. Called by the scheduler right after
    it queues the sweep, and re-checked at worker claim-time (same self-heal
    pattern as check_and_scale_up). Only ever scales UP — the existing
    empty-queue scale-down returns to worker_min when the sweep finishes.
    """
    if _is_local_env():
        return False

    elapsed = time.time() - _get_last_scale_down()
    if elapsed < _SCALE_DOWN_COOLDOWN:
        print(f"[Autoscaler] nightly scale-up suppressed — {int(_SCALE_DOWN_COOLDOWN - elapsed)}s cooldown remaining")
        return False

    queued = _queued_fullsync_count()
    target = _nightly_target(queued, _get_worker_max_nightly())
    if target <= 0:
        return False
    print(f"[Autoscaler] check_and_scale_nightly: {queued} FULL_SYNC(s) queued → target {target} worker(s)")
    current = current_instance_count()
    if current is not None and current < target:
        return _scale(target)
    return False


def check_and_scale_down() -> bool:
    """
    Called after a worker finishes a job (from worker.py).
    Scales down only when no jobs are queued or running at all.
    Records timestamp so scale-up is suppressed during Render's termination window.
    """
    if _is_local_env():
        return False

    active = _any_jobs_active()
    print(f"[Autoscaler] check_and_scale_down: {'jobs still active' if active else 'queue empty'}")
    if not active:
        worker_min = _get_worker_min()
        current = current_instance_count()
        if current is not None and current > worker_min:
            if _scale(worker_min):
                _record_scale_down()
                return True
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
    elif cmd == "check-nightly":
        check_and_scale_nightly()
    else:
        print("Usage: python autoscaler.py [up|down|status|check-up|check-down|check-nightly]")
