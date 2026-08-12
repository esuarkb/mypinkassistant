"""
Weekly Pink Post nudge (launchd: com.mk.pink-post-reminder, Tuesdays 10:00 AM CT).

The Pink Post goes out Tuesdays and is sent LOCALLY from this Mac
(`venv/bin/python send_pink_post.py --send`) — there's no server-side job that
would notice it never happened. This is the only thing that catches a missed
week, so it's a plain reminder, not an alert: it fires every Tuesday whether or
not anything is wrong.

Web push rather than ProjectBroadcast: PB holds texts until its 9am send
window and costs a message; push is instant and free. Same admin channel the
ui-recon alerts use (push_notify.send_push_to_admins reads the PRODUCTION
push_subscriptions table via .env.production when run from this Mac — which is
why the launchd job must set WorkingDirectory to the project root).

Exits 0 even when nothing is delivered; a missed reminder must never look like
a failed job in the launchd log.
"""
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).parent

TITLE = "Pink Post day 💗"
BODY = "Tuesday — draft this week's issue and send it."


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        from push_notify import send_push_to_admins
        n = send_push_to_admins(TITLE, BODY, url="/admin", tag="pink-post")
        print(f"[PinkPostReminder] {stamp} — push sent to {n} device(s)")
        if n == 0:
            # Not fatal, but the whole point of this job is silent otherwise:
            # 0 means no live admin subscription (device revoked, VAPID key
            # missing, or Enable was never tapped on /admin in the PWA).
            print("[PinkPostReminder] WARNING: 0 devices — re-enable push on /admin")
    except Exception as e:
        print(f"[PinkPostReminder] {stamp} — failed to send push: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
