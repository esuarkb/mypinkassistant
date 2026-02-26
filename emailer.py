import os
import requests

def send_welcome_email(to_email: str, first_name: str = "") -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()  # e.g. "MyPinkAssistant <support@mypinkassistant.com>"
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    name = (first_name or "").strip() or "there"

    subject = "Welcome to MyPinkAssistant.com — here are your starter tips! ✨"
    text = f"""Hi {name}!

Welcome to MyPinkAssistant — we are so glad you're here!

It doesn't take long to get started. You might have already begun before you received this email!

But just in case, here are some quick tips to get the most out of your new assistant:

ADD A NEW CUSTOMER
You can add any or all of these details: First and last name, address, email, phone number, even a birthday!

For example: New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02.

I will do my best to understand what you are entering and get it ready to be sent to MyCustomers.

ADD A CUSTOMER ORDER
Be as detailed as you like! You can add multiple items at once, tell me quantities, and I can search by whatever you tell me.

For example: New order for Jane Doe; she wants a poppy lipstick, 2 charcoal masks, and a 4 in 1 cleanser normal/dry

I will confirm each item to make sure it is correct before submitting the entire order to MyCustomers.
And you can always add or remove before final confirmation!

Thank you so much for choosing MyPinkAssistant!

Need help, have a feature request, or just want to say hello?

Email support@mypinkassistant.com
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
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")