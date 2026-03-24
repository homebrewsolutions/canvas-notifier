"""
due_date_tracker.py — Detects when Canvas assignment due dates change.

Persists a snapshot of {assignment_id: due_at} to a JSON file.
On each run, compares fresh assignments against the snapshot and
returns a list of changes so the caller can SMS the user.
"""

import json
import os

SNAPSHOT_FILE = os.getenv("DUE_DATE_SNAPSHOT", os.path.join(os.path.dirname(__file__), ".due_date_snapshot.json"))


def _load_snapshot() -> dict:
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_snapshot(snapshot: dict):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshot, f)


def check_for_due_date_changes(assignments: list[dict]) -> list[dict]:
    """
    Compare assignments against the saved snapshot.

    Returns a list of change dicts:
      {title, course, old_due, new_due}

    Also saves an updated snapshot for the next run.
    Assignment dicts must have 'id', 'title', 'course', and 'due_str' keys.
    """
    snapshot = _load_snapshot()
    changes = []

    new_snapshot = {}
    for a in assignments:
        aid = a.get("id")
        if aid is None:
            continue
        key = str(aid)
        new_due = a.get("due_str", "")
        new_snapshot[key] = new_due

        if key in snapshot and snapshot[key] != new_due:
            changes.append({
                "title":   a.get("title", "Unknown"),
                "course":  a.get("course", ""),
                "old_due": snapshot[key],
                "new_due": new_due,
            })

    _save_snapshot(new_snapshot)
    return changes


def format_changes_sms(changes: list[dict]) -> str:
    lines = ["⚠️ Due date change alert!\n"]
    for c in changes:
        lines.append(f"📌 {c['title']} ({c['course']})")
        lines.append(f"   Was: {c['old_due']}")
        lines.append(f"   Now: {c['new_due']}\n")
    return "\n".join(lines).strip()
