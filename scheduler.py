"""
scheduler.py — Background APScheduler that fires WhatsApp reminders.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from storage import get_pending_reminders, mark_reminder_sent
from notifier import send_whatsapp

_scheduler = BackgroundScheduler(daemon=True)


def _check_reminders():
    pending = get_pending_reminders()
    if not pending:
        return
    print(f"[scheduler] {len(pending)} reminder(s) to send", flush=True)
    for r in pending:
        try:
            msg = (
                f"⏰ *Howard Canvas Reminder*\n\n"
                f"📝 *{r['title']}*\n"
                f"📅 Due: {r['due_str']}\n\n"
                f"Good luck! 🎓"
            )
            send_whatsapp(msg, to=r["phone"], api_key=r["api_key"])
            mark_reminder_sent(r["id"])
            print(f"[scheduler] sent reminder {r['id']} to {r['phone']}", flush=True)
        except Exception as e:
            print(f"[scheduler] failed reminder {r['id']}: {e}", flush=True)


def start():
    if not _scheduler.running:
        _scheduler.add_job(_check_reminders, "interval", minutes=5, id="reminders")
        _scheduler.start()
        print("[scheduler] started — checking reminders every 5 min", flush=True)
