"""
canvas.py — Fetches upcoming assignments from the Canvas REST API.

Works both locally and on Railway. No MCP dependency — calls
https://howard.instructure.com/api/v1/calendar_events directly.
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

CANVAS_BASE = "https://howard.instructure.com"
DAYS_AHEAD  = int(os.getenv("DAYS_AHEAD", 14))
DISPLAY_TZ  = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))


def get_upcoming_assignments(access_token: str = None) -> list[dict]:
    """
    Return assignments due in the next DAYS_AHEAD days.

    Calls GET /api/v1/calendar_events?type=assignment on Howard's Canvas.
    Falls back to CANVAS_ACCESS_TOKEN env var if no token is provided.
    """
    token = access_token or os.getenv("CANVAS_ACCESS_TOKEN")
    if not token:
        raise ValueError("No Canvas access token. Please log in.")

    now       = datetime.now(timezone.utc)
    end       = now + timedelta(days=DAYS_AHEAD)
    now_local = now.astimezone(DISPLAY_TZ)

    resp = requests.get(
        f"{CANVAS_BASE}/api/v1/calendar_events",
        params={
            "access_token": token,
            "type":         "assignment",
            "start_date":   now.date().isoformat(),
            "end_date":     end.date().isoformat(),
            "per_page":     100,
        },
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json()

    if not isinstance(events, list):
        events = []

    assignments = []
    for ev in events:
        due_dt = _parse_dt(ev.get("start_at") or ev.get("end_at"))
        if due_dt is None or not (now <= due_dt <= end):
            continue

        assignment  = ev.get("assignment") or {}
        course      = ev.get("context_name") or "Unknown Course"
        title       = ev.get("title") or assignment.get("name") or "Unnamed Assignment"
        points      = assignment.get("points_possible", "?")
        description = _strip_html(str(assignment.get("description") or ""))
        url         = ev.get("html_url") or ""
        due_local   = due_dt.astimezone(DISPLAY_TZ)

        assignments.append({
            "course":      course,
            "title":       title,
            "due":         due_dt,
            "due_str":     due_local.strftime("%A, %b %-d @ %-I:%M %p"),
            "days_left":   (due_local.date() - now_local.date()).days,
            "points":      points,
            "description": description,
            "url":         url,
        })

    assignments.sort(key=lambda x: x["due"])
    return assignments


def get_grades(access_token: str = None) -> list[dict]:
    """
    Return current grades for all active courses.

    Calls GET /api/v1/courses with total_scores included.
    """
    token = access_token or os.getenv("CANVAS_ACCESS_TOKEN")
    if not token:
        raise ValueError("No Canvas access token. Please log in.")

    resp = requests.get(
        f"{CANVAS_BASE}/api/v1/courses",
        params={
            "access_token":    token,
            "enrollment_state": "active",
            "include[]":       "total_scores",
            "per_page":        50,
        },
        timeout=15,
    )
    resp.raise_for_status()
    courses = resp.json()

    if not isinstance(courses, list):
        return []

    grades = []
    for course in courses:
        # Canvas nests grade info inside the enrollments array
        enrollment = next((e for e in course.get("enrollments", [])
                           if e.get("type") == "student"), None)
        if not enrollment:
            continue

        score = enrollment.get("computed_current_score")
        grade = enrollment.get("computed_current_grade")

        grades.append({
            "course":  course.get("name") or course.get("course_code") or "Unknown Course",
            "score":   score,   # numeric e.g. 92.5
            "grade":   grade,   # letter  e.g. "A"
            "url":     f"{CANVAS_BASE}/courses/{course['id']}",
        })

    grades.sort(key=lambda x: x["course"])
    return grades


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, 23, 59, tzinfo=timezone.utc)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value.rstrip("Z"), fmt.rstrip("Z"))
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()
