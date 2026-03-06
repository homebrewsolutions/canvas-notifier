"""
canvas_auth.py — Automated Canvas login via Playwright.

Handles username/password login and optional 2FA, then generates
and returns a Canvas API token that gets saved to .env.

Requires: pip install playwright && playwright install chromium
"""

import threading
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CANVAS_URL = "https://howard.instructure.com"

# Single active session — this is a single-user local tool
_session = {}
_session_lock = threading.Lock()


# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────

def start_canvas_login(username, password):
    """
    Launch a headless browser and attempt Canvas login.

    Returns one of:
      {'status': 'success', 'token': '<api_token>'}
      {'status': '2fa',     'prompt': '<instruction text>'}
      {'status': 'error',   'message': '<reason>'}
    """
    _cleanup_session()

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
    except Exception as e:
        return {'status': 'error', 'message': f"Could not launch browser: {e}"}

    try:
        page.goto(f"{CANVAS_URL}/login/canvas", wait_until="networkidle", timeout=30000)

        # Fill standard Canvas login form
        page.fill('#pseudonym_session_unique_id', username)
        page.fill('#pseudonym_session_password', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle', timeout=20000)

        # Check for 2FA / MFA prompt
        mfa_selectors = [
            'input[name="otp_attempt"]',
            '#otp_attempt',
            'input[name="code"]',
            'input[autocomplete="one-time-code"]',
        ]
        if any(page.locator(sel).count() > 0 for sel in mfa_selectors):
            with _session_lock:
                _session['playwright'] = playwright
                _session['browser']    = browser
                _session['page']       = page
            prompt = _get_2fa_prompt(page)
            return {'status': '2fa', 'prompt': prompt}

        # Check for login error
        error_el = page.locator('.ic-flash-error, #login_error_box, .alert-error, [role="alert"]').first
        if error_el.count() > 0:
            msg = error_el.text_content().strip()
            _try_close(playwright, browser)
            return {'status': 'error', 'message': msg or 'Invalid username or password.'}

        # Check login success
        if _is_logged_in(page):
            token = _generate_api_token(page)
            _try_close(playwright, browser)
            if token:
                return {'status': 'success', 'token': token}
            return {'status': 'error', 'message': 'Logged in but could not generate an API token. Try manually at Canvas → Settings → New Access Token.'}

        # Unexpected state — might be SSO redirect
        current_url = page.url
        _try_close(playwright, browser)
        return {
            'status': 'error',
            'message': (
                f"Unexpected page after login: {current_url}. "
                "Howard may use SSO (Microsoft/Google). If so, use the manual token method instead."
            )
        }

    except PlaywrightTimeout:
        _try_close(playwright, browser)
        return {'status': 'error', 'message': 'Canvas took too long to respond. Check your internet connection.'}
    except Exception as e:
        _try_close(playwright, browser)
        return {'status': 'error', 'message': str(e)}


def submit_2fa_code(code):
    """
    Submit the 2FA/MFA code to complete the login.

    Returns one of:
      {'status': 'success', 'token': '<api_token>'}
      {'status': 'error',   'message': '<reason>'}
    """
    with _session_lock:
        page       = _session.get('page')
        browser    = _session.get('browser')
        playwright = _session.get('playwright')

    if not page:
        return {'status': 'error', 'message': 'No active login session. Please start over.'}

    try:
        # Fill 2FA code
        for sel in ['input[name="otp_attempt"]', '#otp_attempt', 'input[name="code"]', 'input[autocomplete="one-time-code"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, code)
                break

        # Submit
        for sel in ['button[type="submit"]', 'input[type="submit"]']:
            if page.locator(sel).count() > 0:
                page.click(sel)
                break
        else:
            page.keyboard.press('Enter')

        page.wait_for_load_state('networkidle', timeout=15000)

        # Check for bad code error
        error_el = page.locator('.ic-flash-error, [role="alert"], .error').first
        if error_el.count() > 0:
            msg = error_el.text_content().strip()
            if msg:
                return {'status': 'error', 'message': msg}

        if _is_logged_in(page):
            token = _generate_api_token(page)
            _cleanup_session()
            if token:
                return {'status': 'success', 'token': token}
            return {'status': 'error', 'message': 'Logged in but could not generate an API token.'}

        return {'status': 'error', 'message': 'Code was not accepted. Please try again.'}

    except PlaywrightTimeout:
        _cleanup_session()
        return {'status': 'error', 'message': 'Timed out waiting for Canvas after code submission.'}
    except Exception as e:
        _cleanup_session()
        return {'status': 'error', 'message': str(e)}


# ─────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────

def _is_logged_in(page):
    url = page.url
    return (
        '/dashboard' in url
        or url.rstrip('/') == CANVAS_URL
        or page.locator('#dashboard_header_container, .ic-Dashboard-header, #application').count() > 0
    )


def _get_2fa_prompt(page):
    """Try to extract a human-readable 2FA instruction from the page."""
    for sel in ['label[for="otp_attempt"]', '.mfa-description', 'p:near(input[name="otp_attempt"])']:
        el = page.locator(sel).first
        if el.count() > 0:
            text = el.text_content().strip()
            if text:
                return text
    return 'Enter the authentication code sent to your device.'


def _generate_api_token(page):
    """
    Navigate to Canvas profile settings and create a new API access token.
    Returns the token string, or None if it fails.
    """
    try:
        page.goto(f"{CANVAS_URL}/profile/settings", wait_until="networkidle", timeout=15000)

        # Click the "New Access Token" button
        new_token_btn = page.locator('a[href="#access_token_form"], .add_access_token_link').first
        if new_token_btn.count() == 0:
            new_token_btn = page.locator('button:has-text("New Access Token"), a:has-text("New Access Token")').first
        new_token_btn.click()

        # Wait for the modal / form
        page.wait_for_selector('#access_token_form, #access-token-form, [data-testid="access-token-form"]', timeout=8000)

        # Fill in the "Purpose" field
        purpose = page.locator('input[name="access_token[purpose]"], #access_token_purpose').first
        if purpose.count() > 0:
            purpose.fill('Canvas Notifier')

        # Submit
        page.locator('button:has-text("Generate Token"), input[value="Generate Token"]').first.click()

        # Wait for the token to appear
        page.wait_for_selector('.visible_token, #token_value, [data-testid="access-token-value"]', timeout=10000)

        # Extract token text
        for sel in ['.visible_token', '#token_value', '[data-testid="access-token-value"]', 'input.token-value']:
            el = page.locator(sel).first
            if el.count() > 0:
                token = el.input_value() if el.evaluate('e => e.tagName') == 'INPUT' else el.text_content()
                token = (token or '').strip()
                if len(token) > 10:
                    return token

        return None

    except Exception:
        return None


def _cleanup_session():
    global _session
    with _session_lock:
        if _session:
            _try_close(_session.get('playwright'), _session.get('browser'))
            _session = {}


def _try_close(playwright, browser):
    try:
        browser.close()
    except Exception:
        pass
    try:
        playwright.stop()
    except Exception:
        pass
