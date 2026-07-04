# playwright_automation/step_log.py
"""
Step-level logging for the Playwright scripts (2026-07).

Purpose: when Mary Kay changes InTouch and a script dies, the Render worker
log — and the job's error text / SMS alert — must say exactly which named
step was running, instead of a bare locator traceback.

Usage inside a script (markers ONLY — never wrap script actions in new
try/except and never change waits/timing for logging's sake):

    from playwright_automation.step_log import step
    step("login", 2, 8, "wait_consultant_number", "waiting for 'Consultant Number' textbox")

Each call prints one line:

    [job 8129] [login] STEP 2/8 wait_consultant_number — waiting for 'Consultant Number' textbox

and remembers itself, so when a job fails, worker.py appends last_step() to
the error text ("... [died at login/wait_consultant_number (step 2/8)]").

worker.py calls set_job(job_id) when it claims a job and clear() when the job
ends. Each worker process runs one job at a time, so module-level state is
safe; threading.local guards against any future threaded use.
"""
import threading

_state = threading.local()


def set_job(job_id) -> None:
    """Called by worker.py when a job is claimed — tags subsequent step lines."""
    _state.job_prefix = f"[job {job_id}] "
    _state.last = ""


def clear() -> None:
    """Called by worker.py when a job finishes (success or failure)."""
    _state.job_prefix = ""
    _state.last = ""


def step(script: str, n: int, total: int, step_id: str, detail: str = "") -> None:
    """Print a step marker and remember it as the most recent step."""
    prefix = getattr(_state, "job_prefix", "")
    line = f"{prefix}[{script}] STEP {n}/{total} {step_id}"
    if detail:
        line += f" — {detail}"
    _state.last = f"{script}/{step_id} (step {n}/{total})"
    print(line, flush=True)


def last_step() -> str:
    """The most recent step marker, for appending to a failed job's error text."""
    return getattr(_state, "last", "")
