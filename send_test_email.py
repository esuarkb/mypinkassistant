"""One-time script to send a test feature update email via Resend."""
import os, requests
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("RESEND_API_KEY", "").strip()
MAIL_FROM = os.getenv("MAIL_FROM", "support@mypinkassistant.com").strip()
TO = "briankrause@gmail.com"

SUBJECT = "What's new in MyPinkAssistant 💕"

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

If you're just getting started, here's a routine that fits in 15 minutes and sets you up for real income:

• Monday morning: Ask who has birthdays this week → send a quick text from the list
• After every party or selling event: Enter new profile cards and sales slips in chat
• Once a week: Ask "who needs a follow-up?" → reach out to a few
• Once a week: Ask "who hasn't ordered in 90 days?" → check in with customers you haven't heard from

Consistency here is what builds a customer base that reorders without prompting.

---
💌 KNOW A CONSULTANT WHO'D LOVE THIS?

Your personal referral link is in Settings at https://mypinkassistant.com — when a consultant signs up with your link, you both get a free month. It's the easiest thank-you you can give someone who's been thinking about getting organized.

---
Questions? We're always here at support@mypinkassistant.com.

— The MyPinkAssistant Team
https://mypinkassistant.com
"""

HTML = """\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">

      <h2 style="margin:0 0 14px 0;font-size:22px;line-height:1.25;">
        What's new in <strong>MyPinkAssistant</strong> 💕
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
        If you're still getting into a routine, here's one that fits in 15 minutes and sets you up for real income:
      </p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;margin-bottom:8px;display:block;">
            <strong>Monday morning</strong><br>
            Ask who has birthdays this week → send a quick text from the list
          </td>
        </tr>
        <tr><td style="height:8px;"></td></tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;display:block;">
            <strong>After every party or selling event</strong><br>
            Enter new profile cards and sales slips in chat — takes 30 seconds per customer
          </td>
        </tr>
        <tr><td style="height:8px;"></td></tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;display:block;">
            <strong>Once a week</strong><br>
            Ask "who needs a follow-up?" → pick a few customers and check in
          </td>
        </tr>
        <tr><td style="height:8px;"></td></tr>
        <tr>
          <td style="padding:10px 12px;background:#fdf0f5;border-radius:10px;vertical-align:top;display:block;">
            <strong>Once a week</strong><br>
            Ask "who hasn't ordered in 90 days?" → reach out to customers you haven't heard from
          </td>
        </tr>
      </table>
      <p style="margin:0 0 18px 0;font-size:14px;color:#555;">
        Consistency here is what builds a customer base that reorders without you having to chase them.
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-bottom:6px;"></div>

      <!-- REFERRAL -->
      <h3 style="margin:0 0 8px 0;font-size:17px;">💌 Know a Consultant Who'd Love This?</h3>
      <p style="margin:0 0 10px 0;">
        Your personal referral link is waiting in <strong>Settings</strong> — when a consultant signs up with your link, you both get a free month. It's the easiest thank-you you can give someone who's been thinking about getting organized.
      </p>
      <p style="margin:0 0 24px 0;">
        <a href="https://mypinkassistant.com/settings"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:10px 18px;border-radius:10px;font-weight:bold;font-size:14px;">
          Grab Your Referral Link
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:4px;"></div>

      <p style="margin:12px 0 4px 0;font-size:14px;color:#5a5a5a;">
        Questions or feedback?
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>
      </p>
      <p style="margin:6px 0 0 0;font-size:12px;color:#5a5a5a;">
        <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">mypinkassistant.com</a>
      </p>

    </div>
  </body>
</html>
"""

if not API_KEY:
    raise SystemExit("No RESEND_API_KEY found in .env")

r = requests.post(
    "https://api.resend.com/emails",
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    json={"from": MAIL_FROM, "to": [TO], "subject": SUBJECT, "html": HTML, "text": TEXT},
    timeout=15,
)
if r.status_code >= 300:
    raise SystemExit(f"Resend error {r.status_code}: {r.text}")

print(f"Test email sent to {TO} — status {r.status_code}")
print(r.json())
