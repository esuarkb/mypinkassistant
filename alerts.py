import requests
import os

PB_API_KEY = os.getenv("PB_API_KEY")
PB_CONTACT_ID = os.getenv("PB_CONTACT_ID")


def send_failure_text(message):
    # Mirror every SMS alert as a web push (2026-07-12): PB has a 9am send
    # window (noon Sundays) — push has none, and it reaches the Watch.
    # Push problems must never break the SMS path.
    try:
        from push_notify import send_push_to_admins
        send_push_to_admins("🚨 MPA Failure", message, url="/admin")
    except Exception as _pe:
        print("Push mirror failed:", _pe)

    url = "https://api.projectbroadcast.com/v2/messages"

    payload = {
        "body": f"🚨 MyPinkAssistant Failure\n\n{message}",
        "contact_ids": [PB_CONTACT_ID]
    }

    headers = {
        "X-Auth-Token": PB_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code != 200:
            print("Failed to send alert:", r.text)
    except Exception as e:
        print("Failed to send alert:", e)