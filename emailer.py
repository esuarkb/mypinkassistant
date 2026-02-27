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

I’ll organize it and get it ready to send to MyCustomers.

ADD A CUSTOMER ORDER
Add multiple items and quantities in one message — I’ll confirm everything before submitting.

Example:
New order for Jane Doe; she wants a poppy lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry skin.

REFERRAL PROGRAM
Give a month, get a month! Your referral link is in Settings at https://mypinkassistant.com

Thank you so much for being here!

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
        I’ll organize what you enter and get it ready to send to <strong>MyCustomers</strong>.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🛍 Add a Customer Order</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Add multiple items and quantities in one message — I’ll work with whatever you tell me.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New order for Jane Doe; she wants a poppy lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry skin.
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll confirm each item before submitting, and you can always add/remove before final approval.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Referral Program</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Give a month, get a month! Your personal referral link is in <strong>Settings</strong>.
      </p>
      
      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        We are so glad you are here — and we are excited to support your business 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Need help, have a feature request, or just want to say hello?<br>
        Email <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">
          support@mypinkassistant.com
        </a>
      </p>

      <p style="margin:10px 0 0 0;font-size:12px;color:#5a5a5a;">
        Or open MyPinkAssistant anytime: <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">
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