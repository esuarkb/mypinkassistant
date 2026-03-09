import requests
import os

PB_API_KEY = os.getenv("PB_API_KEY")
PB_CONTACT_ID = os.getenv("PB_CONTACT_ID")


def send_failure_text(message):

    url = "https://api.projectbroadcast.com/v2/messages"

    payload = {
        "body": f"🚨 MyPinkAssistant Failure\n\n{message}",
        "contact_ids": [PB_CONTACT_ID]
    }

    headers = {
        "X-Auth-Token": PB_API_KEY,
        "Content-Type": "application/json"
    }

    r = requests.post(url, json=payload, headers=headers)

    if r.status_code != 200:
        print("Failed to send alert:", r.text)