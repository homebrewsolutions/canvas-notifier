"""
notifier.py — Sends WhatsApp messages via CallMeBot (send-only)

Setup:
  1. Add +34 644 59 82 46 as a contact on WhatsApp (CallMeBot)
  2. Send: "I allow callmebot to send me messages"
  3. You'll receive your CALLMEBOT_API_KEY in reply
  4. Set CALLMEBOT_API_KEY and YOUR_PHONE_NUMBER in your .env
"""

import os
import requests
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

CALLMEBOT_API_KEY = os.getenv("CALLMEBOT_API_KEY")
YOUR_PHONE_NUMBER = os.getenv("YOUR_PHONE_NUMBER")  # E.164 format, e.g. +12025550123

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def send_whatsapp(message, to=None, api_key=None):
    """Send a WhatsApp message via CallMeBot.

    Args:
        message:  Text to send.
        to:       Recipient phone in E.164 format. Falls back to YOUR_PHONE_NUMBER.
        api_key:  Caller's CallMeBot API key. Falls back to CALLMEBOT_API_KEY env var.
    """
    recipient = to or YOUR_PHONE_NUMBER
    key       = api_key or CALLMEBOT_API_KEY

    if not recipient:
        raise ValueError("No phone number — set YOUR_PHONE_NUMBER env var.")
    if not key:
        raise ValueError("No CallMeBot API key — set CALLMEBOT_API_KEY env var.")

    # Strip leading '+' — CallMeBot expects digits only
    phone = recipient.lstrip("+")

    # Split into chunks to stay within WhatsApp limits (~3000 chars safe)
    max_len = 3000
    chunks = [message[i:i+max_len] for i in range(0, len(message), max_len)]

    for i, chunk in enumerate(chunks):
        prefix = f"[{i+1}/{len(chunks)}] " if len(chunks) > 1 else ""
        text = prefix + chunk

        print(f"[whatsapp] sending chunk {i+1}/{len(chunks)} to={recipient}", flush=True)

        resp = requests.get(CALLMEBOT_URL, params={
            "phone": phone,
            "text": text,
            "apikey": key,
        }, timeout=15)

        if not resp.ok:
            raise RuntimeError(f"CallMeBot error {resp.status_code}: {resp.text}")

        print(f"[whatsapp] chunk {i+1} sent: {resp.status_code}", flush=True)

    print(f"[whatsapp] done ({len(chunks)} message(s))", flush=True)
