"""
canvas.py — Fetches upcoming assignments via the AnySiteMCP server.

Uses howard_canvas_get_calendar_events (type=assignment) so no ICS feed
URL is needed — just a Canvas API access token obtained at login.
"""

import os
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from mcp_client import call_tool

load_dotenv()

DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", 14))
DISPLAY_TZ  = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))


def get_upcoming_assignments(access_token: str = None) -> list[dict]:
    """
    Return assignments due in the next DAYS_AHEAD days.

    Calls howard_canvas_get_calendar_events via the MCP server.
    Falls back to CANVAS_ACCESS_TOKEN env var if access_token is not provided.
    """
    token = access_token or os.getenv("CANVAS_ACCESS_TOKEN")
    if not token:
        raise ValueError("No Canvas access token. Please log in.")

    now      = datetime.now(timezone.utc)
    end      = now + timedelta(days=DAYS_AHEAD)
    now_local = now.astimezone(DISPLAY_TZ)

    events = call_tool("howard_canvas_get_calendar_events", {
        "access_token": token,
        "start_date":   now.date().isoformat(),
        "end_date":     end.date().isoformat(),
        "type":         "assignment",
        "per_page":     100,
    })

    # Canvas returns a list; normalise to list
    if isinstance(events, dict):
        events = events.get("items", events.get("events", [events]))
    if not isinstance(events, list):
        events = []

    assignments = []
    for ev in events:
        due_dt = _parse_dt(ev.get("start_at") or ev.get("end_at") or ev.get("due_at"))
        if due_dt is None:
            continue
        if not (now <= due_dt <= end):
            continue

        assignment = ev.get("assignment") or {}
        course     = ev.get("context_name") or assignment.get("course_id") or "Unknown Course"
        title      = ev.get("title") or assignment.get("name") or "Unnamed Assignment"
        points     = assignment.get("points_possible", "?")
        description = assignment.get("description") or ev.get("description") or ""
        url         = ev.get("html_url") or assignment.get("html_url") or ""

        due_local  = due_dt.astimezone(DISPLAY_TZ)

        assignments.append({
            "course":      course,
            "title":       title,
            "due":         due_dt,
            "due_str":     due_local.strftime("%A, %b %-d @ %-I:%M %p"),
            "days_left":   (due_local.date() - now_local.date()).days,
            "points":      points if points != "?" else "?",
            "description": _strip_html(str(description)),
            "url":         url,
        })

    assignments.sort(key=lambda x: x["due"])
    return assignments


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _parse_dt(value) -> datetime | None:
    """Parse an ISO-8601 string or date/datetime object into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, tzinfo=timezone.utc)
    if isinstance(value, str):
        value = value.rstrip("Z")
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _strip_html(text: str) -> str:
    """Very light HTML-tag stripper so descriptions stay readable."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()
