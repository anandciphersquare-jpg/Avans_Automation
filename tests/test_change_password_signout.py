"""
Authentication & Session, UI: Change password validation and Sign out.
Test case ids: SES-001 .. SES-012.

Password rule (live build): 8-12 characters with a lowercase letter, an
uppercase letter, a digit and a symbol; must differ from the current one; the
last 3 passwords cannot be reused. No test here changes the real password:
every case is refused before or by the server.

SES-010..012 sign out of their OWN session (fixture `own_session_page`, a clean
browser with a fresh sign-in), so the shared admin session is never ended.
"""
from __future__ import annotations

import json
import re

import pytest

from api.api_client import ApiClient
from config.settings import settings
from pages.change_password_page import MSG, ChangePasswordPage
from utils.checks import check

pytestmark = [pytest.mark.auth, pytest.mark.ui]


def _cp_calls(page) -> list[str]:
    calls: list[str] = []
    page.on("request", lambda r: calls.append(r.url)
            if r.method == "POST" and r.url.endswith("/auth/change-password") else None)
    return calls


# ============================================================ change password
@pytest.mark.positive
def test_change_password_page_layout(logged_in_page):
    """SES-001 — Change password shows Current / New / Confirm fields, the rule and both buttons."""
    ChangePasswordPage(logged_in_page).open()
    body = logged_in_page.inner_text("body")
    for text in ("Current password", "New password", "Confirm new password",
                 "8 to 12 characters", "Change password and sign in again", "Back to the console"):
        check(text in body, "Change password page", f"'{text}'", "not found")
    for fid in ("currentPassword", "newPassword", "confirmPassword"):
        t = logged_in_page.locator(f"#{fid}").get_attribute("type")
        check(t == "password", f"{fid} masked", "type=password", t)


@pytest.mark.negative
def test_change_password_all_empty(logged_in_page):
    """SES-002 — submitting the empty form shows a message under each field and sends nothing."""
    cp = ChangePasswordPage(logged_in_page).open()
    calls = _cp_calls(logged_in_page)
    cp.submit()
    logged_in_page.wait_for_timeout(600)
    for fid, key in (("currentPassword", "current_required"), ("newPassword", "min_8"),
                     ("confirmPassword", "confirm_required")):
        got = cp.field_error(fid)
        check(got == MSG[key], f"Empty {fid}", repr(MSG[key]), repr(got))
    check(not calls, "No request with empty fields", "0 requests", f"{len(calls)} sent")


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("new,key", [
    ("Ab@1xyz", "min_8"), ("Abcd@12345678", "max_12"), ("ABCD@1234", "complexity"),
    ("abcd@1234", "complexity"), ("Abcd@xyzw", "complexity"), ("Abcd12345", "complexity"),
], ids=["7_chars", "13_chars", "no_lowercase", "no_uppercase", "no_digit", "no_symbol"])
def test_new_password_rules(logged_in_page, new, key):
    """SES-003 — a new password breaking the rule is refused with the matching message."""
    cp = ChangePasswordPage(logged_in_page).open()
    calls = _cp_calls(logged_in_page)
    cp.fill(current="Current@1", new=new)
    cp.submit()
    logged_in_page.wait_for_timeout(600)
    got = cp.field_error("newPassword")
    check(got == MSG[key], f"New password {new!r}", repr(MSG[key]), repr(got))
    check(not calls, "Weak password not sent", "0 requests", f"{len(calls)} sent")


@pytest.mark.positive
@pytest.mark.boundary
@pytest.mark.parametrize("new", ["Abcd@123", "Abcd@1234567"], ids=["8_chars", "12_chars"])
def test_new_password_length_limits_pass_client_check(logged_in_page, new):
    """SES-004 — 8 and 12 characters pass the client rule (the request is faked, nothing changes)."""
    cp = ChangePasswordPage(logged_in_page).open()
    sent = []

    def fake(route):
        sent.append(route.request.post_data)
        route.fulfill(status=400, content_type="application/json",
                      body=json.dumps({"success": False, "message": "QA: request intercepted",
                                       "data": {"code": "VALIDATION_ERROR"}}))

    logged_in_page.route("**/auth/change-password", fake)
    cp.fill(current="Current@1", new=new)
    cp.submit()
    logged_in_page.wait_for_timeout(1000)
    check(not cp.field_error("newPassword"), f"{len(new)}-character password", "no rule message",
          cp.field_error("newPassword"))
    check(len(sent) == 1, "Valid password sent to the server", "1 request", f"{len(sent)}")


@pytest.mark.negative
def test_confirm_password_mismatch(logged_in_page):
    """SES-005 — New and Confirm must match."""
    cp = ChangePasswordPage(logged_in_page).open()
    calls = _cp_calls(logged_in_page)
    cp.fill(current="Current@1", new="Abcd@1234", confirm="Abcd@9999")
    cp.submit()
    logged_in_page.wait_for_timeout(600)
    got = cp.field_error("confirmPassword")
    check(got == MSG["mismatch"], "Confirm mismatch", repr(MSG["mismatch"]), repr(got))
    check(not calls, "Mismatch not sent", "0 requests", f"{len(calls)} sent")


@pytest.mark.negative
def test_new_same_as_current(logged_in_page):
    """SES-006 — the new password cannot equal the current one."""
    cp = ChangePasswordPage(logged_in_page).open()
    cp.fill(current="Abcd@1234", new="Abcd@1234")
    cp.submit()
    logged_in_page.wait_for_timeout(600)
    got = cp.field_error("newPassword")
    check(got == MSG["same_as_current"], "New = current", repr(MSG["same_as_current"]), repr(got))


@pytest.mark.negative
def test_wrong_current_password_refused(logged_in_page):
    """SES-007 — a wrong current password (valid new one) is refused by the server and the user stays signed in."""
    cp = ChangePasswordPage(logged_in_page).open()
    cp.fill(current="Wrong@Cur1", new="Qa@New1234")
    with logged_in_page.expect_response(lambda r: r.url.endswith("/auth/change-password")) as resp:
        cp.submit()
    r = resp.value
    check(r.status not in (200, 204), "Wrong current password", "refused (4xx)", f"HTTP {r.status}",
          hint="the password was CHANGED with a wrong current password")
    check(r.status < 500, "Wrong current password", "4xx", f"HTTP {r.status}")
    msg = cp.server_error()
    check(msg, "Refusal shown to the user", "a message under the form", "no message")
    check("/change-password" in logged_in_page.url, "Still on the form", "/change-password", logged_in_page.url)


@pytest.mark.positive
def test_back_to_console(logged_in_page):
    """SES-008 — 'Back to the console' leaves the form without changing anything."""
    cp = ChangePasswordPage(logged_in_page).open()
    cp.back_to_console()
    logged_in_page.wait_for_url(lambda u: "/change-password" not in u, timeout=10_000)


# ================================================================= sign out
@pytest.mark.smoke
@pytest.mark.security
def test_sign_out_ends_session(own_session_page):
    """SES-010 — Sign out returns to /login, clears the tab session and the old token
    is refused by the API (revoked on the server, not just forgotten by the browser)."""
    page = own_session_page
    token = json.loads(page.evaluate("sessionStorage.getItem('sprintexcrow.session')") or "{}").get("accessToken")
    check(token, "Before sign out", "a signed-in session", "none")
    ChangePasswordPage(page).sign_out()
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    page.locator("#email").wait_for()  # sign-in form rendered: navigation finished
    page.wait_for_load_state("networkidle")
    check(page.evaluate("sessionStorage.getItem('sprintexcrow.session')") is None, "Tab session after sign out",
          "removed", "still present")
    r = ApiClient().get(settings.endpoints.auth_me, auth=False, headers={"Authorization": f"Bearer {token}"})
    check(r.status_code == 401, "Old token after sign out", "HTTP 401 from /auth/me", f"HTTP {r.status_code}",
          hint="logout must revoke the token on the server; a stolen token would stay usable")


@pytest.mark.security
def test_back_button_after_sign_out(own_session_page):
    """SES-011 — after sign out, the browser Back button does not show console data."""
    page = own_session_page
    page.goto(settings.url("/beneficiaries"))
    page.get_by_role("heading", name="Beneficiary List").wait_for()
    ChangePasswordPage(page).sign_out()
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    try:
        page.go_back()
    except Exception:  # noqa: BLE001 - the app redirects straight back to /login, aborting 'back'
        pass
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    check("/login" in page.url or "Showing" not in body, "Back after sign out", "sign-in page, no data",
          f"{page.url} — list visible: {'Showing' in body}")


@pytest.mark.security
def test_protected_page_after_sign_out(own_session_page):
    """SES-012 — after sign out, typing a console URL leads to sign-in."""
    page = own_session_page
    ChangePasswordPage(page).sign_out()
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
    page.goto(settings.url("/beneficiaries"))
    page.wait_for_url(re.compile(r"/login"), timeout=15_000)
