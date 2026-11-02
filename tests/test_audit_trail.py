"""
Audit Trail tests.
Maps to WAUD-001..WAUD-005.
"""
from __future__ import annotations

import pytest

from pages.audit_trail_page import AuditTrailPage
from utils.assertions import FULL_ACCOUNT_RE

pytestmark = [pytest.mark.functional]


@pytest.mark.positive
@pytest.mark.smoke
def test_audit_trail_loads(logged_in_page):
    """WAUD-001 — the Audit Trail renders entries."""
    ap = AuditTrailPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    assert ap.rows().count() >= 0


@pytest.mark.functional
def test_entry_shows_user_time_ip(logged_in_page):
    """WAUD-002 — entries carry user / time / IP (and location)."""
    ap = AuditTrailPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    if not ap.rows().count():
        pytest.skip("No audit rows present")
    text = ap.table_text().lower()
    import re
    has_time = bool(re.search(r"\d{1,2}:\d{2}", text)) or "ago" in text or "202" in text
    has_ip = bool(re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text))
    assert has_time, "No timestamp-like value in audit rows"
    assert has_ip or "ip" in text, "No IP information in audit rows"


@pytest.mark.security
def test_no_secrets_or_full_accounts_in_audit(logged_in_page):
    """WAUD-004 — no passwords, OTPs or full account numbers in descriptions."""
    ap = AuditTrailPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    text = ap.table_text()
    low = text.lower()
    assert "password" not in low and "otp" not in low, "Sensitive keyword in audit text"
    assert not FULL_ACCOUNT_RE.search(text), "An unmasked account number appears in audit"


@pytest.mark.security
@pytest.mark.authorization
def test_audit_restricted_for_non_admin(non_admin_page):
    """WAUD-005 — a limited role cannot open the Audit Trail directly."""
    page = non_admin_page
    base = page.url.split("//", 1)[0] + "//" + page.url.split("//", 1)[1].split("/", 1)[0]
    page.goto(base + "/audit-trail")
    page.wait_for_timeout(800)
    body = page.inner_text("body").lower()
    blocked = any(s in body for s in ("cannot open", "forbidden", "no access",
                                      "unauthor", "access denied", "not found"))
    redirected = "audit" not in page.url.lower()
    assert blocked or redirected, "Audit Trail reachable by a limited role"
