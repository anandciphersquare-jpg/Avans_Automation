"""
Cross-cutting UI security tests.
Maps to WSEC-001..WSEC-008 (hidden-module lockdown, client storage/console,
masking, transport) exercised through the browser.
"""
from __future__ import annotations

import pytest

from pages.dashboard_page import HIDDEN_MENU, ROUTES
from utils.assertions import FULL_ACCOUNT_RE

pytestmark = [pytest.mark.security]


def _origin(page) -> str:
    return page.url.split("//", 1)[0] + "//" + page.url.split("//", 1)[1].split("/", 1)[0]


@pytest.mark.parametrize("item", [m for m in HIDDEN_MENU if m in ROUTES])
def test_hidden_module_route_blocked(logged_in_page, item):
    """WSEC-001 — direct navigation to a non-live module must not render it."""
    page = logged_in_page
    page.goto(_origin(page) + ROUTES[item])
    page.wait_for_timeout(800)
    body = page.inner_text("body").lower()
    blocked = any(s in body for s in ("cannot open", "not found", "forbidden",
                                      "no access", "unauthor", "access denied"))
    redirected = ROUTES[item].strip("/").split("/")[0] not in page.url.lower()
    assert blocked or redirected, f"Hidden module '{item}' rendered via direct URL"


def test_no_secrets_in_local_or_session_storage(logged_in_page):
    """WSEC-006 — no passwords/OTPs/full account numbers in web storage."""
    page = logged_in_page
    dump = page.evaluate(
        """() => {
            const grab = s => { let o={}; for (let i=0;i<s.length;i++){const k=s.key(i); o[k]=s.getItem(k);} return o; };
            return JSON.stringify({local: grab(localStorage), session: grab(sessionStorage)});
        }"""
    ).lower()
    for bad in ("password", "otp", "cvv", "\"pin\""):
        assert bad not in dump, f"'{bad}' found in web storage"
    assert not FULL_ACCOUNT_RE.search(dump), "An unmasked account number is in web storage"


def test_no_sensitive_console_logging(logged_in_page):
    """WSEC-006 — the console must not print passwords/OTPs/account numbers."""
    page = logged_in_page
    messages: list[str] = []
    page.on("console", lambda m: messages.append(m.text))
    # drive a little navigation to generate any logging
    page.goto(_origin(page) + ROUTES.get("Beneficiary List", "/beneficiaries"))
    page.wait_for_timeout(1200)
    joined = " ".join(messages).lower()
    for bad in ("password", "otp"):
        assert bad not in joined, f"'{bad}' printed to console"


def test_app_served_over_https(logged_in_page):
    """WSEC-009 — the application is served over HTTPS."""
    assert logged_in_page.url.lower().startswith("https://"), "App is not on HTTPS"
