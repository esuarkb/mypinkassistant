"""
Feature update email — send via Resend Broadcasts.

Usage:
    python send_test_email.py          # test send to briankrause@gmail.com
    python send_test_email.py send     # broadcast to full audience
"""
import os, sys, requests
from dotenv import load_dotenv

load_dotenv()

API_KEY      = os.getenv("RESEND_API_KEY_FULL", "").strip()
MAIL_FROM    = os.getenv("MAIL_FROM", "support@mypinkassistant.com").strip()
AUDIENCE_ID  = os.getenv("RESEND_AUDIENCE_ID", "").strip()
TEST_TO      = "briankrause@gmail.com"
BROADCAST    = len(sys.argv) > 1 and sys.argv[1] == "send"

SUBJECT = "What's new in MyPinkAssistant 💕"

UNSUBSCRIBE_EMAIL = "support@mypinkassistant.com"

TEXT = """\
Hi there!

We've been busy adding features you asked for — here's a quick look at what's new.

---
🎂 BIRTHDAY TEXTS — ONE TAP AWAY

Ask: "Who has birthdays this month?"

You'll get a list of customers with birthdays this month, each with a button to open a pre-written birthday text right on your phone. One tap and it's ready to send — no copy-pasting.

---
📋 YOUR FOLLOW-UP LIST, DONE FOR YOU

Ask: "Who hasn't ordered in 90 days?"

MyPinkAssistant pulls a list of customers who are due for a follow-up. Pick a few names and reach out — it's the fastest way to turn quiet customers back into active ones.

---
🔍 FIND CUSTOMERS BY PRODUCT

Ask: "Who are my Repair customers?"

See every customer who's ordered from a product line, along with the date they last ordered it. Perfect for reaching out when there's a sale, a new product, or a bundle deal on something they already love.

---
📖 PRODUCT LOOKUP WITH PRICE & FACT SHEET

Ask: "TimeWise Repair Volu-Firm Set"

Get the current price and a direct link to the official Product Fact Sheet — right from chat. No more digging through InTouch.

---
📅 A SIMPLE WEEKLY HABIT

If you're just getting started, here's a routine that fits in 15 minutes and sets you up for some real income producing activities:

• Monday morning: Ask who has birthdays this week → send a quick text from the list
• After every party or selling event: Enter new profile cards and sales slips in chat
• Once a week: Ask "who needs a follow-up?" → reach out to a few
• Once a week: Ask "who hasn't ordered in 90 days?" → check in with customers you haven't heard from

---
KNOW A CONSULTANT WHO'D LOVE THIS?

Your personal referral link is in Settings at https://mypinkassistant.com — when a consultant signs up with your link, you both get a free month. It's the easiest thank-you you can give someone who's been thinking about getting organized.

---
We are always listening to your suggestions and feedback to ensure we are the best we can be to help you succeed in your business. Make sure to follow us on our socials for tips, tricks and new feature launches!

Facebook: https://www.facebook.com/mypinkassistant1
TikTok: https://www.tiktok.com/@mypinkassistant

---
Questions? We're always here at support@mypinkassistant.com.

— The MyPinkAssistant Team
https://mypinkassistant.com

To unsubscribe from these emails, reply with "unsubscribe" or email support@mypinkassistant.com
"""

HTML = """\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">

      <h2 style="margin:0 0 14px 0;font-size:22px;line-height:1.25;">
        What's new in <strong>MyPinkAssistant</strong>
      </h2>

      <p style="margin:0 0 20px 0;">
        We've been busy adding features you asked for — here's a quick look at what's new.
      </p>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 20px;border-radius:10px;font-weight:bold;">
          Open MyPinkAssistant
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:4px;"></div>

      <!-- BIRTHDAYS -->
      <h3 style="margin:20px 0 6px 0;font-size:17px;">🎂 Birthday Texts — One Tap Away</h3>
      <p style="margin:0 0 10px 0;">
        Ask chat who has birthdays this month and you'll get a list of customers with a button to open a pre-written birthday text right on your phone. One tap and it's ready to send — no copy-pasting, no fumbling.
      </p>
      <p style="margin:0 0 18px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Try it:</strong><br>
        Who has birthdays this month?<br>
        Who has birthdays this week?
      </p>

      <div style="border-top:1px solid #e6e6e6;margin-bottom:16px;"></div>

      <!-- FOLLOW-UP LIST -->
      <h3 style="margin:0 0 6px 0;font-size:17px;">📋 Your Follow-Up List, Done for You</h3>
      <p style="margin:0 0 10px 0;">
        Ask who hasn't ordered recently and MyPinkAssistant pulls a list of customers who are due for a check-in. Pick a few names and reach out — it's the fastest way to turn quiet customers back into active ones.
      </p>
      <p style="margin:0 0 18px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Try it:</strong><br>
        Who hasn't ordered in 90 days?<br>
        Who hasn't ordered in 6 months?
      </p>

      <div style="border-top:1px solid #e6e6e6;margin-bottom:16px;"></div>

      <!-- PRODUCT SEARCH -->
      <h3 style="margin:0 0 6px 0;font-size:17px;">🔍 Find Customers by Product</h3>
      <p style="margin:0 0 10px 0;">
        Search your customer base by product line. See every customer who's ordered from it and when they last ordered — perfect for reaching out when there's a sale, a new launch, or a bundle deal on something they already love.
      </p>
      <p style="margin:0 0 18px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Try it:</strong><br>
        Who are my Repair customers?<br>
        Who are my Matte Foundation customers?<br>
        Customers who ordered Satin Hands
      </p>

      <div style="border-top:1px solid #e6e6e6;margin-bottom:16px;"></div>

      <!-- PRODUCT LOOKUP -->
      <h3 style="margin:0 0 6px 0;font-size:17px;">📖 Product Lookup with Price &amp; Fact Sheet</h3>
      <p style="margin:0 0 10px 0;">
        Type any product name and get the current price plus a direct link to the official Product Fact Sheet — right from chat. Great for quickly answering a customer's question without digging through InTouch.
      </p>
      <p style="margin:0 0 18px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Try it:</strong><br>
        TimeWise Repair Volu-Firm Set<br>
        Satin Hands Pampering Set<br>
        How much is the charcoal mask?
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-bottom:6px;"></div>

      <!-- WEEKLY ROUTINE -->
      <h3 style="margin:0 0 10px 0;font-size:17px;">📅 A Simple Weekly Habit</h3>
      <p style="margin:0 0 10px 0;">
        If you're still getting into a routine, here's one that fits in 15 minutes and sets you up for some real income producing activities:
      </p>
      <table style="width:100%;border-collapse:separate;border-spacing:0 8px;margin-bottom:10px;">
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;">
            <strong>Monday morning</strong><br>
            Ask who has birthdays this week &rarr; send a quick text from the list
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;">
            <strong>After every party or selling event</strong><br>
            Enter new profile cards and sales slips in chat — takes 30 seconds per customer
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;">
            <strong>Once a week</strong><br>
            Ask "who needs a follow-up?" &rarr; pick a few customers and check in
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;">
            <strong>Once a week</strong><br>
            Ask "who hasn't ordered in 90 days?" &rarr; reach out to customers you haven't heard from
          </td>
        </tr>
      </table>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:8px;margin-bottom:6px;"></div>

      <!-- REFERRAL -->
      <h3 style="margin:0 0 8px 0;font-size:17px;">Know a Consultant Who'd Love This?</h3>
      <p style="margin:0 0 14px 0;">
        Your personal referral link is waiting in <strong>Settings</strong> — when a consultant signs up with your link, you both get a free month. It's the easiest thank-you you can give someone who's been thinking about getting organized.
      </p>
      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com/settings"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:10px 18px;border-radius:10px;font-weight:bold;font-size:14px;">
          Grab Your Referral Link
        </a>
      </p>

      <!-- FEEDBACK + SOCIALS -->
      <p style="margin:0 0 10px 0;font-size:14px;color:#111;">
        We are always listening to your suggestions and feedback to ensure we are the best we can be to help you succeed in your business. Make sure to follow us on our socials for tips, tricks and new feature launches!
      </p>
      <p style="margin:0 0 24px 0;font-size:14px;">
        <a href="https://www.facebook.com/mypinkassistant1"
           style="color:#e91e63;text-decoration:none;font-weight:bold;">Facebook</a>
        &nbsp;&bull;&nbsp;
        <a href="https://www.tiktok.com/@mypinkassistant"
           style="color:#e91e63;text-decoration:none;font-weight:bold;">TikTok</a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:4px;"></div>

      <p style="margin:12px 0 4px 0;font-size:14px;color:#5a5a5a;">
        Questions or feedback?
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>
      </p>
      <p style="margin:6px 0 0 0;font-size:12px;color:#5a5a5a;">
        <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">mypinkassistant.com</a>
        &nbsp;&bull;&nbsp;
        <a href="mailto:support@mypinkassistant.com?subject=Unsubscribe"
           style="color:#aaaaaa;text-decoration:none;font-size:11px;">Unsubscribe</a>
      </p>

    </div>
  </body>
</html>
"""

if not API_KEY:
    raise SystemExit("No RESEND_API_KEY_FULL found in .env")

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

if BROADCAST:
    if not AUDIENCE_ID:
        raise SystemExit("No RESEND_AUDIENCE_ID found in .env")

    # Create broadcast
    r = requests.post(
        "https://api.resend.com/broadcasts",
        headers=HEADERS,
        json={
            "audience_id": AUDIENCE_ID,
            "from": MAIL_FROM,
            "subject": SUBJECT,
            "html": HTML,
            "text": TEXT,
            "name": "Feature update — May 2026",
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise SystemExit(f"Resend error creating broadcast: {r.status_code}: {r.text}")

    broadcast_id = r.json()["id"]
    print(f"Broadcast created: {broadcast_id}")

    # Send it
    r2 = requests.post(
        f"https://api.resend.com/broadcasts/{broadcast_id}/send",
        headers=HEADERS,
        timeout=15,
    )
    if r2.status_code >= 300:
        raise SystemExit(f"Resend error sending broadcast: {r2.status_code}: {r2.text}")

    print(f"Broadcast sent to audience — {r2.json()}")

else:
    # Test send to single address
    r = requests.post(
        "https://api.resend.com/emails",
        headers=HEADERS,
        json={
            "from": MAIL_FROM,
            "to": [TEST_TO],
            "subject": SUBJECT,
            "html": HTML,
            "text": TEXT,
            "headers": {
                "List-Unsubscribe": f"<mailto:{UNSUBSCRIBE_EMAIL}?subject=Unsubscribe>",
            },
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise SystemExit(f"Resend error {r.status_code}: {r.text}")

    print(f"Test email sent to {TEST_TO} — status {r.status_code}")
    print(r.json())
