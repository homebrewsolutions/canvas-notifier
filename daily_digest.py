"""
daily_digest.py — Run by cron every morning.
Fetches Canvas assignments, asks Claude to summarize them, sends SMS.

Cron example (8 AM daily):
  0 8 * * * /usr/bin/python3 /home/youruser/canvas_notifier/daily_digest.py
"""

from canvas import get_upcoming_assignments
from ai import summarize_assignments
from notifier import send_whatsapp
from due_date_tracker import check_for_due_date_changes, format_changes_sms


def main():
    print("📚 Fetching assignments from Howard Canvas...")
    assignments = get_upcoming_assignments()
    print(f"   Found {len(assignments)} upcoming assignment(s).")

    # Check for due date changes before sending the digest
    changes = check_for_due_date_changes(assignments)
    if changes:
        print(f"⚠️  Detected {len(changes)} due date change(s) — sending alert...")
        send_whatsapp(format_changes_sms(changes))
    else:
        print("   No due date changes detected.")

    print("🤖 Asking Claude to summarize...")
    summary = summarize_assignments(assignments)
    print(f"\n--- WhatsApp Preview ---\n{summary}\n-------------------\n")

    print("📱 Sending WhatsApp message...")
    send_whatsapp(summary)
    print("🎉 Done!")


if __name__ == "__main__":
    main()
