"""
billing_reconcile.py

Nightly safety net for the Stripe webhook pipeline: compares every
consultant's billing_status (and cancel_at_period_end) against Stripe's live
subscription state and heals any drift, with Stripe as the source of truth.

Why this exists (2026-08-15 audit): webhooks are the ONLY thing that updates
billing state, so a single missed delivery desyncs a row forever. Two real
casualties found: consultants 50 and 79 were canceled in Stripe (Aug 6 / Jul 5)
but stuck at past_due in our DB — and past_due passes the access gate, so both
had indefinite free access if they ever came back. Id 50's deletion event fired
during the Aug-6 event-loop outage; Stripe exhausted its retries against the
hung web service and gave up (pending_webhooks=0).

Rules:
- A Stripe customer with NO subscription ever is left alone: that's an
  abandoned checkout still wearing the schema's 'unpaid' signup default
  (11 such rows as of the audit — deliberate, not drift).
- billing_status is healed to the latest subscription's status, stamping
  last_billing_event_at like every webhook write does.
- Healing to 'canceled' also clears the inventory watermark — exact parity
  with the customer.subscription.deleted handler, so a resubscriber is
  treated as new either way.
- cancel_at_period_end syncs only while the sub is live (active/trialing/
  past_due): a portal cancellation fires customer.subscription.updated,
  which the webhook doesn't handle, so this is the only early warning that
  a consultant has scheduled their exit.
- SAFETY CAP: more than MAX_AUTO_FIXES changes → write NOTHING, alert
  instead. If "everyone looks canceled" the problem is this script's inputs
  (bad key, Stripe outage), not 100 simultaneous cancellations. Lesson of
  the referral double-credit bug: never let one bad input loop over the
  whole table.

Runs locally against prod (same pattern as daily_digest.py):
  .env             -> STRIPE_SECRET_KEY, RESEND_API_KEY
  .env.production  -> DATABASE_URL

Usage:
  venv/bin/python billing_reconcile.py --dry-run   # report only, no writes
  venv/bin/python billing_reconcile.py             # heal + email if changed

Scheduled via launchd: com.mk.billing-reconcile (6:15 AM, after the digest).
Emails support@ only when something changed or the run failed — a quiet
night sends nothing.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import psycopg2
import requests
import stripe
from dotenv import dotenv_values, load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
_prod = dotenv_values(os.path.join(_HERE, ".env.production"))

DATABASE_URL = _prod.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
RESEND_API_KEY = (os.environ.get("RESEND_API_KEY") or "").strip()
MAIL_FROM = (os.environ.get("MAIL_FROM") or "support@mypinkassistant.com").strip()
TO_EMAIL = "support@mypinkassistant.com"

# Above this many pending fixes, assume OUR inputs are broken and touch nothing.
MAX_AUTO_FIXES = 10

# cancel_at_period_end only means something while the sub is still alive.
LIVE_STATUSES = ("active", "trialing", "past_due")


def _stripe_truth() -> dict:
    """customer_id -> (sub_id, status, cancel_at_period_end) for the LATEST sub."""
    latest: dict = {}
    for s in stripe.Subscription.list(limit=100, status="all").auto_paging_iter():
        cust = s.customer if isinstance(s.customer, str) else s.customer["id"]
        prev = latest.get(cust)
        if prev is None or s.created > prev[3]:
            latest[cust] = (s.id, s.status, bool(s.cancel_at_period_end), s.created)
    return {c: (v[0], v[1], v[2]) for c, v in latest.items()}


def _email(subject: str, body_html: str) -> None:
    if not RESEND_API_KEY:
        print("[Reconcile] RESEND_API_KEY missing — skipping email")
        return
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": MAIL_FROM, "to": [TO_EMAIL],
                  "subject": subject, "html": body_html},
            timeout=15,
        )
        if resp.status_code >= 300:
            print(f"[Reconcile] Email send failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[Reconcile] Email send failed: {e!r}")


def run(dry_run: bool = False) -> int:
    stripe.api_key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY missing")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL missing (.env.production)")

    truth = _stripe_truth()

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, billing_status, stripe_customer_id,
               stripe_subscription_id, cancel_at_period_end
        FROM consultants
        WHERE stripe_customer_id IS NOT NULL AND stripe_customer_id <> ''
        ORDER BY id
        """
    )
    rows = cur.fetchall()

    fixes = []  # (cid, description, apply_fn(cur))
    for cid, db_status, cust_id, db_sub_id, db_cape in rows:
        db_status = (db_status or "").strip().lower()
        t = truth.get((cust_id or "").strip())
        if t is None:
            # Abandoned checkout: customer exists, no subscription ever.
            continue
        sub_id, s_status, s_cape = t

        if db_status != s_status:
            def _fix_status(cur, cid=cid, sub_id=sub_id, s_status=s_status):
                cur.execute(
                    """
                    UPDATE consultants
                    SET billing_status = %s,
                        stripe_subscription_id = %s,
                        last_billing_event_at = NOW()
                    WHERE id = %s
                    """,
                    (s_status, sub_id, cid),
                )
                if s_status == "canceled":
                    cur.execute(
                        "DELETE FROM inventory_intouch_imports WHERE consultant_id = %s",
                        (cid,),
                    )
            fixes.append((cid, f"billing_status {db_status or '(empty)'} -> {s_status}", _fix_status))
        elif s_status in LIVE_STATUSES and bool(db_cape) != s_cape:
            def _fix_cape(cur, cid=cid, s_cape=s_cape):
                cur.execute(
                    """
                    UPDATE consultants
                    SET cancel_at_period_end = %s,
                        last_billing_event_at = NOW()
                    WHERE id = %s
                    """,
                    (1 if s_cape else 0, cid),
                )
            word = "scheduled cancellation" if s_cape else "cancellation revoked"
            fixes.append((cid, f"cancel_at_period_end {int(bool(db_cape))} -> {int(s_cape)} ({word})", _fix_cape))

    stamp = datetime.now(timezone(timedelta(hours=-5))).strftime("%Y-%m-%d %H:%M CDT")

    if not fixes:
        print(f"[Reconcile] {stamp} — {len(rows)} consultants checked, all in sync. No email.")
        conn.close()
        return 0

    for cid, desc, _ in fixes:
        print(f"[Reconcile]   id {cid}: {desc}")

    if len(fixes) > MAX_AUTO_FIXES:
        conn.close()
        msg = (f"{len(fixes)} mismatches found — over the safety cap of {MAX_AUTO_FIXES}, "
               f"so NOTHING was changed. Either something big really happened or this "
               f"script's Stripe/DB inputs are broken. Investigate by hand.")
        print(f"[Reconcile] {msg}")
        _email(
            f"MPA billing reconcile: SAFETY CAP HIT ({len(fixes)} mismatches, nothing changed)",
            "<p>" + msg + "</p><ul>"
            + "".join(f"<li>consultant {cid}: {desc}</li>" for cid, desc, _ in fixes)
            + "</ul>",
        )
        return 1

    if dry_run:
        print(f"[Reconcile] DRY RUN — {len(fixes)} fix(es) NOT applied.")
        conn.close()
        return 0

    for cid, desc, apply_fn in fixes:
        apply_fn(cur)
    conn.commit()
    conn.close()
    print(f"[Reconcile] {stamp} — applied {len(fixes)} fix(es).")

    items = "".join(f"<li><strong>consultant {cid}</strong>: {desc}</li>" for cid, desc, _ in fixes)
    _email(
        f"MPA billing reconcile: {len(fixes)} fix(es) applied",
        f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;color:#1a1a1a">
        <h2 style="color:#d63384;margin-bottom:4px">Billing Reconcile</h2>
        <p style="color:#666;margin-top:0">{stamp} — DB healed to match Stripe:</p>
        <ul>{items}</ul>
        <p style="color:#999;font-size:11px">Each fix means a Stripe webhook was missed since the
        last run. One or two occasionally is normal (deploy restarts); a steady stream means
        webhook delivery is broken — check the Stripe dashboard's webhook logs.</p>
        </div>""",
    )
    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    try:
        sys.exit(run(dry_run=dry))
    except Exception as e:
        print(f"[Reconcile] FAILED: {e!r}")
        _email("MPA billing reconcile FAILED",
               f"<p>billing_reconcile.py crashed: <code>{e!r}</code></p>"
               "<p>No changes were made past the crash point. Check logs/billing_reconcile.log.</p>")
        sys.exit(1)
