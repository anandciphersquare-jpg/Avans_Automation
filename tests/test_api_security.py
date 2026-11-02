"""
API + API-security tests (no browser).
Maps to API-001..API-029 and WSEC API rows.

These run against the REST API directly. Endpoint paths come from
config.settings.Endpoints — confirm/override them via env. A probe that returns
404 is treated as 'endpoint not wired here' and skips rather than false-failing.
"""
from __future__ import annotations

import pytest

from config.settings import settings
from utils.assertions import (SENSITIVE_KEY_HINTS, SQLI_PAYLOADS,
                              assert_security_headers)

pytestmark = [pytest.mark.api, pytest.mark.security]

EP = settings.endpoints
PROTECTED = [EP.dashboard, EP.beneficiaries, EP.transfers, EP.users, EP.roles, EP.audit]
HIDDEN = [EP.hidden_create_transfer, EP.hidden_approvals, EP.hidden_virtual_id,
          EP.hidden_master_escrow, EP.hidden_deposits, EP.hidden_qr_settlements]


# --------------------------------------------------------------- authentication
@pytest.mark.parametrize("path", PROTECTED)
def test_protected_endpoint_requires_token(api, path):
    """API-001 — protected endpoints reject unauthenticated requests (401/403)."""
    r = api.get(path, auth=False)
    if r.status_code == 404:
        pytest.skip(f"Endpoint not wired here: {path}")
    assert r.status_code in (401, 403), f"{path} returned {r.status_code} without a token"


def test_tampered_token_rejected(api):
    """API-003 — a tampered/garbage bearer token is rejected."""
    api.set_token("eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.")  # alg=none-style junk
    r = api.get(EP.beneficiaries)
    if r.status_code == 404:
        pytest.skip("Endpoint not wired here")
    assert r.status_code in (401, 403), f"Tampered token accepted ({r.status_code})"


def test_valid_admin_token_is_accepted(admin_api):
    """API-002 — a valid admin token is accepted on a protected endpoint."""
    r = admin_api.get(EP.beneficiaries)
    if r.status_code == 404:
        pytest.skip("Endpoint not wired here")
    assert r.status_code in (200, 204), f"Valid token rejected ({r.status_code})"


# ----------------------------------------------------------------- authorization
@pytest.mark.parametrize("path", HIDDEN)
def test_hidden_module_endpoints_locked(admin_api, path):
    """WSEC-002 — endpoints behind non-live modules must be locked (403/404)."""
    r = admin_api.get(path)
    assert r.status_code in (403, 404, 405, 501), \
        f"Non-live endpoint {path} is reachable ({r.status_code})"


def test_idor_on_beneficiary_blocked(admin_api):
    """API-005 — requesting an object by an id outside the caller's scope is
    denied (no IDOR). Uses a clearly foreign id."""
    r = admin_api.get(EP.beneficiaries.rstrip("/") + "/00000000-0000-0000-0000-000000000000")
    if r.status_code == 404 and "not wired" in "":
        pytest.skip("Endpoint not wired here")
    assert r.status_code in (403, 404), f"Foreign object returned {r.status_code} (possible IDOR)"


def test_mass_assignment_ignored(admin_api):
    """API-006 — extra privileged fields on create-user are ignored."""
    from utils.data_factory import new_user
    u = new_user()
    payload = {"email": u["email"], "fullName": u["full_name"], "contact": u["contact"],
               "role": "Customer", "isAdmin": True, "is_admin": True}
    r = admin_api.post(EP.users, json=payload)
    if r.status_code == 404:
        pytest.skip("Users endpoint not wired here")
    if r.status_code >= 400:
        return  # rejected outright is acceptable
    body = (r.text or "").lower()
    assert '"isadmin":true' not in body.replace(" ", ""), "Server echoed/accepted isAdmin=true"


# --------------------------------------------------------------------- injection
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_in_search_is_safe(admin_api, payload):
    """API-007 — SQLi in a query parameter does not error or dump data."""
    r = admin_api.get(EP.beneficiaries, params={"search": payload})
    if r.status_code == 404:
        pytest.skip("Endpoint not wired here")
    assert r.status_code < 500, f"SQLi payload caused a server error ({r.status_code})"
    body = (r.text or "").lower()
    assert "sql" not in body and "syntax" not in body, "DB error leaked for SQLi payload"


# ------------------------------------------------------------------- data hygiene
def test_no_sensitive_fields_in_responses(admin_api):
    """API-018 — responses never contain password/OTP/secret fields."""
    r = admin_api.get(EP.users)
    if r.status_code == 404:
        pytest.skip("Users endpoint not wired here")
    body = (r.text or "").lower().replace(" ", "")
    for key in ("password", "otp", "secret"):
        assert f'"{key}":' not in body, f"Response exposes a '{key}' field"


def test_account_numbers_masked_in_responses(admin_api):
    """API-017 — account numbers in responses are masked (last 4 only)."""
    import re
    r = admin_api.get(EP.beneficiaries)
    if r.status_code == 404 or not r.content:
        pytest.skip("Beneficiaries endpoint not wired / empty")
    # account fields only: a mobile number is legitimately 10 raw digits
    from utils.checks import check
    raw = re.findall(r'"(\w*[Aa]cc\w*)"\s*:\s*"(\d{5,})"', r.text)
    check(not raw, "Account numbers in GET /beneficiaries", "masked (e.g. **********7890)",
          f"raw values in {sorted({k for k, _ in raw})}")


# ----------------------------------------------------------------- hardening
def test_security_headers_present(admin_api):
    """API-026 — recommended security headers are present on API responses."""
    r = admin_api.get(EP.dashboard)
    if r.status_code == 404:
        pytest.skip("Dashboard endpoint not wired here")
    missing = assert_security_headers(dict(r.headers))
    assert not missing, f"Missing security headers: {missing}"


def test_unexpected_method_not_allowed(admin_api):
    """API-013 — unexpected HTTP verbs are rejected (405)."""
    r = admin_api.request("TRACE", EP.beneficiaries)
    assert r.status_code in (403, 404, 405, 501), f"TRACE returned {r.status_code}"


def test_cors_not_wildcard_with_credentials(admin_api):
    """API-014 — no 'Access-Control-Allow-Origin: *' together with credentials."""
    r = admin_api.get(EP.dashboard, headers={"Origin": "https://evil.example.com"})
    if r.status_code == 404:
        pytest.skip("Dashboard endpoint not wired here")
    acao = r.headers.get("Access-Control-Allow-Origin", "")
    acac = r.headers.get("Access-Control-Allow-Credentials", "")
    assert not (acao == "*" and acac.lower() == "true"), "Wildcard CORS with credentials"


# API-015 (login rate limiting) moved to tests/test_auth_api.py::test_login_is_rate_limited
# (AUTH-API-060). It is opt-in there (RUN_LOCKOUT_TESTS=1) because it can throttle this IP.
