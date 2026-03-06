"""
ai.py — Claude-powered assignment analysis and Q&A
"""

import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def summarize_assignments(assignments):
    """
    Ask Claude to prioritize and summarize the assignment list
    into a smart, friendly SMS-ready message.
    """
    if not assignments:
        return "✅ No assignments due in the next 14 days. You're all caught up!"

    # Build a clean data dump for Claude
    assignment_data = []
    for a in assignments:
        assignment_data.append(
            f"- [{a['course']}] \"{a['title']}\" — due {a['due_str']} "
            f"({a['days_left']} days left, {a['points']} pts)"
        )

    assignment_text = "\n".join(assignment_data)

    prompt = f"""You are a helpful academic assistant for a Howard University student.
Here are their upcoming assignments for the next 14 days:

{assignment_text}

Write a concise, friendly SMS summary that:
1. Starts with a one-sentence overall workload assessment (light/moderate/heavy week)
2. Highlights the 3 most urgent/important assignments with a brief reason why
3. Groups any remaining assignments briefly by course
4. Ends with one motivational sentence

Keep the total under 1200 characters (SMS limit). Use emojis sparingly. Be direct and helpful."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def answer_question(question, assignments):
    """
    Answer a student's question about their assignments using Claude.
    Keeps the response SMS-friendly (under 600 chars).
    """
    if not assignments:
        context = "The student currently has no upcoming assignments in the next 14 days."
    else:
        lines = []
        for a in assignments:
            lines.append(
                f"- [{a['course']}] \"{a['title']}\" due {a['due_str']} "
                f"({a['days_left']} days left, {a['points']} pts)"
            )
        context = "Current assignments:\n" + "\n".join(lines)

    prompt = f"""You are a helpful academic assistant for a Howard University student.
They are texting you questions about their Canvas assignments.

{context}

Their question: "{question}"

Answer helpfully and concisely. Keep your response under 500 characters since it will be sent as an SMS.
Be friendly, direct, and practical."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def generate_study_schedule(assignments):
    """
    Generate a suggested study schedule based on upcoming assignments.
    Returns a structured dict for the dashboard.
    """
    if not assignments:
        return {"schedule": [], "summary": "No assignments coming up — enjoy the break!"}

    assignment_text = "\n".join([
        f"- [{a['course']}] \"{a['title']}\" due {a['due_str']} ({a['days_left']} days, {a['points']} pts)"
        for a in assignments
    ])

    prompt = f"""You are an academic planner for a Howard University student.

Upcoming assignments:
{assignment_text}

Create a practical study schedule. Respond ONLY with valid JSON in this exact format:
{{
  "summary": "one sentence overview of the plan",
  "schedule": [
    {{
      "day": "Monday, Mar 3",
      "tasks": ["Task 1 description", "Task 2 description"]
    }}
  ]
}}

Spread work realistically across available days. Prioritize high-point and sooner-due assignments."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if present
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"summary": raw, "schedule": []}
