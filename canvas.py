"""
canvas.py — Fetches upcoming assignments from a Canvas ICS calendar feed.
No API token required — uses the personal calendar feed URL from Canvas.
"""

import os
import requests
from datetime import datetime, timezone, timedelta, date
from icalendar import Calendar
from dotenv import load_dotenv

load_dotenv()

DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", 14))


def get_upcoming_assignments(feed_url=None):
    """Return a list of assignments due in the next DAYS_AHEAD days from a Canvas ICS feed."""
    feed_url = feed_url or os.getenv("CANVAS_FEED_URL")
    if not feed_url:
        raise ValueError("No Canvas calendar feed URL found. Please connect your Canvas account.")

    resp = requests.get(feed_url, timeout=15)
    resp.raise_for_status()

    cal  = Calendar.from_ical(resp.content)
    now  = datetime.now(timezone.utc)
    end  = now + timedelta(days=DAYS_AHEAD)

    assignments = []

    for component in cal.walk():
        if component.name != 'VEVENT':
            continue

        # Canvas uses DTSTART for the due date/time
        dtstart = component.get('DTSTART') or component.get('DUE')
        if not dtstart:
            continue

        due_dt = dtstart.dt

        # Normalize to timezone-aware datetime
        if isinstance(due_dt, date) and not isinstance(due_dt, datetime):
            due_dt = datetime(due_dt.year, due_dt.month, due_dt.day, 23, 59, tzinfo=timezone.utc)
        elif due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)

        if not (now <= due_dt <= end):
            continue

        summary = str(component.get('SUMMARY', 'Unnamed Assignment'))
        course, title = _parse_course_and_title(summary, component)
        url = str(component.get('URL', ''))
        description = str(component.get('DESCRIPTION', ''))

        assignments.append({
            "course":      course,
            "title":       title,
            "due":         due_dt,
            "due_str":     due_dt.strftime("%A, %b %-d @ %-I:%M %p"),
            "days_left":   (due_dt.date() - now.date()).days,
            "points":      "?",
            "description": description,
            "url":         url,
        })

    assignments.sort(key=lambda x: x["due"])
    return assignments


def _parse_course_and_title(summary, component):
    """
    Canvas ICS SUMMARY is usually one of:
      "[Course Name] Assignment Title"
      "Assignment Title"
    Falls back to checking the DESCRIPTION field for a course line.
    """
    # Format: "[Course Name] Assignment Title"
    if summary.startswith('[') and ']' in summary:
        idx    = summary.index(']')
        course = summary[1:idx].strip()
        title  = summary[idx + 1:].strip() or summary
        return course, title

    # Look for "Course: ..." in description
    description = str(component.get('DESCRIPTION', ''))
    for line in description.splitlines():
        lower = line.lower()
        if lower.startswith('course:') or lower.startswith('class:'):
            course = line.split(':', 1)[1].strip()
            return course, summary

    return 'Unknown Course', summary
