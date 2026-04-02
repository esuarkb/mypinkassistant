import os
import requests
from html import escape

def send_welcome_email(to_email: str, first_name: str = "") -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()  # e.g. "MyPinkAssistant <support@mypinkassistant.com>"
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    name = (first_name or "").strip() or "there"
    safe_name = escape(name)

    subject = "Welcome to MyPinkAssistant.com — here are your starter tips! ✨"

    # Plain text (fallback)
    text = f"""Hi {name}!

Welcome to MyPinkAssistant — we’re so glad you’re here!

Start chatting now: https://mypinkassistant.com

Here are a few quick starter tips:

ADD A NEW CUSTOMER
Include as much or as little as you want: name, address, email, phone, birthday.

Example:
New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02

I’ll organize it and get it ready to send to MyCustomers automatically.

LOOK UP A CUSTOMER
Just type a name — I’ll find the closest match even if you misspell it.

Example:
What is Jane’s phone number? What did Jane order last time?

ADD A CUSTOMER ORDER
Add multiple items and quantities in one message — I’ll confirm everything before submitting.

Example:
New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.

PERSONAL INVENTORY
When you place an inventory order through MaryKayInTouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.

Example:
How many TimeWise sets do I have? Set my par for charcoal masks to 3.

REFERRAL PROGRAM
Give a month, get a month! Your referral link is in Settings at https://mypinkassistant.com

FOLLOW US ON FACEBOOK
Tips, new features, and updates: https://www.facebook.com/mypinkassistant1

Have questions? Check out our FAQ: https://mypinkassistant.com/faq

We built MyPinkAssistant to save you time and simplify your business - and we’re honored you’re here.

Need help or have a feature request?
support@mypinkassistant.com
"""

    # HTML (pretty + mobile-friendly)
    html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">Hi {safe_name}!</p>

      <h2 style="margin:0 0 12px 0;font-size:22px;line-height:1.25;">
        Welcome to <strong>MyPinkAssistant</strong> 💕
      </h2>

      <p style="margin:0 0 16px 0;">
        You may have already jumped in — but if not, you can start here:
      </p>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Start Chatting
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:10px;"></div>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">💁‍♀️ Add a New Customer</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Include as much or as little detail as you’d like: name, address, email, phone number, birthday.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll organize what you enter and send it to <strong>MyCustomers</strong> automatically.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📇 Look up Customer Information and Orders</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Instantly find customer details and past orders — just type a name.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        What is Jane’s phone number? What did Jane order last time?
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        Can’t remember the exact name? No worries — just give me what you have and I’ll find the closest match.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🛍 Add a Customer Order</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Add multiple items and quantities in one message — no SKU numbers needed.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll confirm each item before submitting, and you can always add/remove before final approval.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📦 Personal Inventory</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        When you place an inventory order through MaryKayInTouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        How many TimeWise sets do I have? Set my par for charcoal masks to 3.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Referral Program</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Give a month, get a month! Your personal referral link is in <strong>Settings</strong>.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Follow Us on Facebook</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Follow our Facebook page for tips, new features, and updates:
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">facebook.com/mypinkassistant1</a>
      </p>

      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        We built MyPinkAssistant to save you time and simplify your business — and we’re honored you’re here. 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Have questions? Check out our <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">FAQ</a> or email us at
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>.
      </p>

      <p style="margin:10px 0 0 0;font-size:12px;color:#5a5a5a;">
        Open MyPinkAssistant anytime: <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">
          mypinkassistant.com
        </a>
      </p>
    </div>
  </body>
</html>
"""

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")


def send_wrong_credentials_email(to_email: str, first_name: str = "") -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    name = (first_name or "").strip() or "there"
    safe_name = escape(name)

    subject = "MyPinkAssistant — incorrect InTouch credentials"

    text = f"""Hi {name}!

It looks like you might have entered the wrong InTouch username or password. You can fix this at mypinkassistant.com/settings — just re-enter the correct credentials, hit Save, and head back to chat to get started.

Let me know if you have any other issues!

-Brian
support@mypinkassistant.com
"""

    html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">Hi {safe_name}!</p>

      <p style="margin:0 0 16px 0;">
        It looks like you might have entered the wrong InTouch username or password. You can fix this in just a few steps:
      </p>

      <ol style="margin:0 0 16px 0;padding-left:20px;color:#111;">
        <li style="margin-bottom:6px;">Tap the button below to open Settings</li>
        <li style="margin-bottom:6px;">Re-enter your correct InTouch username and password</li>
        <li style="margin-bottom:6px;">Hit <strong>Save</strong>, then head back to chat to get started</li>
      </ol>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com/settings"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Go to Settings
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:10px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Thank you for using MyPinkAssistant! We are here if you have any questions, suggestions, or issues! —
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>
      </p>

      <p style="margin:6px 0 0 0;font-size:13px;color:#5a5a5a;">-Brian</p>
    </div>
  </body>
</html>
"""

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")