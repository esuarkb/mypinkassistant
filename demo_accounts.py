"""Accounts that hold fabricated demo data and must never sync with InTouch.

consultant 1 (briankrause@gmail.com) became a permanent demo account on
2026-07-26 — it is the account used for webinars and screenshots, seeded by
demo_seed.py. It still has live InTouch credentials, so without an explicit
exclusion the nightly scheduler would refill it with real customers and bury
the demo data (which is exactly what happened after the May 2026 demo).

Anything that enumerates consultants for a RECURRING sync must skip these.
One-shot manual runners (run_full_sync.py etc.) are deliberately not guarded —
those are only ever invoked with an explicit account.
"""

DEMO_CONSULTANT_IDS = frozenset({1})


def is_demo_account(consultant_id) -> bool:
    """True if this consultant is a demo account and must not be synced."""
    try:
        return int(consultant_id) in DEMO_CONSULTANT_IDS
    except (TypeError, ValueError):
        return False
