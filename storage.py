"""
storage.py — Persistent JSON store for registrations and reminders.
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "store.json"


def _load():
    if not DATA_FILE.exists():
        return {"registrations": {}, "reminders": []}
    with open(DATA_FILE) as f:
        return json.load(f)


def _save(data):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Registrations ─────────────────────────────────────────────────────────────

def save_registration(phone: str, api_key: str):
    """Save/refresh a user's CallMeBot registration. Expires in 72 hours."""
    data = _load()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    data["registrations"][phone] = {"api_key": api_key, "expires_at": expires_at}
    _save(data)


def get_registration(phone: str) -> dict | None:
    """Return registration dict {api_key, expires_at} if still valid, else None."""
    if not phone:
        return None
    data = _load()
    reg = data["registrations"].get(phone)
    if not reg:
        return None
    if datetime.fromisoformat(reg["expires_at"]) < datetime.now(timezone.utc):
        del data["registrations"][phone]
        _save(data)
        return None
    return reg


# ── Reminders ──────────────────────────────────────────────────────────────────

def save_reminder(phone: str, api_key: str, assignment_id, title: str,
                  due_iso: str, remind_at_iso: str, due_str: str) -> str:
    """Persist a reminder. Returns the reminder ID."""
    data = _load()
    reminder = {
        "id":            str(uuid.uuid4()),
        "phone":         phone,
        "api_key":       api_key,
        "assignment_id": str(assignment_id),
        "title":         title,
        "due":           due_iso,
        "due_str":       due_str,
        "remind_at":     remind_at_iso,
        "sent":          False,
    }
    # Avoid duplicates: remove any existing unsent reminder for same phone+assignment
    data["reminders"] = [
        r for r in data["reminders"]
        if not (r["phone"] == phone and r["assignment_id"] == str(assignment_id) and not r["sent"])
    ]
    data["reminders"].append(reminder)
    _save(data)
    return reminder["id"]


def get_pending_reminders() -> list[dict]:
    """Return all unsent reminders whose remind_at time has passed."""
    data = _load()
    now = datetime.now(timezone.utc).isoformat()
    return [r for r in data["reminders"] if not r["sent"] and r["remind_at"] <= now]


def mark_reminder_sent(reminder_id: str):
    data = _load()
    for r in data["reminders"]:
        if r["id"] == reminder_id:
            r["sent"] = True
    _save(data)


def get_reminders_for_phone(phone: str) -> list[dict]:
    """Return all upcoming unsent reminders for a phone number."""
    data = _load()
    now = datetime.now(timezone.utc).isoformat()
    return [
        r for r in data["reminders"]
        if r["phone"] == phone and not r["sent"] and r["due"] >= now
    ]


def delete_reminder(reminder_id: str, phone: str):
    """Delete a reminder (only if it belongs to the given phone)."""
    data = _load()
    data["reminders"] = [
        r for r in data["reminders"]
        if not (r["id"] == reminder_id and r["phone"] == phone)
    ]
    _save(data)
