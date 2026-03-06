# 📚 Howard Canvas AI Assistant

Fetches your Canvas assignments, summarizes them with Claude AI, texts you every morning,
and lets you reply via SMS to ask questions about your workload.

---

## File Structure

```
canvas_notifier/
├── .env                  ← Your secret keys (never share/commit this)
├── .env.example          ← Template for .env
├── requirements.txt      ← Python dependencies
├── canvas.py             ← Fetches assignments from Howard Canvas API
├── ai.py                 ← Claude AI integration (summarize, Q&A, schedule)
├── notifier.py           ← Sends SMS via Twilio
├── daily_digest.py       ← Run by cron every morning → sends your daily SMS
└── app.py                ← Flask server (web dashboard + SMS reply webhook)
```

---

## Setup (Linux)

### 1. Install Python dependencies
```bash
pip3 install -r requirements.txt --break-system-packages
```

### 2. Configure your .env file
```bash
cp .env.example .env
nano .env
```
Fill in all values:
- **CANVAS_TOKEN**: Canvas → Profile → Settings → New Access Token
- **TWILIO_***: from twilio.com dashboard
- **ANTHROPIC_API_KEY**: from console.anthropic.com

### 3. Test the daily digest manually
```bash
python3 daily_digest.py
```
You should receive a text with your AI-summarized assignments.

### 4. Start the web dashboard
```bash
python3 app.py
```
Open http://localhost:5000 in your browser.

### 5. Enable two-way SMS (reply to texts)

Install ngrok to expose your local server to Twilio:
```bash
# Install ngrok
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# Authenticate (get token from ngrok.com)
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Expose your Flask server
ngrok http 5000
```

Copy the ngrok HTTPS URL (e.g. `https://abc123.ngrok.io`) and set it as your
Twilio webhook:
- Go to twilio.com → Phone Numbers → your number → Messaging
- Set "A message comes in" webhook to: `https://abc123.ngrok.io/sms`
- Method: HTTP POST

Now when you reply to your morning SMS, Claude answers back!

### 6. Schedule the daily digest with cron
```bash
crontab -e
```
Add this line (runs every day at 8 AM):
```
0 8 * * * /usr/bin/python3 /home/YOUR_USERNAME/canvas_notifier/daily_digest.py
```

---

## Moving to a Cloud VM

When you're ready to move off your local machine:

1. Spin up a VM (Oracle Cloud free tier, AWS EC2, DigitalOcean, etc.)
2. Copy this entire folder to the VM:
   ```bash
   scp -r ~/canvas_notifier user@YOUR_VM_IP:~/canvas_notifier
   ```
3. SSH in, install deps, run the same setup steps above
4. Replace ngrok with your VM's real public IP in the Twilio webhook:
   ```
   http://YOUR_VM_IP:5000/sms
   ```
   Or set up a domain + nginx + SSL for a cleaner setup.
5. Use `systemd` or `screen` to keep `app.py` running permanently:
   ```bash
   screen -S canvas
   python3 app.py
   # Ctrl+A then D to detach
   ```

---

## Usage

| What | How |
|------|-----|
| Morning SMS digest | Automatic via cron at 8 AM |
| Ask a question | Reply to the SMS with any question |
| Web dashboard | Open http://localhost:5000 |
| Send digest manually | Click "Send to my phone" on dashboard |
| Change look-ahead days | Edit DAYS_AHEAD in .env |
