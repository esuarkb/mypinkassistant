"""
Syncs active/trialing consultants to a Resend audience.
Adds/updates active consultants and removes cancelled ones.
Safe to run anytime.

Usage:
    python sync_resend_audience.py <resend_audience_id>

Find your audience ID in the Resend dashboard under Audiences.
"""
import sys
import os
import requests
from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres

if len(sys.argv) < 2:
    print("Usage: python sync_resend_audience.py <resend_audience_id>")
    sys.exit(1)

AUDIENCE_ID = sys.argv[1]
API_KEY = (os.getenv("RESEND_API_KEY_FULL") or "").strip()

if not API_KEY:
    print("Missing RESEND_API_KEY_FULL in environment")
    sys.exit(1)

conn = connect()
cur = conn.cursor()

PH = "%s" if is_postgres() else "?"

# --- Active/trialing: upsert ---
cur.execute("""
    SELECT email, first_name, last_name
    FROM consultants
    WHERE billing_status IN ('active', 'trialing')
      AND email IS NOT NULL AND email != ''
""")
active_rows = cur.fetchall()

# --- Cancelled: remove ---
cur.execute("""
    SELECT email
    FROM consultants
    WHERE billing_status NOT IN ('active', 'trialing')
      AND email IS NOT NULL AND email != ''
""")
cancelled_rows = cur.fetchall()

conn.close()

print(f"Found {len(active_rows)} active/trialing, {len(cancelled_rows)} cancelled\n")

added = 0
add_failed = 0

print("--- Syncing active/trialing ---")
for row in active_rows:
    if isinstance(row, dict):
        email = row["email"]
        first_name = row["first_name"] or ""
        last_name = row["last_name"] or ""
    else:
        email, first_name, last_name = row[0], row[1] or "", row[2] or ""

    r = requests.post(
        f"https://api.resend.com/audiences/{AUDIENCE_ID}/contacts",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "unsubscribed": False,
        },
        timeout=15,
    )

    if r.status_code < 300:
        print(f"  ✅ {email}")
        added += 1
    else:
        print(f"  ❌ {email} — {r.status_code}: {r.text}")
        add_failed += 1

removed = 0
remove_failed = 0

print("\n--- Removing cancelled ---")
for row in cancelled_rows:
    email = row["email"] if isinstance(row, dict) else row[0]

    # Resend requires contact ID to delete — look it up first
    r = requests.get(
        f"https://api.resend.com/audiences/{AUDIENCE_ID}/contacts",
        headers={"Authorization": f"Bearer {API_KEY}"},
        params={"email": email},
        timeout=15,
    )

    if r.status_code >= 300:
        print(f"  ⚠️  {email} — lookup failed: {r.status_code}")
        remove_failed += 1
        continue

    data = r.json()
    contacts = data.get("data", [])
    if not contacts:
        print(f"  — {email} not in audience, skipping")
        continue

    contact_id = contacts[0]["id"]
    r2 = requests.delete(
        f"https://api.resend.com/audiences/{AUDIENCE_ID}/contacts/{contact_id}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=15,
    )

    if r2.status_code < 300:
        print(f"  🗑️  {email} removed")
        removed += 1
    else:
        print(f"  ❌ {email} — delete failed: {r2.status_code}: {r2.text}")
        remove_failed += 1

print(f"\nDone — {added} synced, {removed} removed, {add_failed + remove_failed} failed")
