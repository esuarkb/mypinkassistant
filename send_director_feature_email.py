# send_director_feature_email.py
# Sends the director/unit feature announcement to all consultants with team data.
#
# Usage:
#   python send_director_feature_email.py --dry-run   # print recipients, no send
#   python send_director_feature_email.py             # send for real

import sys, os, hmac, hashlib, requests
from dotenv import load_dotenv
load_dotenv()  # picks up RESEND_API_KEY, MAIL_FROM, MK_SESSION_SECRET, APP_BASE_URL

# Pull DATABASE_URL from .env.production without overriding the keys above
_prod_vars = {}
try:
    for line in open(".env.production").read().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            _prod_vars[k.strip()] = v.strip()
    os.environ.setdefault("DATABASE_URL", _prod_vars.get("DATABASE_URL", ""))
except FileNotFoundError:
    pass

from db import connect, is_postgres

DRY_RUN        = "--dry-run" in sys.argv
PH             = "%s" if is_postgres() else "?"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM      = os.environ.get("MAIL_FROM", "").strip()
SESSION_SECRET = os.environ.get("MK_SESSION_SECRET", "").strip()
APP_BASE_URL   = "https://mypinkassistant.com"
SUBJECT        = "New in MyPinkAssistant: Ask questions about your team in chat"


def unsub_token(email: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()


def build_html(first_name: str, email: str) -> str:
    unsub = f"{APP_BASE_URL}/unsubscribe?email={requests.utils.quote(email)}&token={unsub_token(email)}"
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">

      <p style="margin:0 0 12px 0;">Hi {first_name}!</p>

      <h2 style="margin:0 0 12px 0;font-size:22px;line-height:1.25;">
        Your chat assistant now knows your team 💕
      </h2>

      <p style="margin:0 0 16px 0;">
        We just launched a major update for directors and consultants with a team —
        <strong>you can now ask questions about your unit the same way you ask about a customer.</strong>
        Just type in plain English and get an instant answer.
      </p>

      <p style="margin:0 0 22px 0;">
        <a href="{APP_BASE_URL}/app"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Try it now
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:10px;"></div>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📇 Consultant Lookup</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Your entire team is at your fingertips. Look up any consultant by name and instantly see their contact info, career level, activity status, MyShop status, and more — all in one place.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Show me Suzie Sunshine<br>
        What is Sarah's phone number?<br>
        Who is on Heidi's team?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">👥 Team Activity</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Get instant answers about who's active, who's going quiet, and where everyone stands.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Who on my team is inactive?<br>
        Who hasn't placed an order in the last 6 months?<br>
        Show me all T6 consultants
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎀 Great Start Bundles</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Know exactly where each new consultant stands on their Great Start window — right at your fingertips.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Who still has Great Start bundles available?<br>
        When does Sally's Great Start window expire?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">⭐ Star Consultant</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        See who's on track, who's close, and who's already hit a level this quarter — all accessible in seconds.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Who is close to the next Star level?<br>
        Who has already hit Ruby this quarter?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎟 Seminar Registration</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        As registration opens, see who's in and who still needs a nudge.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Who is registered for Seminar?<br>
        Who hasn't registered yet?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">✨ Rise + Radiate Challenge</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Track your team's progress on the challenge — who's earned it, who's close, and who could use some encouragement this month.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Examples:</strong><br>
        Who has earned Rise and Radiate?<br>
        Who is close to qualifying this month?
      </p>

      <p style="margin:0 0 16px 0;color:#111;">
        Your team data syncs every night automatically — so the answers are always up to date when you ask.
      </p>

      <p style="margin:0 0 16px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;font-style:italic;color:#444;">
        💡 <strong>And this is just the beginning.</strong> We have a lot more on the way — more reports, more insights, and more ways to coach and grow your team, all from the same simple chat. Stay tuned!
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Follow Us for Tips & Updates</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        We share tips, new features, and tricks on our socials — follow along so you never miss what's new:
      </p>
      <p style="margin:0 0 16px 0;">
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">Facebook: facebook.com/mypinkassistant1</a><br>
        <a href="https://www.tiktok.com/@mypinkassistant" style="color:#e91e63;text-decoration:none;font-weight:bold;">TikTok: @mypinkassistant</a>
      </p>

      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        We built MyPinkAssistant to save you time and simplify your business — and we're honored you're here. 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Have questions? Check out our <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">FAQ</a> or email us at
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>.
      </p>

      <p style="margin:10px 0 0 0;font-size:12px;color:#5a5a5a;">
        Open MyPinkAssistant anytime: <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">mypinkassistant.com</a>
        &nbsp;·&nbsp; <a href="{unsub}" style="color:#5a5a5a;">Unsubscribe from feature updates</a>
      </p>

    </div>
  </body>
</html>"""


# Find consultants with team data who haven't opted out
conn = connect()
cur = conn.cursor()
cur.execute(f"""
    SELECT DISTINCT c.id, c.email, c.first_name
    FROM consultants c
    JOIN unit_members um ON um.consultant_id = c.id
    WHERE c.billing_status IN ('active', 'trialing')
      AND (c.email_opted_out IS NULL OR c.email_opted_out = 0)
    ORDER BY c.id
""")
recipients = cur.fetchall()
conn.close()

print(f"{'DRY RUN — ' if DRY_RUN else ''}Sending to {len(recipients)} recipient(s):\n")

for row in recipients:
    cid   = row[0] if not hasattr(row, "keys") else row["id"]
    email = row[1] if not hasattr(row, "keys") else row["email"]
    fname = (row[2] if not hasattr(row, "keys") else row["first_name"] or "").strip() or "there"
    print(f"  [{cid}] {email} ({fname})")
    if not DRY_RUN:
        try:
            requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": MAIL_FROM, "to": [email], "subject": SUBJECT, "html": build_html(fname, email)},
                timeout=15,
            ).raise_for_status()
            print(f"       ✓ sent")
        except Exception as e:
            print(f"       ✗ FAILED: {e}")
