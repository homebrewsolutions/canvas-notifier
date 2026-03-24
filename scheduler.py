"""
scheduler.py — Background thread that fires WhatsApp reminders every 5 minutes.
Uses only stdlib threading — no apscheduler dependency.
"""

import threading
import time
import traceback

from storage import get_pending_reminders, mark_reminder_sent
from notifier import send_whatsapp

_started = False
_lock    = threading.Lock()


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
        except Exception:
            print(f"[scheduler] failed reminder {r['id']}:", flush=True)
            traceback.print_exc()


def _loop():
    while True:
        try:
            _check_reminders()
        except Exception:
            traceback.print_exc()
        time.sleep(300)  # 5 minutes


def start():
    global _started
    with _lock:
        if _started:
            return
        t = threading.Thread(target=_loop, daemon=True, name="reminder-scheduler")
        t.start()
        _started = True
        print("[scheduler] started — checking reminders every 5 min", flush=True)
