# email_service.py
import os
import requests


def send_email(to_email: str, subject: str, html: str) -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()

    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set.")
    if not mail_from:
        raise RuntimeError("MAIL_FROM is not set (example: no-reply@mypinkassistant.com).")

    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Resend send failed ({r.status_code}): {r.text}")
