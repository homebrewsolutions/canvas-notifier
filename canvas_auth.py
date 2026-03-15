"""
canvas_auth.py — Headless Microsoft SSO login for Howard Canvas.

ALL Playwright operations run inside a single dedicated background thread.
sync_playwright is tied to the greenlet/thread it was created in — calling
page methods from a different thread raises "Cannot switch to a different
thread". The fix: one thread owns the browser for its entire lifetime.

Flow:
  start_login()  → spawns _login_thread, blocks up to 60s for 2FA state
  submit_code()  → sends code to the thread via queue, blocks for result
  get_status()   → returns current state (polled by frontend for push flow)
"""

import re
import time
import threading
import queue
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CANVAS_URL = "https://howard.instructure.com"

_lock    = threading.Lock()
_state   = {"status": "idle"}

# Queues for communicating between Flask request threads and the login thread.
# _init_q  : login thread → start_login  (2FA state: needs_push / needs_code / error)
# _code_q  : submit_code  → login thread (the OTP code string)
# _final_q : login thread → submit_code  (result after code submission)
_init_q  = queue.Queue(maxsize=1)
_code_q  = queue.Queue(maxsize=1)
_final_q = queue.Queue(maxsize=1)


# ─────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────

def start_login(email: str, password: str) -> dict:
    """
    Kick off the SSO login in a background thread.
    Blocks until credential submission + 2FA detection completes (≤60s).
    """
    _flush_queues()
    _set(status="pending")
    threading.Thread(target=_login_thread, args=(email, password), daemon=True).start()
    try:
        return _init_q.get(timeout=60)
    except queue.Empty:
        return _set(status="error", message="Login timed out. Please try again.")


def submit_code(code: str) -> dict:
    """
    Send a 2FA code to the login thread and wait for the result (≤30s).
    """
    try:
        _code_q.put_nowait(code)
    except queue.Full:
        return _set(status="error", message="No active login session. Please start over.")
    try:
        return _final_q.get(timeout=30)
    except queue.Empty:
        return _set(status="error", message="Timed out after code submission.")


def get_status() -> dict:
    """Return current auth state (polled by frontend during push flow)."""
    with _lock:
        return dict(_state)


# ─────────────────────────────────────────────
#  Login thread — owns the browser for its entire lifetime
# ─────────────────────────────────────────────

def _login_thread(email: str, password: str):
    pw = browser = None
    try:
        pw      = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        # ── Navigate to Canvas (redirects to Microsoft SSO) ──────────────
        page.goto(CANVAS_URL, wait_until="load", timeout=30_000)

        if _on_canvas(page):
            _init_q.put(_finish(page))
            return

        # ── Microsoft email step ──────────────────────────────────────────
        try:
            page.wait_for_selector('input[name="loginfmt"], input[type="email"]', timeout=15_000)
        except PlaywrightTimeout:
            _init_q.put(_set(status="error", message=f"Could not reach Microsoft login. Landed on: {page.url}"))
            return

        page.fill('input[name="loginfmt"]', email)
        page.click('#idSIButton9')

        # ── Password step ─────────────────────────────────────────────────
        try:
            page.wait_for_selector('input[name="passwd"]', timeout=15_000)
        except PlaywrightTimeout:
            _init_q.put(_set(status="error", message=f"Email step failed. Page: {page.url}"))
            return

        if _has_error(page):
            _init_q.put(_set(status="error", message=_error_text(page) or "Email not recognised."))
            return

        page.fill('input[name="passwd"]', password)
        page.click('#idSIButton9')
        page.wait_for_load_state("load", timeout=15_000)

        if _has_error(page):
            _init_q.put(_set(status="error", message=_error_text(page) or "Incorrect password."))
            return

        if _on_canvas(page):
            _init_q.put(_finish(page))
            return

        # ── 2FA detection ─────────────────────────────────────────────────
        print(f"[2fa] detecting, url={page.url}", flush=True)
        print(f"[2fa] page title={page.title()}", flush=True)
        twofa = _detect_2fa(page)
        print(f"[2fa] detected type={twofa}", flush=True)

        # ── Push / number-matching ────────────────────────────────────────
        if twofa == "push":
            prompt = _get_2fa_prompt(page)
            number = _get_display_number(page)
            _init_q.put(_set(status="needs_push", prompt=prompt, number=number))
            # Wait for approval in THIS thread (no cross-thread Playwright calls)
            _wait_for_push(page)
            return

        # ── Code entry ────────────────────────────────────────────────────
        if twofa == "code":
            prompt = _get_2fa_prompt(page)
            _init_q.put(_set(status="needs_code", prompt=prompt))

            # Wait for submit_code() to provide the code
            try:
                code = _code_q.get(timeout=120)
            except queue.Empty:
                _final_q.put(_set(status="error", message="Timed out waiting for code."))
                return

            # Fill the code input
            filled = False
            for sel in ['input[name="otc"]', 'input[name="code"]', 'input[autocomplete="one-time-code"]']:
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    page.fill(sel, code)
                    filled = True
                    break
                except PlaywrightTimeout:
                    continue

            if not filled:
                _final_q.put(_set(status="error", message="Could not find the code input. Please try again."))
                return

            page.locator('#idSubmit_SAOTCC_Continue, #idSIButton9, input[type="submit"]').first.click()
            page.wait_for_load_state("load", timeout=20_000)

            if _has_error(page):
                _final_q.put(_set(status="error", message=_error_text(page) or "Invalid code."))
                return

            if _has_stay_signed_in(page):
                page.locator('#idBtn_Back, button:has-text("No"), input[value="No"]').first.click()
                page.wait_for_load_state("load", timeout=10_000)

            if not _on_canvas(page):
                try:
                    page.wait_for_url(f"*{CANVAS_URL}*", timeout=15_000)
                except PlaywrightTimeout:
                    page.goto(CANVAS_URL, wait_until="load", timeout=20_000)

            _final_q.put(_finish(page))
            return

        # ── "Stay signed in?" with no 2FA ────────────────────────────────
        if _has_stay_signed_in(page):
            page.locator('#idBtn_Back, input[value="No"]').first.click()
            page.wait_for_load_state("load", timeout=10_000)
            if _on_canvas(page):
                _init_q.put(_finish(page))
                return

        _init_q.put(_set(status="error",
                         message=f"Unexpected page after login: {page.url}"))

    except PlaywrightTimeout:
        result = _set(status="error", message="Login timed out. Check your credentials and try again.")
        _safe_put(_init_q, result)
        _safe_put(_final_q, result)
    except Exception as e:
        result = _set(status="error", message=str(e))
        _safe_put(_init_q, result)
        _safe_put(_final_q, result)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def _wait_for_push(page):
    """
    Wait for Authenticator approval — runs INSIDE the login thread.
    All page calls are safe here because we own the Playwright instance.
    """
    start_url = page.url
    print(f"[push] waiting, start: {start_url}", flush=True)

    for _ in range(150):  # up to 5 minutes
        time.sleep(2)
        try:
            url = page.url
            print(f"[push] url: {url}", flush=True)

            # On Canvas — done
            if CANVAS_URL in url:
                print("[push] on canvas", flush=True)
                _finish(page)
                return

            # "Stay signed in?" — dismiss and let Microsoft redirect
            if _has_stay_signed_in(page):
                print("[push] dismissing stay-signed-in", flush=True)
                page.locator('#idBtn_Back, button:has-text("No"), input[value="No"]').first.click()
                continue

            # Navigated to a different Microsoft page (post-approval intermediate)
            if url != start_url and _is_microsoft(url):
                print("[push] intermediate microsoft page, going to canvas", flush=True)
                try:
                    page.goto(CANVAS_URL, wait_until="load", timeout=20_000)
                except PlaywrightTimeout:
                    pass
                if _on_canvas(page):
                    _finish(page)
                return

            # URL unchanged but number element gone → SPA approved
            gone = page.locator('#idRichContext_DisplaySign, #displaySign, .displaySign').count() == 0
            if gone:
                print("[push] number element gone, going to canvas", flush=True)
                try:
                    page.goto(CANVAS_URL, wait_until="load", timeout=20_000)
                except PlaywrightTimeout:
                    pass
                if _on_canvas(page):
                    _finish(page)
                return

        except Exception as e:
            print(f"[push] exception: {e}", flush=True)
            err = str(e).lower()
            if any(k in err for k in ["closed", "target", "destroyed"]):
                _set(status="error", message="Browser session lost. Please try again.")
                return

    _set(status="error", message="Push notification timed out. Please try again.")


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _finish(page) -> dict:
    cookies = _extract_cookies(page)
    if cookies:
        return _set(status="success", cookies=cookies)
    return _set(status="error", message="Logged in but could not extract Canvas session cookies.")


def _extract_cookies(page) -> dict | None:
    """Extract Canvas session cookies from the logged-in browser."""
    try:
        # Make sure we're on Canvas first
        if CANVAS_URL not in page.url:
            page.goto(CANVAS_URL, wait_until="load", timeout=15_000)

        cookies = page.context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies if CANVAS_URL.split("//")[1] in c.get("domain", "")}
        print(f"[cookies] extracted {len(cookie_dict)} canvas cookies", flush=True)

        if cookie_dict:
            return cookie_dict

        print("[cookies] ERROR: no canvas cookies found", flush=True)
        return None
    except Exception as e:
        print(f"[cookies] ERROR: {e}", flush=True)
        return None


def _detect_2fa(page) -> str | None:
    number_match_sel = (
        '#idRichContext_DisplaySign, #displaySign, .displaySign, '
        '[data-bind*="DisplaySign"], #idDiv_SAOTCC_DisplaySign'
    )
    code_input_sel = 'input[name="otc"], input[name="code"], input[autocomplete="one-time-code"]'

    try:
        page.wait_for_selector(f'{number_match_sel}, {code_input_sel}', timeout=10_000)
    except PlaywrightTimeout:
        print("[2fa] timed out waiting for 2fa elements", flush=True)

    for sel in number_match_sel.split(', '):
        try:
            count = page.locator(sel.strip()).count()
            print(f"[2fa] number_match sel={sel.strip()} count={count}", flush=True)
            if count > 0:
                return "push"
        except Exception as e:
            print(f"[2fa] number_match sel={sel.strip()} error={e}", flush=True)

    for sel in code_input_sel.split(', '):
        try:
            el = page.locator(sel.strip()).first
            count = el.count()
            visible = el.is_visible() if count > 0 else False
            print(f"[2fa] code_input sel={sel.strip()} count={count} visible={visible}", flush=True)
            if count > 0 and visible:
                return "code"
        except Exception as e:
            print(f"[2fa] code_input sel={sel.strip()} error={e}", flush=True)

    html = page.content().lower()
    push_keywords = ["enter the number shown", "number shown", "approve sign in",
                     "open your authenticator", "push notification", "number matching"]
    code_keywords = ["verification code", "enter the code", "one-time", "otc"]
    matched_push = [k for k in push_keywords if k in html]
    matched_code = [k for k in code_keywords if k in html]
    print(f"[2fa] text fallback: push_keywords={matched_push} code_keywords={matched_code}", flush=True)

    if matched_push:
        return "push"
    if matched_code:
        return "code"
    return None


def _get_display_number(page) -> str | None:
    for sel in ['#idRichContext_DisplaySign', '#displaySign', '.displaySign',
                '[data-bind*="DisplaySign"]', '#idDiv_SAOTCC_DisplaySign']:
        try:
            page.wait_for_selector(sel, timeout=5_000)
            el = page.locator(sel).first
            if el.count() > 0:
                tag  = el.evaluate("e => e.tagName").upper()
                text = (el.input_value() if tag == "INPUT" else el.text_content() or "").strip()
                if text:
                    return text
        except PlaywrightTimeout:
            continue
        except Exception:
            continue

    try:
        match = re.search(r'(?<!\d)(\d{2})(?!\d)', page.content())
        if match:
            return match.group(1)
    except Exception:
        pass
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
        return CANVAS_URL in page.url
    except Exception:
        return False


def _is_microsoft(url: str) -> bool:
    return any(d in url for d in ["microsoftonline.com", "microsoft.com", "live.com", "login.windows.net"])


def _has_stay_signed_in(page) -> bool:
    try:
        return page.locator('#idBtn_Back, input[value="No"]').count() > 0
    except Exception:
        return False


def _set(**kwargs) -> dict:
    with _lock:
        _state.clear()
        _state.update(kwargs)
    return dict(kwargs)


def _safe_put(q: queue.Queue, item):
    """Put item into queue without blocking (drop if full)."""
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


def _flush_queues():
    """Drain all queues before starting a new login."""
    for q in (_init_q, _code_q, _final_q):
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break
