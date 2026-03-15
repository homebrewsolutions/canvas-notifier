"""
canvas.py — Fetches upcoming assignments from the Canvas REST API.

Works both locally and on Railway. No MCP dependency — calls the Canvas
REST API directly. Supports any Canvas school via canvas_url parameter.
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

DAYS_AHEAD  = int(os.getenv("DAYS_AHEAD", 14))
DISPLAY_TZ  = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))

_DEFAULT_CANVAS_URL = "https://howard.instructure.com"


def _resolve_canvas_url(canvas_url: str = None) -> str:
    """Return canvas_url if provided, else fall back to env var or default."""
    return canvas_url or os.getenv("CANVAS_URL", _DEFAULT_CANVAS_URL)


def get_upcoming_assignments(access_token: str = None, cookies: dict = None, canvas_url: str = None) -> list[dict]:
    """
    Return assignments due in the next DAYS_AHEAD days.

    Fetches active courses first, then assignments per course.
    Authenticates via access_token (bearer) or session cookies.
    """
    token = access_token or os.getenv("CANVAS_ACCESS_TOKEN")
    if not token and not cookies:
        raise ValueError("No Canvas credentials. Please log in.")

    base = _resolve_canvas_url(canvas_url)

    now       = datetime.now(timezone.utc)
    end       = now + timedelta(days=DAYS_AHEAD)
    now_local = now.astimezone(DISPLAY_TZ)

    def api_get(path, params=None):
        p = dict(params or {})
        if token:
            p["access_token"] = token
        resp = requests.get(f"{base}{path}", params=p,
                            cookies=cookies or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # Get all active courses
    courses = api_get("/api/v1/courses", {
        "enrollment_state": "active",
        "per_page": 50,
    })
    if not isinstance(courses, list):
        return []

    print(f"[canvas] found {len(courses)} active courses", flush=True)

    assignments = []
    for course in courses:
        if not isinstance(course, dict) or "id" not in course:
            continue
        course_id   = course["id"]
        course_name = course.get("name") or course.get("course_code") or "Unknown Course"

        try:
            items = api_get(f"/api/v1/courses/{course_id}/assignments", {
                "bucket":   "upcoming",
                "per_page": 50,
                "order_by": "due_at",
            })
        except Exception:
            continue

        if not isinstance(items, list):
            continue

        for a in items:
            if not isinstance(a, dict):
                continue
            due_dt = _parse_dt(a.get("due_at"))
            if due_dt is None or not (now <= due_dt <= end):
                continue

            due_local = due_dt.astimezone(DISPLAY_TZ)
            assignments.append({
                "course":      course_name,
                "title":       a.get("name") or "Unnamed Assignment",
                "due":         due_dt,
                "due_str":     due_local.strftime("%A, %b %-d @ %-I:%M %p"),
                "days_left":   (due_local.date() - now_local.date()).days,
                "points":      a.get("points_possible", "?"),
                "description": _strip_html(str(a.get("description") or "")),
                "url":         a.get("html_url") or "",
            })

    assignments.sort(key=lambda x: x["due"])
    print(f"[canvas] found {len(assignments)} upcoming assignments", flush=True)
    return assignments


def get_grades(access_token: str = None, cookies: dict = None, canvas_url: str = None) -> list[dict]:
    """
    Return current grades for all active courses.

    Calls GET /api/v1/courses with total_scores included.
    """
    token = access_token or os.getenv("CANVAS_ACCESS_TOKEN")
    if not token and not cookies:
        raise ValueError("No Canvas credentials. Please log in.")

    base = _resolve_canvas_url(canvas_url)

    params = {
        "enrollment_state": "active",
        "include[]":        "total_scores",
        "per_page":         50,
    }
    if token:
        params["access_token"] = token

    resp = requests.get(
        f"{base}/api/v1/courses",
        params=params,
        cookies=cookies or {},
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
            "url":     f"{base}/courses/{course['id']}",
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
