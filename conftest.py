"""
Shared pytest fixtures for the SprintEXcrow automation suite.

Built on pytest-playwright (provides `browser`, `page`, etc.). We override the
context args to grant geolocation (sign-in is blocked without Allow Location),
and add higher-level fixtures:

    settings          - the loaded configuration
    api               - an ApiClient (unauthenticated)
    admin_api         - an ApiClient already logged in as admin (token set)
    logged_in_page    - a Playwright Page authenticated as admin (UI login once,
                        cached via storage_state and reused across tests)
    non_admin_page    - a Page authenticated as the limited-role user

Tests that need credentials/OTP skip cleanly when the environment is not set,
so the suite always collects and runs.

Every run also builds the execution report (reporting/ - see
reporting/README.md): one page per run, reports/Test_Report_<run_id>.html.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from api.api_client import ApiClient
from config.settings import settings as _settings
from pages.login_page import LoginPage
from utils import app_session

# execution report: hooks + the `report` fixture
pytest_plugins = ["reporting.plugin"]


def pytest_configure(config):
    from utils import console
    console.bind(config)  # lets page objects talk to the tester (manual OTP)


@pytest.fixture(autouse=True)
def _case_id_in_messages(request):
    """Put the running test's case id (e.g. AUTH-API-005) into failure messages."""
    from reporting.metadata import test_id
    from utils import checks
    checks.CURRENT_ID = test_id(request.node)[0]
    yield
    checks.CURRENT_ID = ""


# --------------------------------------------------------------------------- #
# configuration / context
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def settings():
    return _settings


def _context_kwargs() -> dict:
    """Context args shared by pytest-playwright's page and our own contexts."""
    from reporting.plugin import media_context_kwargs  # imported by pytest_plugins by now
    return {
        **media_context_kwargs(),  # video recording for the execution report
        "locale": "en-IN",
        "permissions": ["geolocation"],
        "geolocation": {
            "latitude": _settings.geo_latitude,
            "longitude": _settings.geo_longitude,
        },
        "ignore_https_errors": False,
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    # merge our geolocation/locale on top of pytest-playwright defaults
    return {**browser_context_args, **_context_kwargs()}


# --------------------------------------------------------------------------- #
# API fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def admin_api(request) -> ApiClient:
    """ApiClient signed in as admin. API login needs the emailed OTP, so the
    token comes from the signed-in UI session (see `admin_token`)."""
    if not _settings.has_admin_creds:
        pytest.skip("ADMIN_EMAIL / ADMIN_PASSWORD not set — API auth tests skipped.")
    client = ApiClient()
    client.set_token(request.getfixturevalue("admin_token"))
    return client


# --------------------------------------------------------------------------- #
# authenticated UI session (login once, reuse via storage_state)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def _admin_storage_state(browser) -> str:
    """Perform the full UI login (email + password + OTP) once and save the
    authenticated storage state for reuse. Returns the state file path."""
    if not _settings.has_admin_creds:
        pytest.skip("ADMIN_EMAIL / ADMIN_PASSWORD not set — UI session tests skipped.")

    state_path = Path(_settings.storage_state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    # reuse a saved session only while the app still accepts it
    if state_path.exists() and app_session.has_session(state_path) and os.getenv("REUSE_AUTH", "1") == "1":
        context = _admin_context(browser, str(state_path))
        try:
            if app_session.is_signed_in(context.new_page()):
                return str(state_path)
        finally:
            context.close()

    context = browser.new_context(**_context_kwargs())
    page = context.new_page()
    try:
        LoginPage(page).open().login(_settings.admin_email, _settings.admin_password)
        page.wait_for_url(lambda u: "/login" not in u and u.rstrip("/") != _settings.base_url.rstrip("/"),
                          timeout=30_000)
        page.wait_for_load_state("networkidle")
        app_session.save(page, state_path)  # sessionStorage holds the app's login
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Admin login failed, so tests that need a signed-in admin were not run. {exc}")
    finally:
        context.close()
    return str(state_path)


def _admin_context(browser, state_path: str):
    context = browser.new_context(storage_state=state_path, **_context_kwargs())
    app_session.restore(context, state_path)
    return context


@pytest.fixture
def logged_in_page(browser, _admin_storage_state):
    """Signed-in admin page, already on the dashboard (as after a real login)."""
    context = _admin_context(browser, _admin_storage_state)
    page = context.new_page()
    if not app_session.is_signed_in(page):  # saved session expired/revoked -> sign in again, once
        # clean context: the restore init script would keep re-injecting the dead token
        context.close()
        context = browser.new_context(**_context_kwargs())
        page = context.new_page()
        try:
            LoginPage(page).open().login(_settings.admin_email, _settings.admin_password)
            page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
            app_session.save(page, _admin_storage_state)
        except Exception as exc:  # noqa: BLE001
            context.close()
            pytest.skip(f"Admin login failed, so tests that need a signed-in admin were not run. {exc}")
    try:  # side menu appears once the dashboard data has loaded
        page.get_by_role("link", name="Dashboard").first.wait_for(state="visible", timeout=30_000)
    except Exception:  # noqa: BLE001 - the test itself reports what is missing
        pass
    yield page
    context.close()


@pytest.fixture
def own_session_page(browser):
    """A page signed in with its OWN admin session in a clean context (no saved-session
    restore). For sign-out / logout tests: what they end is theirs alone."""
    if not _settings.has_admin_creds:
        pytest.skip("ADMIN_EMAIL / ADMIN_PASSWORD not set.")
    context = browser.new_context(**_context_kwargs())
    page = context.new_page()
    try:
        LoginPage(page).open().login(_settings.admin_email, _settings.admin_password)
        page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
        page.get_by_role("link", name="Dashboard").first.wait_for(state="visible", timeout=30_000)
    except Exception as exc:  # noqa: BLE001
        context.close()
        pytest.skip(f"Admin login failed, so this sign-out test was not run. {exc}")
    yield page
    context.close()


def _saved_session(state_path: str) -> dict:
    """The app's sessionStorage entry ({accessToken, expiresAt}) saved next to the state file."""
    try:
        data = json.loads(Path(state_path).with_name(Path(state_path).stem + "_session.json").read_text("utf-8"))
        return json.loads(data["session_storage"]["sprintexcrow.session"])
    except Exception:  # noqa: BLE001
        return {}


def _token_usable(token: str | None, expires_at: str | None, margin_s: int = 120) -> bool:
    """Accepted by the API and not expiring within `margin_s` (tokens live ~30 min)."""
    from datetime import datetime, timedelta, timezone
    if not token or not expires_at:
        return False
    try:
        left = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) - datetime.now(timezone.utc)
    except ValueError:
        return False
    if left < timedelta(seconds=margin_s):
        return False
    # still accepted? (a sign-out / change-password test may have revoked it)
    return ApiClient().get(_settings.endpoints.auth_me, auth=False,
                           headers={"Authorization": f"Bearer {token}"}).status_code == 200


@pytest.fixture
def admin_token(browser, _admin_storage_state) -> str:
    """Bearer token of the signed-in admin, read from the app's sessionStorage.
    The API login needs the email OTP, so API tests borrow the UI session.
    An expiring or revoked token is replaced by signing in again."""
    saved = _saved_session(_admin_storage_state)
    if _token_usable(saved.get("accessToken"), saved.get("expiresAt")):
        return saved["accessToken"]
    # a clean context: the saved-session init script would re-inject the old token
    context = browser.new_context(**_context_kwargs())
    page = context.new_page()
    try:
        LoginPage(page).open().login(_settings.admin_email, _settings.admin_password)
        page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
        page.wait_for_load_state("networkidle")
        app_session.save(page, _admin_storage_state)
        raw = page.evaluate("sessionStorage.getItem('sprintexcrow.session')")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Admin login failed, so API tests that need a token were not run. {exc}")
    finally:
        context.close()
    token = (json.loads(raw) if raw else {}).get("accessToken")
    if not token:
        pytest.skip("No access token in the app session, so API tests that need a token were not run.")
    return token


@pytest.fixture
def ui_token_api(admin_token) -> ApiClient:
    """An ApiClient authenticated with the admin's UI-session token."""
    client = ApiClient()
    client.set_token(admin_token)
    return client


@pytest.fixture
def non_admin_page(browser):
    """A Page authenticated as the limited-role (non-admin) user."""
    if not _settings.has_user_creds:
        pytest.skip("USER_EMAIL / USER_PASSWORD not set — access-control tests skipped.")
    context = browser.new_context(**_context_kwargs())
    page = context.new_page()
    try:
        LoginPage(page).open().login(_settings.user_email, _settings.user_password)
        page.wait_for_load_state("networkidle")
    except Exception as exc:  # noqa: BLE001
        context.close()
        pytest.skip(f"Non-admin login failed, so this access-control test was not run. {exc}")
    yield page
    context.close()


# --------------------------------------------------------------------------- #
# small helpers available to tests
# --------------------------------------------------------------------------- #
@pytest.fixture
def tmp_cheque(tmp_path) -> str:
    """A tiny valid PNG to use as a 'cancelled cheque' upload."""
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
        "awAAAABJRU5ErkJggg=="
    )
    f = tmp_path / "cheque.png"
    f.write_bytes(png)
    return str(f)
