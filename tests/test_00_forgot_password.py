"""
Forgot password -> mailed code/link -> new password -> sign in.

Runs ONCE: the new password is saved to CREDENTIALS_STORE and every later
login uses it, so after a successful reset this test skips and the suite
just signs in and moves on to the other modules. Delete the store file (or
set FORCE_PASSWORD_RESET=1) to run the reset again.

The file name sorts first so the reset happens before any module logs in.
"""
from __future__ import annotations

import os

import pytest

from config.settings import settings
from pages.dashboard_page import DashboardPage
from pages.login_page import LoginPage
from utils.credential_store import reset_done

pytestmark = [pytest.mark.auth]


@pytest.mark.functional
@pytest.mark.skipif(not settings.has_admin_creds, reason="set ADMIN_EMAIL / ADMIN_PASSWORD")
@pytest.mark.skipif(settings.otp_strategy.lower() not in ("imap", "gmail"),
                    reason="needs OTP_STRATEGY=imap to read the reset mail")
def test_forgot_password_then_login(page):
    """AUTH-UI-080 — reset the password via the mailed code, then sign in with it."""
    if reset_done(settings.credentials_store_path, settings.admin_email) \
            and os.getenv("FORCE_PASSWORD_RESET") != "1":
        pytest.skip("Password already reset and saved — using the saved password.")

    lp = LoginPage(page)
    new_password = lp.reset_password_via_mail(settings.admin_email)
    assert settings.admin_password == new_password, "New password was not saved"

    lp.open().login(settings.admin_email, new_password)
    page.wait_for_load_state("networkidle")
    assert "login" not in page.url.lower(), "Sign-in with the new password failed"
    assert DashboardPage(page).is_menu_enabled("Dashboard")

    # refresh the shared session so later modules do not reuse a pre-reset one
    from utils import app_session
    app_session.save(page, settings.storage_state_path)
