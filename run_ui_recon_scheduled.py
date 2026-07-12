"""
Scheduled wrapper for run_ui_recon.py (launchd: com.mk.ui-recon, 6:45 AM + 5:00 PM CT).

Runs the read-only InTouch UI recon and texts Brian via ProjectBroadcast ONLY when
something changed (exit 1) or the recon itself crashed (couldn't log in / script
error — which can itself mean MK changed the login page). Silent on clean runs.

Purpose: catch Mary Kay's InTouch deploys (one confirmed incident: the
"Change To Processed" rename landed overnight June 4→5 2026) before a
consultant's job finds them the hard way. Morning run catches overnight
deploys; 5 PM run catches business-hours pushes.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT = Path(__file__).parent
load_dotenv(PROJECT / ".env")

PB_API_KEY = os.getenv("PB_API_KEY", "")
PB_CONTACT_ID = os.getenv("PB_CONTACT_ID", "")
ALERT_EMAIL = "support@mypinkassistant.com"


def send_email(subject: str, body: str) -> None:
    """Resend email — PB doesn't deliver texts before 9am CST, and the 6:45am
    run is the one most likely to catch an overnight MK deploy."""
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        print("[UIRecon] Missing RESEND_API_KEY/MAIL_FROM — cannot email")
        return
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": mail_from, "to": [ALERT_EMAIL], "subject": subject,
                  "text": body},
            timeout=15,
        )
        print(f"[UIRecon] email alert status: {r.status_code}")
    except Exception as e:
        print(f"[UIRecon] Failed to send email alert: {e}")


def send_push(title: str, message: str) -> None:
    # Web push mirror (2026-07-12): the 6:45am run's PB text waits for the 9am
    # send window — push reaches the phone/Watch immediately. push_notify
    # reads prod subscriptions via .env.production when run from this Mac.
    try:
        from push_notify import send_push_to_admins
        n = send_push_to_admins(title, message, url="/admin")
        print(f"[UIRecon] push alert sent to {n} device(s)")
    except Exception as e:
        print(f"[UIRecon] Failed to send push alert: {e}")


def send_text(message: str) -> None:
    if not PB_API_KEY or not PB_CONTACT_ID:
        print("[UIRecon] Missing PB credentials — cannot text")
        return
    try:
        r = requests.post(
            f"https://app.projectbroadcast.com/api/v1/contacts/{PB_CONTACT_ID}/send",
            json={"text": message[:1500]},
            headers={"x-api-key": PB_API_KEY, "Content-Type": "application/json",
                     "Accept": "application/json"},
            timeout=15,
        )
        print(f"[UIRecon] PB alert status: {r.status_code}")
    except Exception as e:
        print(f"[UIRecon] Failed to send PB alert: {e}")


def main() -> int:
    print(f"\n[UIRecon] scheduled run {datetime.now().isoformat(timespec='seconds')}")
    proc = subprocess.run(
        [str(PROJECT / "venv" / "bin" / "python"), str(PROJECT / "run_ui_recon.py")],
        capture_output=True, text=True, timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out)

    if proc.returncode == 0:
        print("[UIRecon] clean — no alert")
        return 0

    change_lines = [l.strip() for l in out.splitlines()
                    if l.strip().startswith(("[", "***")) and
                    ("NEW " in l or "MISSING " in l or "PROBE BROKE" in l or "***" in l)]
    if change_lines:
        body = "\n".join(change_lines[:10])
        msg = (f"🔍 MPA UI Recon: InTouch CHANGED\n\n{body}\n\n"
               f"Run diagnostics before tonight's sync. If benign: python run_ui_recon.py --reset")
        send_email("MPA UI Recon: InTouch CHANGED", msg)
        send_push("🔍 InTouch CHANGED", msg)
        send_text(msg)  # PB delivers after 9am CST; push + email cover the 6:45am run
    else:
        tail = "\n".join(out.splitlines()[-6:])
        msg = (f"🔍 MPA UI Recon FAILED to complete (couldn't inspect InTouch — "
               f"possibly a login-page change or outage):\n\n{tail}")
        send_email("MPA UI Recon: FAILED to complete", msg)
        send_push("🔍 UI Recon FAILED", msg)
        send_text(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
