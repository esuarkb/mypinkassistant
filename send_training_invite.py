"""
One-off: send tonight's training invite.
  python send_training_invite.py preview   — sends to briankrause@gmail.com only
  python send_training_invite.py send      — broadcasts to full Resend audience
"""
import sys
import os
import requests
from dotenv import load_dotenv
load_dotenv()

PREVIEW_MODE = len(sys.argv) < 2 or sys.argv[1] != "send"

API_KEY      = (os.getenv("RESEND_API_KEY_FULL") or "").strip()
MAIL_FROM    = "MyPinkAssistant <support@mypinkassistant.com>"
AUDIENCE_ID  = (os.getenv("RESEND_AUDIENCE_ID") or "").strip()
PREVIEW_TO   = "briankrause@gmail.com"

SUBJECT = "Join us TONIGHT at 7 PM CT — Live MyPinkAssistant Training on Zoom"

HTML = """\
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#ffffff;">
<div style="max-width:600px;margin:0 auto;padding:24px 20px;font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#111;">

  <h2 style="margin:0 0 16px 0;font-size:22px;line-height:1.25;">
    You&rsquo;re invited &mdash; our first live MPA training is <strong>tonight at 7&nbsp;PM&nbsp;CT</strong> 💕
  </h2>

  <p style="margin:0 0 14px 0;">
    Hi {{ contact.first_name }},
  </p>

  <p style="margin:0 0 14px 0;">
    We&rsquo;re hosting our very first live Zoom training tonight and we&rsquo;d love to have you there.
    We&rsquo;ll walk through the features that save you the most time &mdash; from data entry to the
    smart tools that tell you exactly who to follow up with and what to say.
  </p>

  <div style="background:#fff0f5;border:1px solid #f8b4cc;border-radius:10px;padding:16px 20px;margin:0 0 20px 0;">
    <p style="margin:0 0 6px 0;font-weight:bold;font-size:16px;">Tonight &mdash; Monday, May 18 at 7:00 PM CT</p>
    <p style="margin:0 0 4px 0;">
      <a href="https://zoom.us/j/6469022974" style="color:#e91e63;font-weight:bold;text-decoration:none;">zoom.us/j/6469022974</a>
    </p>
    <p style="margin:0;font-size:14px;color:#555;">Passcode: <strong>1111</strong></p>
  </div>

  <p style="margin:0 0 10px 0;font-weight:bold;">Here&rsquo;s what we&rsquo;ll cover:</p>
  <ul style="margin:0 0 18px 0;padding-left:20px;color:#111;">
    <li style="margin-bottom:6px;">Conversational data entry &mdash; add customers and sales slips without filling out a single form</li>
    <li style="margin-bottom:6px;">Instant lookups: customer info, order history, product prices, the Look Book, and more &mdash; all from your phone</li>
    <li style="margin-bottom:6px;">Smart features: who hasn&rsquo;t ordered in 3 months, PCP followups, upcoming birthdays, and more</li>
    <li style="margin-bottom:6px;">Inventory management, bilingual support, and the referral program</li>
  </ul>

  <p style="margin:0 0 16px 0;">
    Whether you&rsquo;re just getting started or have been using MPA for a while, you&rsquo;ll walk away
    with features you didn&rsquo;t know were there.
  </p>

  <p style="margin:0 0 20px 0;font-size:15px;">
    <strong>Know a consultant or director who could use this?</strong> Forward this email or share
    <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;font-weight:bold;">mypinkassistant.com</a>
    &mdash; and don&rsquo;t forget your referral link in Settings earns you a free month when they sign up.
  </p>

  <p style="margin:0 0 22px 0;">
    <a href="https://zoom.us/j/6469022974"
       style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
              padding:13px 20px;border-radius:10px;font-weight:bold;font-size:16px;">
      Join the Zoom &rarr;
    </a>
  </p>

  <p style="margin:0 0 6px 0;">See you tonight!</p>
  <p style="margin:0 0 0 0;font-size:14px;color:#555;">Brian<br>MyPinkAssistant</p>

  <div style="border-top:1px solid #e6e6e6;margin-top:28px;padding-top:14px;">
    <p style="margin:0;font-size:12px;color:#999;line-height:1.5;">
      You&rsquo;re receiving this because you have an active MyPinkAssistant account.<br>
      <a href="{{{ unsubscribe_url }}}" style="color:#999;">Unsubscribe</a>
    </p>
  </div>

</div>
</body>
</html>
"""

TEXT = """\
You're invited — our first live MPA training is TONIGHT at 7 PM CT!

Hi {{ contact.first_name }},

We're hosting our very first live Zoom training tonight and we'd love to have you there.

TONIGHT — Monday, May 18 at 7:00 PM CT
zoom.us/j/6469022974
Passcode: 1111

Here's what we'll cover:
- Conversational data entry — add customers and sales slips without filling out a single form
- Instant lookups: customer info, order history, product prices, the Look Book, and more
- Smart features: who hasn't ordered in 3 months, PCP followups, upcoming birthdays, and more
- Inventory management, bilingual support, and the referral program

Know a consultant or director who could use this? Forward this email or share mypinkassistant.com — and your referral link in Settings earns you a free month when they sign up.

See you tonight!
Brian
MyPinkAssistant

---
To unsubscribe: {{{ unsubscribe_url }}}
"""

if PREVIEW_MODE:
    print(f"PREVIEW MODE — sending to {PREVIEW_TO} only")
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "from": MAIL_FROM,
            "to": [PREVIEW_TO],
            "subject": f"[PREVIEW] {SUBJECT}",
            "html": HTML.replace("{{ contact.first_name }}", "Brian").replace("{{{ unsubscribe_url }}}", "https://mypinkassistant.com/unsubscribe"),
            "text": TEXT.replace("{{ contact.first_name }}", "Brian").replace("{{{ unsubscribe_url }}}", "https://mypinkassistant.com/unsubscribe"),
        },
        timeout=15,
    )
    print(f"Status: {r.status_code}")
    print(r.text)

else:
    print("BROADCAST MODE — sending to full audience")
    # Create broadcast
    r = requests.post(
        "https://api.resend.com/broadcasts",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "audience_id": AUDIENCE_ID,
            "from": MAIL_FROM,
            "name": "MPA Training Invite — May 18 2026",
            "subject": SUBJECT,
            "html": HTML,
            "text": TEXT,
        },
        timeout=15,
    )
    print(f"Create broadcast: {r.status_code}")
    if r.status_code >= 300:
        print(r.text)
        sys.exit(1)

    broadcast_id = r.json()["id"]
    print(f"Broadcast ID: {broadcast_id}")

    # Send it
    r2 = requests.post(
        f"https://api.resend.com/broadcasts/{broadcast_id}/send",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={},
        timeout=15,
    )
    print(f"Send: {r2.status_code}")
    print(r2.text)
