"""
notifier.py — Sends SMS via Twilio
"""

import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
YOUR_PHONE_NUMBER  = os.getenv("YOUR_PHONE_NUMBER")


def send_sms(message, to=None):
    """Send an SMS. Defaults to YOUR_PHONE_NUMBER if no `to` is provided."""
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    recipient = to or YOUR_PHONE_NUMBER

    # Split into chunks if over 1550 chars
    max_len = 1550
    chunks = [message[i:i+max_len] for i in range(0, len(message), max_len)]

    for i, chunk in enumerate(chunks):
        prefix = f"[{i+1}/{len(chunks)}] " if len(chunks) > 1 else ""
        client.messages.create(
            body=prefix + chunk,
            from_=TWILIO_FROM_NUMBER,
            to=recipient
        )

    print(f"✅ SMS sent to {recipient} ({len(chunks)} message(s))")
