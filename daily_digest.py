"""
daily_digest.py — Run by cron every morning.
Fetches Canvas assignments, asks Claude to summarize them, sends SMS.

Cron example (8 AM daily):
  0 8 * * * /usr/bin/python3 /home/youruser/canvas_notifier/daily_digest.py
"""

from canvas import get_upcoming_assignments
from ai import summarize_assignments
from notifier import send_sms


def main():
    print("📚 Fetching assignments from Howard Canvas...")
    assignments = get_upcoming_assignments()
    print(f"   Found {len(assignments)} upcoming assignment(s).")

    print("🤖 Asking Claude to summarize...")
    summary = summarize_assignments(assignments)
    print(f"\n--- SMS Preview ---\n{summary}\n-------------------\n")

    print("📱 Sending SMS...")
    send_sms(summary)
    print("🎉 Done!")


if __name__ == "__main__":
    main()
