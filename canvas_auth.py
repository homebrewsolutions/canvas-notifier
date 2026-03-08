"""
canvas_auth.py — Headless Microsoft SSO login for Howard Canvas.

Handles the full login flow programmatically:
  1. Navigate to Howard Canvas → redirects to Microsoft SSO
  2. Fill in email + password
  3. Detect 2FA type (Authenticator push or code entry)
  4. If code: return prompt so the web UI can ask the user
  5. If push: wait in background for the user to approve on their phone
  6. After login: generate a Canvas API token and return it

Works headlessly — no visible browser needed, runs on Railway.
"""

import time
import threading
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CANVAS_URL = "https://howard.instructure.com"

_lock    = threading.Lock()
_state   = {"status": "idle"}   # idle | pending | needs_code | needs_push | success | error
_session = {}                    # holds playwright / browser / page between requests


# ─────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────

def start_login(email: str, password: str) -> dict:
    """
    Begin the SSO login flow synchronously up to the 2FA step.

    Returns one of:
      {'status': 'success',    'token': '...'}
      {'status': 'needs_code', 'prompt': '...'}   ← app should ask user for code
      {'status': 'needs_push', 'prompt': '...'}   ← app should tell user to check phone;
                                                     poll get_status() until success/error
      {'status': 'error',      'message': '...'}
    """
    _cleanup()
    _set(status="pending")

    try:
        pw      = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page()

        with _lock:
            _session["pw"]      = pw
            _session["browser"] = browser
            _session["page"]    = page

        # Navigate to Canvas — it will redirect to Microsoft SSO automatically
        page.goto(CANVAS_URL, wait_until="networkidle", timeout=30_000)

        # If already on Canvas (cached session), finish immediately
        if _on_canvas(page):
            return _finish(page)

        # Wait for Microsoft email field
        try:
            page.wait_for_selector('input[name="loginfmt"], input[type="email"]', timeout=15_000)
        except PlaywrightTimeout:
            url = page.url
            _cleanup()
            return _set(status="error", message=f"Could not reach Microsoft login page. Landed on: {url}")

        # Fill email and click Next
        page.fill('input[name="loginfmt"]', email)
        page.click('#idSIButton9')

        # Wait for password field
        try:
            page.wait_for_selector('input[name="passwd"]', timeout=15_000)
        except PlaywrightTimeout:
            url = page.url
            _cleanup()
            return _set(status="error", message=f"Email step failed or not recognised. Page: {url}")

        # Check for email-step error (e.g. account not found)
        if _has_error(page):
            msg = _error_text(page)
            _cleanup()
            return _set(status="error", message=msg or f"Email not recognised. Page: {page.url}")

        # Fill password and sign in
        page.fill('input[name="passwd"]', password)
        page.click('#idSIButton9')
        page.wait_for_load_state("networkidle", timeout=15_000)

        # Check for bad credentials
        if _has_error(page):
            msg = _error_text(page)
            _cleanup()
            return _set(status="error", message=msg or f"Incorrect password. Page: {page.url}")

        # Already on Canvas (no 2FA)?
        if _on_canvas(page):
            return _finish(page)

        # Detect 2FA type
        twofa = _detect_2fa(page)

        if twofa == "code":
            prompt = _get_2fa_prompt(page)
            _set(status="needs_code", prompt=prompt)
            return {"status": "needs_code", "prompt": prompt}

        if twofa == "push":
            prompt = _get_2fa_prompt(page)
            _set(status="needs_push", prompt=prompt)
            # Wait for phone approval in background
            t = threading.Thread(target=_wait_for_push, daemon=True)
            t.start()
            return {"status": "needs_push", "prompt": prompt}

        # "Stay signed in?" prompt — click No and proceed
        if _has_stay_signed_in(page):
            _click(page, '#idBtn_Back, input[value="No"]')
            page.wait_for_load_state("networkidle", timeout=10_000)
            if _on_canvas(page):
                return _finish(page)

        _cleanup()
        return _set(status="error",
                    message=f"Unexpected page after login: {page.url}. "
                            "Howard may have changed their SSO flow.")

    except PlaywrightTimeout:
        _cleanup()
        return _set(status="error", message="Login timed out. Check your credentials and try again.")
    except Exception as e:
        _cleanup()
        return _set(status="error", message=str(e))


def submit_code(code: str) -> dict:
    """
    Submit a 2FA verification code (TOTP / SMS).

    Returns one of:
      {'status': 'success', 'token': '...'}
      {'status': 'error',   'message': '...'}
    """
    with _lock:
        page = _session.get("page")

    if not page:
        return _set(status="error", message="No active login session. Please start over.")

    try:
        _wait_and_fill(page, 'input[name="otc"], input[name="code"], input[autocomplete="one-time-code"]', code)
        _click(page, '#idSubmit_SAOTCC_Continue, #idSIButton9, input[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=15_000)

        if _has_error(page):
            return _set(status="error", message=_error_text(page) or "Invalid code. Please try again.")

        if _has_stay_signed_in(page):
            _click(page, '#idBtn_Back, input[value="No"]')
            page.wait_for_load_state("networkidle", timeout=10_000)

        if _on_canvas(page):
            return _finish(page)

        return _set(status="error", message="Code accepted but could not reach Canvas.")

    except PlaywrightTimeout:
        _cleanup()
        return _set(status="error", message="Timed out after code submission.")
    except Exception as e:
        _cleanup()
        return _set(status="error", message=str(e))


def get_status() -> dict:
    """Return the current auth state (for polling)."""
    with _lock:
        return dict(_state)


# ─────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────

def _wait_for_push():
    """Background thread: poll until Microsoft push is approved or times out."""
    with _lock:
        page = _session.get("page")
    if not page:
        return

    try:
        for _ in range(150):   # 5 minutes
            time.sleep(2)
            try:
                if _has_stay_signed_in(page):
                    _click(page, '#idBtn_Back, input[value="No"]')
                    page.wait_for_load_state("networkidle", timeout=10_000)

                if _on_canvas(page):
                    _finish(page)
                    return
            except Exception:
                pass

        _set(status="error", message="Push notification timed out. Please try again.")
    except Exception as e:
        _set(status="error", message=str(e))
    finally:
        _cleanup()


def _finish(page) -> dict:
    """Generate a Canvas API token and return success."""
    token = _generate_api_token(page)
    _cleanup()
    if token:
        return _set(status="success", token=token)
    return _set(status="error",
                message="Logged in but could not generate a Canvas API token.")


def _generate_api_token(page) -> str | None:
    try:
        page.goto(f"{CANVAS_URL}/profile/settings", wait_until="networkidle", timeout=15_000)

        btn = page.locator(
            'a[href="#access_token_form"], .add_access_token_link, '
            'button:has-text("New Access Token"), a:has-text("New Access Token")'
        ).first
        btn.click()

        page.wait_for_selector(
            '#access_token_form, #access-token-form, [data-testid="access-token-form"]',
            timeout=8_000
        )

        purpose = page.locator('input[name="access_token[purpose]"], #access_token_purpose').first
        if purpose.count() > 0:
            purpose.fill("Canvas Notifier")

        page.locator('button:has-text("Generate Token"), input[value="Generate Token"]').first.click()

        page.wait_for_selector(
            '.visible_token, #token_value, [data-testid="access-token-value"], input.token-value',
            timeout=10_000
        )

        for sel in ['.visible_token', '#token_value', '[data-testid="access-token-value"]', 'input.token-value']:
            el = page.locator(sel).first
            if el.count() > 0:
                tag   = el.evaluate("e => e.tagName")
                token = el.input_value() if tag == "INPUT" else el.text_content()
                token = (token or "").strip()
                if len(token) > 10:
                    return token
        return None
    except Exception:
        return None


def _detect_2fa(page) -> str | None:
    """Return 'code', 'push', or None."""
    html = page.content().lower()
    if any(k in html for k in ["otc", "verification code", "enter the code", "one-time"]):
        return "code"
    if any(k in html for k in ["approve sign in", "open your authenticator", "push notification", "number matching"]):
        return "push"
    return None


def _get_2fa_prompt(page) -> str:
    for sel in [".text-title", "#idDiv_SAOTCS_Title", "#idDiv_SAOTCC_Title", "h1", ".title"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                text = el.text_content().strip()
                if text:
                    return text
        except Exception:
            pass
    return "Complete two-factor authentication."


def _has_error(page) -> bool:
    try:
        err = page.locator('#idTd_Tile_ErrorMessage, .alert-error, [aria-live="assertive"]').first
        return err.count() > 0 and bool((err.text_content() or "").strip())
    except Exception:
        return False


def _error_text(page) -> str:
    try:
        return page.locator('#idTd_Tile_ErrorMessage, .alert-error, [aria-live="assertive"]').first.text_content().strip()
    except Exception:
        return ""


def _on_canvas(page) -> bool:
    try:
        url = page.url
        return CANVAS_URL in url and (
            "/dashboard" in url
            or url.rstrip("/") == CANVAS_URL
            or page.locator("#dashboard_header_container, .ic-Dashboard-header").count() > 0
        )
    except Exception:
        return False


def _has_stay_signed_in(page) -> bool:
    try:
        return page.locator('#idBtn_Back, input[value="No"]').count() > 0
    except Exception:
        return False


def _wait_and_fill(page, selector: str, value: str):
    page.wait_for_selector(selector, timeout=10_000)
    page.fill(selector.split(",")[0].strip(), value)


def _click(page, selector: str):
    page.locator(selector).first.click()


def _set(**kwargs) -> dict:
    with _lock:
        _state.clear()
        _state.update(kwargs)
    return dict(kwargs)


def _cleanup():
    with _lock:
        pw      = _session.pop("pw", None)
        browser = _session.pop("browser", None)
        _session.pop("page", None)
    try:
        browser.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
