"""
get_token.py — Run this once locally to get your Canvas API token.

Usage:
    python3 get_token.py

A browser window will open. Sign in with your Howard University
Microsoft account (including 2FA). The token will be printed here
when done — copy it into Railway as CANVAS_ACCESS_TOKEN.
"""

import time
from canvas_auth import start_browser_login, get_login_result

print("\n" + "="*55)
print("  Canvas Token Generator")
print("="*55)
print("\nOpening browser — sign in with your Howard account.")
print("This page will update when you're done.\n")

start_browser_login()

while True:
    result = get_login_result()

    if result["status"] == "success":
        print("="*55)
        print("  Login successful!")
        print("="*55)
        print(f"\nYour Canvas API token:\n\n  {result['token']}\n")
        print("Copy this token and set it as CANVAS_ACCESS_TOKEN")
        print("in your Railway environment variables.\n")
        break
    elif result["status"] == "error":
        print(f"\nLogin failed: {result['message']}\n")
        break

    time.sleep(2)
