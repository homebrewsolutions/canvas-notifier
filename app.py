"""
app.py — Flask server
  - Receives incoming SMS from Twilio (webhook) and replies with Claude's answer
  - Serves a web dashboard showing assignments + AI insights

Run locally:
  python3 app.py

Then expose with ngrok:
  ngrok http 5000

Set your Twilio webhook to: https://YOUR_NGROK_URL/sms
"""

import os
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, session as flask_session
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

from canvas import get_upcoming_assignments
from ai import answer_question, summarize_assignments, generate_study_schedule
from notifier import send_sms
from canvas_auth import start_browser_login, get_login_result

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "howard-canvas-x9k2mzp-fallback-key"


def get_access_token():
    """Return the Canvas API token from the session, falling back to .env."""
    return flask_session.get('canvas_access_token') or os.getenv('CANVAS_ACCESS_TOKEN')


@app.before_request
def require_auth():
    """Redirect to /setup if the user isn't logged in yet."""
    exempt = ('/setup', '/sms')
    if not any(request.path.startswith(e) for e in exempt):
        if not get_access_token():
            return redirect(url_for('setup'))

# ─────────────────────────────────────────────
#  DASHBOARD HTML
# ─────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>📚 Canvas Assistant</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', sans-serif;
      background: #0d0d0d;
      color: #e8e8e8;
      min-height: 100vh;
    }
    header {
      background: linear-gradient(135deg, #003a8c, #003087);
      padding: 24px 32px;
      display: flex;
      align-items: center;
      gap: 16px;
      border-bottom: 3px solid #b8860b;
    }
    header h1 { font-size: 1.6rem; color: white; }
    header p  { color: #cce0ff; font-size: 0.9rem; margin-top: 4px; }
    .badge {
      background: #b8860b;
      color: white;
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 0.8rem;
      font-weight: bold;
      margin-left: auto;
    }
    main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    @media(max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    .card {
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      padding: 24px;
    }
    .card h2 {
      font-size: 1rem;
      color: #7eb3ff;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid #2a2a2a;
    }
    .ai-summary {
      background: #111;
      border-left: 4px solid #b8860b;
      border-radius: 8px;
      padding: 16px;
      white-space: pre-wrap;
      font-size: 0.95rem;
      line-height: 1.7;
      color: #ddd;
    }
    .assignment {
      padding: 14px;
      border-radius: 8px;
      margin-bottom: 10px;
      border-left: 4px solid #444;
      background: #111;
    }
    .assignment.urgent   { border-color: #ff4d4d; }
    .assignment.soon     { border-color: #ffa500; }
    .assignment.upcoming { border-color: #4caf50; }
    .assignment .title   { font-weight: 600; font-size: 0.95rem; }
    .assignment .meta    { font-size: 0.82rem; color: #888; margin-top: 4px; }
    .assignment .due     { font-size: 0.82rem; margin-top: 6px; }
    .dismiss-btn {
      float: right;
      background: none;
      border: none;
      color: #fff;
      font-size: 1.1rem;
      cursor: pointer;
      line-height: 1;
      padding: 0;
      margin-left: 8px;
    }
    .dismiss-btn:hover { color: #ff6b6b; }
    .tag {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 0.75rem;
      font-weight: bold;
      margin-right: 6px;
    }
    .tag.red    { background: #3d0000; color: #ff6b6b; }
    .tag.orange { background: #2d1a00; color: #ffa500; }
    .tag.green  { background: #002d00; color: #4caf50; }
    .schedule-day { margin-bottom: 16px; }
    .schedule-day h3 {
      font-size: 0.85rem;
      color: #b8860b;
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .schedule-day ul { list-style: none; padding: 0; }
    .schedule-day li {
      font-size: 0.88rem;
      padding: 6px 0;
      border-bottom: 1px solid #222;
      color: #ccc;
    }
    .schedule-day li:before { content: "→ "; color: #555; }
    .chat-box {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .chat-input {
      display: flex;
      gap: 8px;
    }
    .chat-input input {
      flex: 1;
      background: #111;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px 14px;
      color: #eee;
      font-size: 0.9rem;
    }
    .chat-input input:focus { outline: none; border-color: #7eb3ff; }
    .chat-input button {
      background: #003a8c;
      color: white;
      border: none;
      border-radius: 8px;
      padding: 10px 18px;
      cursor: pointer;
      font-size: 0.9rem;
    }
    .chat-input button:hover { background: #0055cc; }
    .chat-messages { min-height: 80px; }
    .msg {
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 8px;
      font-size: 0.9rem;
      line-height: 1.5;
    }
    .msg.user { background: #003a8c22; border-left: 3px solid #003a8c; }
    .msg.ai   { background: #b8860b15; border-left: 3px solid #b8860b; }
    .loading { color: #555; font-style: italic; font-size: 0.85rem; }
    .span-full { grid-column: 1 / -1; }
    .refresh-btn {
      background: none;
      border: 1px solid #333;
      color: #888;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.8rem;
      margin-bottom: 20px;
    }
    .refresh-btn:hover { border-color: #7eb3ff; color: #7eb3ff; }
    .sms-btn {
      background: #b8860b;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.85rem;
      margin-top: 12px;
    }
    .sms-btn:hover { background: #d4a00d; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>📚 Canvas Assistant</h1>
      <p>AI-powered assignment tracker · Next 14 days</p>
    </div>
    <span class="badge" id="count-badge">Loading...</span>
  </header>

  <main>
    <button class="refresh-btn" onclick="loadAll()">⟳ Refresh Data</button>

    <div class="grid">
      <!-- AI Summary -->
      <div class="card span-full">
        <h2>🤖 AI Summary</h2>
        <div class="ai-summary" id="ai-summary">Loading...</div>
        <button class="sms-btn" onclick="sendDigest()">📱 Send to my phone</button>
      </div>

      <!-- Assignments -->
      <div class="card">
        <h2>📋 Upcoming Assignments</h2>
        <div id="assignments">Loading...</div>
      </div>

      <!-- Study Schedule -->
      <div class="card">
        <h2>📅 Suggested Study Schedule</h2>
        <div id="schedule">Loading...</div>
      </div>

      <!-- Ask AI -->
      <div class="card span-full">
        <h2>💬 Ask About Your Assignments</h2>
        <div class="chat-box">
          <div class="chat-messages" id="chat-messages"></div>
          <div class="chat-input">
            <input type="text" id="chat-input" placeholder="e.g. Which assignment should I do first?" onkeydown="if(event.key==='Enter') askAI()"/>
            <button onclick="askAI()">Ask</button>
          </div>
        </div>
      </div>
    </div>
  </main>

  <script>
    let cachedAssignments = [];

    function dismissKey(a) { return `${a.title}::${a.course} · ${a.points} pts`; }
    function getDismissed() { return new Set(JSON.parse(localStorage.getItem('dismissed') || '[]')); }
    function saveDismissed(set) { localStorage.setItem('dismissed', JSON.stringify([...set])); }

    function renderAssignments(assignments) {
      const aDiv = document.getElementById('assignments');
      if (assignments.length === 0) {
        aDiv.innerHTML = '<p style="color:#555">No assignments due in the next 14 days 🎉</p>';
        return;
      }
      aDiv.innerHTML = assignments.map((a, i) => {
        let urgencyClass = 'upcoming', tag = '', tagClass = '';
        if (a.days_left <= 1)      { urgencyClass='urgent';   tag='TODAY/TOMORROW'; tagClass='red'; }
        else if (a.days_left <= 3) { urgencyClass='soon';     tag=`${a.days_left}d left`; tagClass='orange'; }
        else                       { urgencyClass='upcoming'; tag=`${a.days_left}d left`; tagClass='green'; }
        return `
          <div class="assignment ${urgencyClass}" id="assign-${i}">
            <button class="dismiss-btn" onclick="dismiss(${i})" title="Mark as done">&times;</button>
            <div class="title">${a.title}</div>
            <div class="meta">${a.course} · ${a.points} pts</div>
            <div class="due">
              <span class="tag ${tagClass}">${tag}</span>
              📅 ${a.due_str}
            </div>
          </div>`;
      }).join('');
    }

    function dismiss(i) {
      const el = document.getElementById(`assign-${i}`);
      if (!el) return;
      const title = el.querySelector('.title').textContent;
      const meta  = el.querySelector('.meta').textContent;
      const key   = title + '::' + meta;
      const dismissed = getDismissed();
      dismissed.add(key);
      saveDismissed(dismissed);
      el.remove();
      const remaining = document.querySelectorAll('.assignment').length;
      document.getElementById('count-badge').textContent =
        `${remaining} assignment${remaining !== 1 ? 's' : ''}`;
      if (remaining === 0) {
        document.getElementById('assignments').innerHTML =
          '<p style="color:#555">No assignments due in the next 14 days 🎉</p>';
      }
    }

    async function loadAll() {
      document.getElementById('ai-summary').textContent = 'Loading...';
      document.getElementById('assignments').innerHTML = '<p class="loading">Fetching from Canvas...</p>';
      document.getElementById('schedule').innerHTML = '<p class="loading">Generating schedule...</p>';

      const [summaryRes, assignRes, schedRes] = await Promise.all([
        fetch('/api/summary'),
        fetch('/api/assignments'),
        fetch('/api/schedule')
      ]);

      const summaryData  = await summaryRes.json();
      const assignData   = await assignRes.json();
      const scheduleData = await schedRes.json();

      cachedAssignments = assignData.assignments || [];

      // Filter out dismissed assignments
      const dismissed = getDismissed();
      const visible = cachedAssignments.filter(a => !dismissed.has(dismissKey(a)));

      // Badge
      document.getElementById('count-badge').textContent =
        `${visible.length} assignment${visible.length !== 1 ? 's' : ''}`;

      // Summary
      document.getElementById('ai-summary').textContent = summaryData.summary;

      // Assignments
      renderAssignments(visible);

      // Schedule
      const sDiv = document.getElementById('schedule');
      if (!scheduleData.schedule || scheduleData.schedule.length === 0) {
        sDiv.innerHTML = `<p style="color:#888">${scheduleData.summary || 'No schedule generated.'}</p>`;
      } else {
        sDiv.innerHTML = `<p style="color:#888;margin-bottom:16px;font-size:0.85rem">${scheduleData.summary}</p>` +
          scheduleData.schedule.map(day => `
            <div class="schedule-day">
              <h3>${day.day}</h3>
              <ul>${(day.tasks || []).map(t => `<li>${t}</li>`).join('')}</ul>
            </div>`).join('');
      }
    }

    async function askAI() {
      const input = document.getElementById('chat-input');
      const question = input.value.trim();
      if (!question) return;

      const msgs = document.getElementById('chat-messages');
      msgs.innerHTML += `<div class="msg user"><strong>You:</strong> ${question}</div>`;
      msgs.innerHTML += `<div class="msg ai loading" id="thinking">Claude is thinking...</div>`;
      input.value = '';

      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ question })
      });
      const data = await res.json();

      document.getElementById('thinking').remove();
      msgs.innerHTML += `<div class="msg ai"><strong>Claude:</strong> ${data.answer}</div>`;
      msgs.scrollTop = msgs.scrollHeight;
    }

    async function sendDigest() {
      const btn = event.target;
      btn.textContent = 'Sending...';
      btn.disabled = true;
      const res = await fetch('/api/send-digest', { method: 'POST' });
      const data = await res.json();
      btn.textContent = data.ok ? '✅ Sent!' : '❌ Failed';
      setTimeout(() => { btn.textContent = '📱 Send to my phone'; btn.disabled = false; }, 3000);
    }

    loadAll();
  </script>
</body>
</html>
"""

# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/assignments")
def api_assignments():
    try:
        assignments = get_upcoming_assignments(access_token=get_access_token())
        for a in assignments:
            a["due"] = a["due"].isoformat()
        return jsonify({"assignments": assignments})
    except Exception as e:
        return jsonify({"error": str(e), "assignments": []}), 500


@app.route("/api/summary")
def api_summary():
    try:
        assignments = get_upcoming_assignments(access_token=get_access_token())
        summary = summarize_assignments(assignments)
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"summary": f"Error: {str(e)}"}), 500


@app.route("/api/schedule")
def api_schedule():
    try:
        assignments = get_upcoming_assignments(access_token=get_access_token())
        schedule = generate_study_schedule(assignments)
        return jsonify(schedule)
    except Exception as e:
        return jsonify({"summary": f"Error: {str(e)}", "schedule": []}), 500


@app.route("/api/ask", methods=["POST"])
def api_ask():
    try:
        data        = request.get_json()
        question    = data.get("question", "")
        assignments = get_upcoming_assignments(access_token=get_access_token())
        answer      = answer_question(question, assignments)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"answer": f"Error: {str(e)}"}), 500


@app.route("/api/send-digest", methods=["POST"])
def api_send_digest():
    try:
        assignments = get_upcoming_assignments(access_token=get_access_token())
        summary     = summarize_assignments(assignments)
        send_sms(summary)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/logout")
def logout():
    flask_session.pop('canvas_access_token', None)
    return redirect(url_for('setup'))


@app.route("/sms", methods=["POST"])
def sms_webhook():
    """
    Twilio calls this endpoint when you reply to the SMS.
    Claude reads your question and texts back an answer.
    """
    incoming_msg = request.form.get("Body", "").strip()
    resp         = MessagingResponse()

    try:
        assignments = get_upcoming_assignments()
        answer      = answer_question(incoming_msg, assignments)
        resp.message(answer)
    except Exception as e:
        resp.message(f"Sorry, something went wrong: {str(e)}")

    return str(resp)


# ─────────────────────────────────────────────
#  SETUP PAGE HTML
# ─────────────────────────────────────────────

SETUP_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Sign In — Canvas Assistant</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', sans-serif;
      background: #0d0d0d;
      color: #e8e8e8;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container { width: 100%; max-width: 460px; padding: 24px; }
    .card {
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 14px;
      padding: 36px 32px;
    }
    .logo { font-size: 2rem; margin-bottom: 12px; }
    h1 { font-size: 1.3rem; color: #fff; margin-bottom: 6px; }
    .subtitle { font-size: 0.88rem; color: #777; margin-bottom: 28px; line-height: 1.6; }
    .btn {
      display: block;
      width: 100%;
      background: #003a8c;
      color: white;
      border: none;
      border-radius: 8px;
      padding: 13px;
      font-size: 0.95rem;
      cursor: pointer;
      font-weight: 600;
      text-align: center;
      text-decoration: none;
    }
    .btn:hover { background: #0055cc; }
    .btn:disabled { background: #222; color: #555; cursor: default; }
    .alert { padding: 12px 16px; border-radius: 8px; font-size: 0.88rem; margin-bottom: 20px; line-height: 1.5; }
    .alert-error   { background: #3d0000; border-left: 4px solid #ff4d4d; color: #ff9999; }
    .alert-success { background: #002d00; border-left: 4px solid #4caf50; color: #88e888; }
    .alert-info    { background: #001a33; border-left: 4px solid #7eb3ff; color: #9ecfff; }
    .waiting-box { text-align: center; padding: 8px 0 20px; }
    .spinner-ring {
      display: inline-block;
      width: 40px; height: 40px;
      border: 4px solid #2a2a2a;
      border-top-color: #7eb3ff;
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
      margin-bottom: 16px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .waiting-box p { font-size: 0.9rem; color: #aaa; line-height: 1.6; }
    .waiting-box strong { color: #e8e8e8; }
    .retry-link { display: block; text-align: center; margin-top: 16px; font-size: 0.82rem; color: #555; text-decoration: none; }
    .retry-link:hover { color: #7eb3ff; }
  </style>
</head>
<body>
<div class="container">
  <div class="card">

    <div id="view-idle">
      <div class="logo">📚</div>
      <h1>Sign in to Canvas</h1>
      <p class="subtitle">
        Click below to open a browser window where you can sign in with your
        Howard University Microsoft account — including 2FA — just like normal.
        Once you're in, we'll handle the rest automatically.
      </p>
      <div id="error-box" style="display:none" class="alert alert-error"></div>
      <button class="btn" onclick="startLogin()">Open Sign-In Window</button>
    </div>

    <div id="view-waiting" style="display:none">
      <div class="logo">🔐</div>
      <h1>Complete sign-in</h1>
      <div class="waiting-box">
        <div class="spinner-ring"></div>
        <p>
          <strong>A browser window has opened.</strong><br>
          Sign in with your Howard University account there,<br>
          including any 2FA prompts. This page will update automatically.
        </p>
      </div>
      <a class="retry-link" href="/setup">Cancel and start over</a>
    </div>

    <div id="view-success" style="display:none">
      <div class="logo">✅</div>
      <h1>You're connected!</h1>
      <div class="alert alert-success">
        Canvas account linked. Redirecting to your dashboard...
      </div>
    </div>

  </div>
</div>

<script>
  async function startLogin() {
    document.getElementById('error-box').style.display = 'none';
    document.getElementById('view-idle').style.display = 'none';
    document.getElementById('view-waiting').style.display = 'block';

    // Tell the server to launch the browser
    const res = await fetch('/setup/start', { method: 'POST' });
    if (!res.ok) {
      showError('Could not start the login process. Is the server running?');
      return;
    }

    // Poll for result every 2 seconds
    const interval = setInterval(async () => {
      const r = await fetch('/setup/status');
      const data = await r.json();

      if (data.status === 'success') {
        clearInterval(interval);
        // Save token to session then go to dashboard
        await fetch('/setup/complete', { method: 'POST' });
        document.getElementById('view-waiting').style.display = 'none';
        document.getElementById('view-success').style.display = 'block';
        setTimeout(() => window.location.href = '/', 1500);
      } else if (data.status === 'error') {
        clearInterval(interval);
        showError(data.message || 'Login failed. Please try again.');
      }
    }, 2000);
  }

  function showError(msg) {
    document.getElementById('view-waiting').style.display = 'none';
    document.getElementById('view-idle').style.display = 'block';
    const box = document.getElementById('error-box');
    box.textContent = msg;
    box.style.display = 'block';
  }
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────
#  SETUP ROUTES
# ─────────────────────────────────────────────

@app.route("/setup", methods=["GET"])
def setup():
    return render_template_string(SETUP_HTML)


@app.route("/setup/start", methods=["POST"])
def setup_start():
    """Launch the visible browser in a background thread."""
    start_browser_login()
    return jsonify({"ok": True})


@app.route("/setup/status")
def setup_status():
    """Return the current login status for the JS poller."""
    return jsonify(get_login_result())


@app.route("/setup/complete", methods=["POST"])
def setup_complete():
    """Read the token from the completed login and save it to the session."""
    result = get_login_result()
    if result.get("status") == "success" and result.get("token"):
        flask_session["canvas_access_token"] = result["token"]
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "No token available"}), 400


# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 Starting Canvas Assistant...")
    print("   Dashboard: http://localhost:5000")
    print("   SMS webhook: http://localhost:5000/sms")
    print("   (use ngrok to expose the webhook to Twilio)\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
