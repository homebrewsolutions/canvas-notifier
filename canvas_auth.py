"""
canvas_auth.py — Non-headless Canvas login via Playwright.

Opens a real visible browser so the user can complete Microsoft SSO
and 2FA naturally. After the user logs in, automatically navigates to
Canvas profile settings, generates an API token, and closes the browser.

Call start_browser_login() to kick off the background thread, then
poll get_login_result() for status updates.
"""

import time
import threading
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CANVAS_URL   = "https://howard.instructure.com"
LOGIN_TIMEOUT = 180  # seconds the user has to complete login

_lock   = threading.Lock()
_result = {"status": "idle"}   # idle | pending | success | error


def start_browser_login():
    """
    Launch a visible browser window and begin the login flow in a background thread.
    The user must complete Microsoft SSO + 2FA in the opened window.
    """
    with _lock:
        _result.clear()
        _result["status"] = "pending"

    t = threading.Thread(target=_login_thread, daemon=True)
    t.start()


def get_login_result() -> dict:
    """Return a copy of the current login result."""
    with _lock:
        return dict(_result)


# ─────────────────────────────────────────────
#  Internal
# ─────────────────────────────────────────────

def _login_thread():
    playwright = browser = None
    try:
        playwright = sync_playwright().start()
        browser    = playwright.chromium.launch(headless=False)
        page       = browser.new_page()

        # Go to Canvas — Howard will redirect to Microsoft SSO automatically
        page.goto(f"{CANVAS_URL}/login/saml", timeout=30_000)

        # Wait for the user to finish logging in (up to LOGIN_TIMEOUT seconds)
        logged_in = _wait_for_login(page)

        if not logged_in:
            _set(status="error", message="Login timed out. Please try again.")
            return

        # User is on Canvas — quietly generate an API token in the same session
        token = _generate_api_token(page)

        if token:
            _set(status="success", token=token)
        else:
            _set(status="error",
                 message="Logged in, but could not generate a Canvas API token. "
                         "Try going to Canvas → Settings → New Access Token manually.")

    except PlaywrightTimeout:
        _set(status="error", message="Browser timed out. Please try again.")
    except Exception as e:
        _set(status="error", message=str(e))
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass


def _wait_for_login(page) -> bool:
    """Poll every second until the user reaches the Canvas dashboard or times out."""
    for _ in range(LOGIN_TIMEOUT):
        time.sleep(1)
        try:
            url = page.url
            if CANVAS_URL not in url:
                continue
            on_dashboard = (
                "/dashboard" in url
                or url.rstrip("/") == CANVAS_URL
                or page.locator(
                    "#dashboard_header_container, "
                    ".ic-Dashboard-header, "
                    "#application"
                ).count() > 0
            )
            if on_dashboard:
                return True
        except Exception:
            # Page may be navigating; keep waiting
            pass
    return False


def _generate_api_token(page) -> str | None:
    """Navigate to profile settings and create a new Canvas API access token."""
    try:
        page.goto(f"{CANVAS_URL}/profile/settings",
                  wait_until="networkidle", timeout=15_000)

        # Click "New Access Token"
        btn = page.locator(
            'a[href="#access_token_form"], '
            '.add_access_token_link, '
            'button:has-text("New Access Token"), '
            'a:has-text("New Access Token")'
        ).first
        btn.click()

        # Wait for the modal/form
        page.wait_for_selector(
            '#access_token_form, #access-token-form, '
            '[data-testid="access-token-form"]',
            timeout=8_000
        )

        # Fill in a purpose so it's identifiable later
        purpose = page.locator(
            'input[name="access_token[purpose]"], #access_token_purpose'
        ).first
        if purpose.count() > 0:
            purpose.fill("Canvas Notifier")

        # Submit
        page.locator(
            'button:has-text("Generate Token"), input[value="Generate Token"]'
        ).first.click()

        # Wait for the token value to appear
        page.wait_for_selector(
            '.visible_token, #token_value, '
            '[data-testid="access-token-value"], input.token-value',
            timeout=10_000
        )

        # Extract the token text
        for sel in [
            '.visible_token',
            '#token_value',
            '[data-testid="access-token-value"]',
            'input.token-value',
        ]:
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


def _set(**kwargs):
    with _lock:
        _result.clear()
        _result.update(kwargs)
