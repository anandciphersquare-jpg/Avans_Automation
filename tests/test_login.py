"""
Authentication & Session, UI: sign-in form, location gate, OTP step, full
sign-in, the `next` redirect, session handling and Forgot password.
Test case ids: AUTH-UI-001 .. AUTH-UI-072.

Live rules (2026-10-21):
    Sign in      #email (type=email) + #password; both mandatory; email format checked
    Location     Sign in stays disabled until the browser reports a position
    OTP          6 boxes 'Digit 1..6', digits only; 'Verify and sign in' enabled at 6;
                 'Send a new code in Ns' countdown; 'Use a different account'
    Session      token in sessionStorage 'sprintexcrow.session' (per tab, ~30 min)

Account safety: only AUTH-UI-020 sends a wrong password for the real account
(once per run), so the suite never locks the admin out.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import pytest

from config.settings import settings
from pages.dashboard_page import DashboardPage
from pages.login_page import MSG, LoginPage
from utils.assertions import INVALID_EMAILS, SQLI_PAYLOADS, XSS_PAYLOADS
from utils.checks import check

pytestmark = [pytest.mark.auth, pytest.mark.ui]

requires_admin = pytest.mark.skipif(not settings.has_admin_creds, reason="set ADMIN_EMAIL / ADMIN_PASSWORD")
APP_HOST = urlsplit(settings.base_url).netloc
SESSION_KEY = "sprintexcrow.session"
PROTECTED = ["/dashboard", "/beneficiaries", "/transfers", "/audit-trail", "/users", "/change-password"]


def _login_calls(page) -> list[str]:
    """Collect every POST to /auth/login made by the page."""
    calls: list[str] = []
    page.on("request", lambda r: calls.append(r.url) if r.method == "POST" and r.url.endswith("/auth/login") else None)
    return calls


def _reach_otp_step(page) -> LoginPage:
    lp = LoginPage(page).open()
    lp.enter_credentials(settings.admin_email, settings.admin_password)
    lp.submit()
    try:
        page.get_by_role("heading", name="Enter the code").wait_for(timeout=30_000)
    except Exception:  # noqa: BLE001
        pytest.fail(f"OTP step not reached after valid credentials; the form shows: {lp.form_alert(1000)!r}")
    return lp


def _session(page) -> dict:
    raw = page.evaluate(f"sessionStorage.getItem('{SESSION_KEY}')")
    return json.loads(raw) if raw else {}


# ====================================================== sign-in form layout
@pytest.mark.smoke
@pytest.mark.positive
def test_sign_in_page_layout(page):
    """AUTH-UI-001 — Sign-in page shows heading, Email, Password, Forgot password? and Sign in."""
    LoginPage(page).open()
    body = page.inner_text("body")
    for text in ("Sign in", "Enter your credentials to access the console.", "Forgot password?"):
        check(text in body, "Sign-in page content", f"text '{text}' on the page", "not found")
    email, pwd = page.locator("#email"), page.locator("#password")
    check(email.get_attribute("type") == "email", "Email field type", "type=email", email.get_attribute("type"))
    check(pwd.get_attribute("type") == "password", "Password is masked", "type=password", pwd.get_attribute("type"),
          hint="a plain-text password field exposes the password on screen")
    check(email.get_attribute("autocomplete") == "username" and pwd.get_attribute("autocomplete") == "current-password",
          "Autocomplete hints", "username / current-password",
          f"{email.get_attribute('autocomplete')} / {pwd.get_attribute('autocomplete')}")


@pytest.mark.security
def test_password_not_in_url_after_submit(page):
    """AUTH-UI-002 — submitting the form never puts the email/password in the URL."""
    lp = LoginPage(page).open()
    lp.enter_credentials("qa.nobody.7x@example.com", "Wrong@1234")
    lp.submit()
    lp.form_alert()
    check("Wrong@1234" not in page.url and "password=" not in page.url.lower(),
          "Credentials kept out of the URL", "URL without the password", page.url,
          hint="a GET form submission leaks the password into history and server logs")


# ============================================= mandatory fields (client side)
@pytest.mark.negative
@pytest.mark.parametrize("email,pwd,expect_email,expect_pwd", [
    ("", "", MSG["email_required"], MSG["password_required"]),
    ("qa.user@example.com", "", "", MSG["password_required"]),
    ("", "Secret@123", MSG["email_required"], ""),
    ("   ", "Secret@123", "any", ""),
], ids=["both_empty", "password_empty", "email_empty", "email_spaces"])
def test_mandatory_fields(page, email, pwd, expect_email, expect_pwd):
    """AUTH-UI-010 — Email and Password are mandatory; nothing is sent while one is empty."""
    calls = _login_calls(page)
    lp = LoginPage(page).open()
    lp.enter_credentials(email, pwd)
    lp.submit()
    page.wait_for_timeout(600)
    got_email, got_pwd = lp.field_error("email"), lp.field_error("password")
    if expect_email == "any":
        check(got_email, "Email of spaces only", "an email error", "no error shown")
    else:
        check(got_email == expect_email, "Email field message", repr(expect_email), repr(got_email))
    check(got_pwd == expect_pwd, "Password field message", repr(expect_pwd), repr(got_pwd))
    check(not calls, "No sign-in request with a missing field", "0 requests to /auth/login", f"{len(calls)} sent")


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("bad_email", INVALID_EMAILS)
def test_invalid_email_format(page, bad_email):
    """AUTH-UI-011 — malformed emails show the format message and are not sent."""
    calls = _login_calls(page)
    lp = LoginPage(page).open()
    lp.enter_credentials(bad_email, "Secret@123")
    lp.submit()
    page.wait_for_timeout(600)
    got = lp.field_error("email")
    check(got == MSG["email_format"], f"Email format check for {bad_email!r}", repr(MSG["email_format"]), repr(got))
    check(not calls, "No sign-in request for a malformed email", "0 requests", f"{len(calls)} sent")


# ========================================================= server refusals
@requires_admin
@pytest.mark.negative
def test_wrong_password_rejected(page):
    """AUTH-UI-020 — a wrong password shows 'Invalid email or password.' and does not sign in.
    (The only wrong-password attempt on the real account per run.)"""
    lp = LoginPage(page).open()
    lp.enter_credentials(settings.admin_email, "Wrong@Pass1")
    lp.submit()
    got = lp.form_alert()
    check(got == MSG["bad_credentials"], "Wrong password message", repr(MSG["bad_credentials"]), repr(got))
    check(not lp.on_otp_step() and "/login" in page.url, "Wrong password does not continue",
          "still on the sign-in form", page.url)


@pytest.mark.security
def test_unknown_email_same_message(page):
    """AUTH-UI-021 — an unknown email gets the SAME message as a wrong password
    (no 'user not found', so accounts cannot be discovered)."""
    lp = LoginPage(page).open()
    lp.enter_credentials("qa.nobody.7x@example.com", "Wrong@Pass1")
    lp.submit()
    got = lp.form_alert()
    check(got == MSG["bad_credentials"], "Unknown-email message", repr(MSG["bad_credentials"]), repr(got),
          hint="a different message for unknown emails lets attackers list valid accounts")


@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_in_sign_in(page, payload):
    """AUTH-UI-022 — SQL in email/password never signs in and never shows a database error."""
    lp = LoginPage(page).open()
    lp.enter_credentials(payload, payload)
    lp.submit()
    page.wait_for_timeout(1500)
    body = page.inner_text("body").lower()
    check("/login" in page.url and not lp.on_otp_step(), "SQL payload refused", "still on sign-in", page.url,
          hint="the payload got past the credential check")
    check(not any(s in body for s in ("sql", "syntax error", "exception")), "No database error shown",
          "no SQL/exception text", "database error text on the page")


@pytest.mark.security
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_xss_in_sign_in_fields(page, payload):
    """AUTH-UI-023 — script payloads in the sign-in fields never execute."""
    fired = []
    page.on("dialog", lambda d: (fired.append(d.message), d.dismiss()))
    lp = LoginPage(page).open()
    lp.enter_credentials(payload, payload)
    lp.submit()
    page.wait_for_timeout(1000)
    check(not fired, "Script payload in sign-in", "no alert dialog", f"dialog fired: {fired}")


# ============================================================ location gate
def test_location_denied_blocks_sign_in(browser):
    """AUTH-UI-030 — with location blocked, a clear notice shows and Sign in stays disabled."""
    context = browser.new_context(locale="en-IN", permissions=[])
    page = context.new_page()
    try:
        lp = LoginPage(page).open()
        page.get_by_text(MSG["location_denied_title"]).wait_for(timeout=15_000)
        lp.enter_credentials("qa.user@example.com", "Secret@123")
        banner = lp.location_banner()
        check(MSG["location_denied_title"] in banner, "Location notice", MSG["location_denied_title"], banner)
        check("Try again" in banner, "Retry offered", "'Try again' link in the notice", banner)
        check(lp.sign_in_button().is_disabled(), "Sign in without location", "button disabled",
              "button enabled", hint="sign-in must require location")
    finally:
        context.close()


@pytest.mark.positive
def test_location_granted_enables_sign_in(page):
    """AUTH-UI-031 — with location allowed, no notice is shown and Sign in is enabled."""
    lp = LoginPage(page).open()
    lp.wait_location_ready()
    check(not lp.location_banner(), "No location notice when allowed", "no notice", lp.location_banner())


# ===================================================================== OTP ========================================
@requires_admin
@pytest.mark.positive
def test_valid_credentials_open_otp_step(page):
    """AUTH-UI-040 — correct credentials open 'Enter the code' with a masked email and 6 boxes."""
    _reach_otp_step(page)
    text = page.locator("form[aria-labelledby='otp-heading']").inner_text()
    check("We sent a 6-digit code to" in text, "OTP step text", "'We sent a 6-digit code to …'", text[:120])
    check("•" in text and settings.admin_email not in text, "Email masked on the OTP step",
          "masked address (a••••r@…)", text[:160], hint="the full email should not be shown")
    check(LoginPage(page).otp_inputs().count() == 6, "OTP boxes", "6", LoginPage(page).otp_inputs().count())


@requires_admin
@pytest.mark.boundary
def test_verify_enabled_only_at_six_digits(page):
    """AUTH-UI-041 — 'Verify and sign in' stays disabled for 0-5 digits and enables at 6."""
    lp = _reach_otp_step(page)
    boxes = lp.otp_inputs()
    for n in range(6):
        check(lp.verify_button().is_disabled(), f"Verify with {n} digits", "disabled", "enabled")
        boxes.nth(n).fill(str(n + 1))
    check(lp.verify_button().is_enabled(), "Verify with 6 digits", "enabled", "disabled")


@requires_admin
@pytest.mark.negative
def test_otp_boxes_accept_digits_only(page):
    """AUTH-UI-042 — letters and symbols typed into the OTP boxes are ignored."""
    lp = _reach_otp_step(page)
    first = lp.otp_inputs().nth(0)
    first.press_sequentially("a@ ")
    check(first.input_value() == "", "OTP box with letters/symbols", "box stays empty", repr(first.input_value()))


@requires_admin
@pytest.mark.positive
def test_otp_paste_fills_all_boxes(page):
    """AUTH-UI-043 — pasting a 6-digit code fills all six boxes."""
    lp = _reach_otp_step(page)
    lp.otp_inputs().nth(0).fill("123456")
    got = "".join(lp.otp_inputs().nth(i).input_value() for i in range(6))
    check(got == "123456", "Pasted code spread across the boxes", "123456", got)


@requires_admin
@pytest.mark.negative
def test_wrong_otp_rejected(page):
    """AUTH-UI-044 — a wrong code shows an error, clears the boxes and does not sign in."""
    lp = _reach_otp_step(page)
    lp.enter_otp("000000")
    lp.verify_button().click()
    err = lp.otp_error()
    check(err, "Wrong OTP message", "an error under the code boxes", "no message",
          hint="the user is not told the code was wrong")
    check("/login" in page.url, "Wrong OTP does not sign in", "still on /login", page.url)
    left = "".join(lp.otp_inputs().nth(i).input_value() for i in range(lp.otp_inputs().count()))
    check(left == "", "Boxes cleared after a wrong code", "empty boxes", repr(left))


@requires_admin
@pytest.mark.positive
def test_resend_has_countdown(page):
    """AUTH-UI-045 — 'Send a new code' starts disabled with a seconds countdown."""
    lp = _reach_otp_step(page)
    btn = lp.resend_button()
    label = btn.inner_text()
    check(re.match(r"Send a new code in \d+s", label), "Resend label", "'Send a new code in Ns'", label)
    check(btn.is_disabled(), "Resend during the countdown", "disabled", "enabled",
          hint="without a cool-down a user (or script) can flood the mailbox")


@requires_admin
@pytest.mark.positive
def test_use_different_account_returns_to_sign_in(page):
    """AUTH-UI-046 — 'Use a different account' goes back to the sign-in form."""
    lp = _reach_otp_step(page)
    lp.use_different_account()
    check(page.locator("#email").is_visible() and not lp.on_otp_step(), "Back to sign-in",
          "Email field visible", "still on the OTP step")


@requires_admin
@pytest.mark.functional
def test_refresh_on_otp_returns_to_sign_in(page):
    """AUTH-UI-047 — refreshing on the OTP step returns to the sign-in form (no half session)."""
    _reach_otp_step(page)
    page.reload()
    page.locator("#email").wait_for(timeout=15_000)
    check(not _session(page), "No session before the OTP", "empty sessionStorage", _session(page))


@requires_admin
@pytest.mark.security
def test_cannot_skip_otp_by_url(page):
    """AUTH-UI-048 — after the password step, opening /dashboard directly still needs sign-in."""
    _reach_otp_step(page)
    page.goto(settings.url("/dashboard"))
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    check("/login" in page.url, "OTP cannot be skipped", "redirect to /login", page.url,
          hint="the password alone must never give access")


# ======================================================= full sign-in + next
@requires_admin
@pytest.mark.smoke
@pytest.mark.positive
def test_valid_login_lands_on_dashboard(page):
    """AUTH-UI-050 — email + password + OTP signs in to the dashboard; the session is
    kept in this tab only (sessionStorage) and expires in about 30 minutes."""
    LoginPage(page).open().login(settings.admin_email, settings.admin_password)
    page.wait_for_load_state("networkidle")
    check(DashboardPage(page).is_menu_enabled("Dashboard"), "Side menu after sign-in", "Dashboard menu", "missing")
    s = _session(page)
    check(s.get("accessToken"), "Session after sign-in", "token in sessionStorage", "none")
    local = page.evaluate("JSON.stringify(Object.entries(localStorage))")
    check(s["accessToken"] not in local, "Token not in localStorage", "sessionStorage only",
          "token also in localStorage", hint="localStorage survives closing the browser")
    from datetime import datetime, timezone
    minutes = (datetime.fromisoformat(s["expiresAt"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 60
    check(0 < minutes <= 60, "Session lifetime", "expires within 60 minutes", f"{minutes:.0f} minutes")


@requires_admin
@pytest.mark.functional
def test_next_returns_to_requested_page(page):
    """AUTH-UI-051 — opening /beneficiaries signed-out goes to /login?next=… and,
    after sign-in, back to /beneficiaries."""
    page.goto(settings.url("/beneficiaries"))
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    check("next=%2Fbeneficiaries" in page.url, "Redirect keeps the target", "/login?next=%2Fbeneficiaries", page.url)
    LoginPage(page).login(settings.admin_email, settings.admin_password)
    page.wait_for_url(re.compile(r"/beneficiaries"), timeout=30_000)


@requires_admin
@pytest.mark.security
@pytest.mark.parametrize("target", ["//evil.example.com", "https://evil.example.com", "/\\evil.example.com"],
                         ids=["protocol_relative", "absolute_url", "backslash"])
def test_next_cannot_redirect_off_site(page, target):
    """AUTH-UI-052 — a `next` pointing to another site is ignored after sign-in (no open redirect)."""
    LoginPage(page).open(next_path=target).login(settings.admin_email, settings.admin_password)
    page.wait_for_timeout(2500)
    host = urlsplit(page.url).netloc
    check(host == APP_HOST, f"Sign-in with next={target}", f"stay on {APP_HOST}", page.url,
          hint="an open redirect lets phishing links send users to a fake site after a real sign-in")


# ================================================================== session
@pytest.mark.security
@pytest.mark.parametrize("path", PROTECTED)
def test_protected_page_needs_sign_in(page, path):
    """AUTH-UI-060 — every console page sends a signed-out visitor to /login?next=…"""
    page.goto(settings.url(path))
    try:
        page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    check("/login" in page.url, f"Signed-out visit to {path}", "redirect to /login", page.url)


@requires_admin
@pytest.mark.security
def test_new_tab_without_session_needs_sign_in(browser, _admin_storage_state):
    """AUTH-UI-061 — the sign-in lives in the tab: a new tab with only the saved cookies
    and local storage (no tab session) is not signed in."""
    from conftest import _context_kwargs
    context = browser.new_context(storage_state=_admin_storage_state, **_context_kwargs())
    page = context.new_page()
    try:
        page.goto(settings.url("/dashboard"))
        page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    finally:
        url = page.url
        context.close()
    check("/login" in url, "New tab without the tab session", "redirect to /login", url,
          hint="the session is meant to be tab-scoped (sessionStorage)")


@pytest.mark.security
@pytest.mark.parametrize("session", [
    {"accessToken": "abc.def.ghi", "expiresAt": "2099-01-01T00:00:00Z"},
    {"accessToken": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.", "expiresAt": "2099-01-01T00:00:00Z"},
    {"accessToken": "", "expiresAt": "2099-01-01T00:00:00Z"},
], ids=["garbage_token", "unsigned_token", "empty_token"])
def test_forged_session_rejected(browser, session):
    """AUTH-UI-062 — a forged token planted in sessionStorage does not open the console."""
    from conftest import _context_kwargs
    context = browser.new_context(**_context_kwargs())
    context.add_init_script(f"sessionStorage.setItem('{SESSION_KEY}', {json.dumps(json.dumps(session))})")
    page = context.new_page()
    try:
        page.goto(settings.url("/beneficiaries"))
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
        url = page.url
    finally:
        context.close()
    check("/login" in url or "Showing" not in body, "Forged token", "redirect to /login and no data",
          f"{url} — data visible: {'Showing' in body}", hint="the API must reject tokens it did not sign")


@requires_admin
@pytest.mark.security
def test_session_not_in_cookies_or_local_storage(logged_in_page):
    """AUTH-UI-063 — the access token is only in this tab's sessionStorage — not in
    cookies (no CSRF surface) or localStorage (survives browser close)."""
    token = _session(logged_in_page).get("accessToken", "")
    check(token, "Signed-in session", "token present", "none")
    cookies = json.dumps(logged_in_page.context.cookies())
    local = logged_in_page.evaluate("JSON.stringify(Object.entries(localStorage))")
    check(token not in cookies, "Token in cookies", "absent", "present")
    check(token not in local, "Token in localStorage", "absent", "present")


@requires_admin
@pytest.mark.security
def test_session_cookie_flags(logged_in_page):
    """AUTH-UI-064 — any session-like cookie is HttpOnly, Secure and SameSite."""
    cookies = [c for c in logged_in_page.context.cookies()
               if any(k in c["name"].lower() for k in ("sess", "token", "auth", "jwt", "sid"))]
    if not cookies:
        pytest.skip("No session cookie: the app keeps its token in sessionStorage (checked in AUTH-UI-063)")
    for c in cookies:
        check(c.get("httpOnly") and c.get("secure") and c.get("sameSite") in ("Lax", "Strict"),
              f"Cookie {c['name']} flags", "HttpOnly + Secure + SameSite Lax/Strict",
              f"httpOnly={c.get('httpOnly')} secure={c.get('secure')} sameSite={c.get('sameSite')}")


# ========================================================= forgot password
@pytest.mark.positive
def test_forgot_password_page(page):
    """AUTH-UI-070 — 'Forgot password?' opens the reset page with Email, Send reset link and Back to sign in."""
    lp = LoginPage(page).open()
    lp.open_forgot_password()
    body = page.inner_text("body")
    for text in ("Enter the email linked to your account", "Send reset link", "Back to sign in"):
        check(text in body, "Forgot password page", f"'{text}'", "not found")


@pytest.mark.negative
@pytest.mark.parametrize("email,expected", [("", MSG["email_required"]), ("abc", MSG["email_format"]),
                                            ("abc@", MSG["email_format"])], ids=["empty", "no_at", "no_domain"])
def test_forgot_password_email_validation(page, email, expected):
    """AUTH-UI-071 — the reset form checks the email before sending."""
    lp = LoginPage(page).open()
    lp.open_forgot_password()
    lp.request_reset(email)
    page.wait_for_timeout(600)
    got = lp.field_error("email")
    check(got == expected, f"Reset email {email!r}", repr(expected), repr(got))


@pytest.mark.security
def test_forgot_password_same_answer_for_unknown_email(page):
    """AUTH-UI-072 — an unknown email gets the same 'If an account exists for …' answer
    (no account discovery). Sends no mail."""
    lp = LoginPage(page).open()
    lp.open_forgot_password()
    lp.request_reset("qa.nobody.7x@example.com")
    page.get_by_text("Check your email").wait_for(timeout=15_000)
    body = page.inner_text("body")
    check(MSG["reset_sent"] in body and "not found" not in body.lower(), "Reset answer for an unknown email",
          "'If an account exists for …'", body[:200])
