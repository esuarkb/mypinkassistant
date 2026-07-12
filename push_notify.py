# push_notify.py — Web Push (VAPID) sender for admin alert notifications.
# Built 2026-07-12. Admin-only today; the push_subscriptions table and this
# sender are consultant-ready (consultant_id per row) for the roadmap's
# reorder-reminder push. Subscriptions are created only via the admin-gated
# /push/subscribe endpoint (Enable button on /admin inside the installed PWA).
#
# Delivery notes: iOS shows these like any notification (Watch mirrors when
# the phone is locked). No quiet hours — unlike ProjectBroadcast's 9am window.
import json
import os

from dotenv import load_dotenv
load_dotenv()

VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
VAPID_SUBJECT = (os.getenv("VAPID_SUBJECT") or "mailto:support@mypinkassistant.com").strip()


def _admin_consultant_ids(cur, PH) -> list:
    admin_emails = [e.strip().lower() for e in (os.getenv("MK_ADMIN_EMAILS") or "").split(",") if e.strip()]
    if not admin_emails:
        return []
    marks = ",".join([PH] * len(admin_emails))
    cur.execute(f"SELECT id FROM consultants WHERE lower(email) IN ({marks})", admin_emails)
    return [int(r[0] if not hasattr(r, "get") else r["id"]) for r in cur.fetchall()]


def send_push_to_admins(title: str, body: str, url: str = "/admin", tag: str = "mpa-alert") -> int:
    """Send a web push to every admin subscription. Returns the number
    delivered. Dead subscriptions (404/410 from the push service) are
    deleted; other failures increment failed_count. Never raises — alert
    paths must not die because a notification hiccuped."""
    if not VAPID_PRIVATE_KEY:
        return 0
    try:
        from pywebpush import webpush, WebPushException
        from db import tx, is_postgres
        PH = "%s" if is_postgres() else "?"

        with tx() as (conn, cur):
            admin_ids = _admin_consultant_ids(cur, PH)
            if not admin_ids:
                return 0
            marks = ",".join([PH] * len(admin_ids))
            cur.execute(
                f"SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE consultant_id IN ({marks})",
                admin_ids,
            )
            subs = [
                {"row_id": r[0] if not hasattr(r, "get") else r["id"],
                 "endpoint": r[1] if not hasattr(r, "get") else r["endpoint"],
                 "p256dh": r[2] if not hasattr(r, "get") else r["p256dh"],
                 "auth": r[3] if not hasattr(r, "get") else r["auth"]}
                for r in cur.fetchall()
            ]

        payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
        sent = 0
        dead, failed = [], []
        for s in subs:
            try:
                webpush(
                    subscription_info={"endpoint": s["endpoint"],
                                       "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT},
                    ttl=3600,
                    headers={"Urgency": "high"},
                )
                sent += 1
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):
                    dead.append(s["row_id"])   # phone wiped / subscription rotted
                else:
                    failed.append(s["row_id"])
                print(f"[Push] send failed (status={status}) sub={s['row_id']}: {e}")
            except Exception as e:
                failed.append(s["row_id"])
                print(f"[Push] send failed sub={s['row_id']}: {e}")

        if dead or failed:
            with tx() as (conn, cur):
                for rid in dead:
                    cur.execute(f"DELETE FROM push_subscriptions WHERE id = {PH}", (rid,))
                for rid in failed:
                    cur.execute(f"UPDATE push_subscriptions SET failed_count = failed_count + 1 WHERE id = {PH}", (rid,))
        return sent
    except Exception as e:
        print(f"[Push] send_push_to_admins error: {e}")
        return 0
