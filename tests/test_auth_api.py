"""
Authentication & Session, API (/api/v1/auth/*): login, OTP, session (/auth/me,
logout), change password, forgot / reset password, and their security.
Test case ids: AUTH-API-001 .. AUTH-API-061.

Contract confirmed on UAT (2026-10-21):
    POST /auth/login        {email, password, clientGeo}  -> otpRequired + challenge (no token yet)
    POST /auth/verify-otp   {challengeReference, code}    -> session token
    POST /auth/resend-otp   {challengeReference}
    GET  /auth/me, POST /auth/logout, POST /auth/change-password   (token required)
    POST /auth/forgot-password {email}, /auth/reset-password[/verify]
Wrong credentials -> 401 UNAUTHORIZED "Invalid email or password."

Account safety:
  * only AUTH-API-006 sends a wrong password for the real account (once per run);
  * brute-force / rate-limit / OTP-lockout cases (AUTH-API-060/061/024) can lock
    the account or throttle this machine's IP, so they run only with
    RUN_LOCKOUT_TESTS=1 — run them on their own, at the end of a session.
"""
from __future__ import annotations

import base64
import json
import os
import time

import pytest

from api.api_client import ApiClient
from config.settings import settings
from utils.assertions import SQLI_PAYLOADS, assert_security_headers
from utils.checks import api_summary, check, describe, expect_api

pytestmark = [pytest.mark.api, pytest.mark.auth]

EP = settings.endpoints
GEO = ApiClient.client_geo()
FAKE_EMAIL = "qa.nobody.7x@example.com"
BAD_CREDS = "Invalid email or password."
OTP_RESTART = "This code can no longer be used. Sign in again to get a new one."
BOGUS_CHALLENGE = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"
requires_admin = pytest.mark.skipif(not settings.has_admin_creds, reason="set ADMIN_EMAIL / ADMIN_PASSWORD")
lockout_risk = pytest.mark.skipif(os.getenv("RUN_LOCKOUT_TESTS") != "1",
                                  reason="can lock the account / throttle this IP — set RUN_LOCKOUT_TESTS=1 to run")


def _login(api, email=FAKE_EMAIL, password="Wrong@Pass1", geo=GEO, **extra):
    body = {"email": email, "password": password, **extra}
    if geo is not None:
        body["clientGeo"] = geo
    return api.post(EP.login, json=body, auth=False)


def _jwt_parts(token: str) -> tuple[dict, dict]:
    def dec(seg: str) -> dict:
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    head, payload, _ = token.split(".")
    return dec(head), dec(payload)


# ============================================================ login: input
@pytest.mark.negative
def test_login_empty_body(api):
    """AUTH-API-001 — {} is refused with VALIDATION_ERROR naming email and password."""
    expect_api(api.post(EP.login, json={}, auth=False), "Login with an empty body",
               status=400, code="VALIDATION_ERROR", fields=["email", "password"])


@pytest.mark.negative
@pytest.mark.parametrize("missing", ["email", "password"])
def test_login_missing_field(api, missing):
    """AUTH-API-002 — a login without email or password is refused naming that field."""
    body = {"email": FAKE_EMAIL, "password": "Wrong@Pass1", "clientGeo": GEO}
    body.pop(missing)
    expect_api(api.post(EP.login, json=body, auth=False), f"Login without {missing}",
               status=400, code="VALIDATION_ERROR", fields=[missing])


@pytest.mark.negative
@pytest.mark.parametrize("email", ["abc", "abc@", "a b@x.com", "@x.com"])
def test_login_bad_email_format(api, email):
    """AUTH-API-003 — a malformed email is refused with 'Enter a valid email address'."""
    expect_api(_login(api, email=email), f"Login with email {email!r}",
               status=400, code="VALIDATION_ERROR", fields=["email"])


@pytest.mark.negative
def test_login_without_location(api):
    """AUTH-API-004 — sign-in without clientGeo is refused (location is mandatory)."""
    expect_api(_login(api, geo=None), "Login without clientGeo", status=400, code="VALIDATION_ERROR",
               message_contains="Location access is required")


@pytest.mark.negative
def test_login_unknown_email(api):
    """AUTH-API-005 — an unknown email gets 401 'Invalid email or password.'"""
    expect_api(_login(api), "Login with an unknown email", status=401, code="UNAUTHORIZED", message=BAD_CREDS)


@requires_admin
@pytest.mark.security
def test_login_wrong_password_same_as_unknown_email(api):
    """AUTH-API-006 — a wrong password for a REAL account answers exactly like an unknown
    email (status, code, message), so accounts cannot be discovered. One attempt per run."""
    real = _login(api, email=settings.admin_email, password="Wrong@Pass1")
    fake = _login(api)
    a, b = api_summary(real), api_summary(fake)
    same = (a["status"], a["code"], a["message"]) == (b["status"], b["code"], b["message"])
    check(same, "Real account + wrong password vs unknown email",
          f"identical answers ({describe(fake)})", f"real account got: {describe(real)}",
          hint="a different answer for real accounts lets attackers list valid users")
    check(a["status"] == 401, "Wrong password status", "HTTP 401", describe(real))


@pytest.mark.negative
def test_login_malformed_json(api):
    """AUTH-API-007 — a broken JSON body is 400 MALFORMED_REQUEST, not 500."""
    r = api.post(EP.login, data='{"email": "a@b.com",', headers={"Content-Type": "application/json"}, auth=False)
    expect_api(r, "Login with malformed JSON", status=400, code="MALFORMED_REQUEST")


@pytest.mark.negative
@pytest.mark.parametrize("geo", [{"latitude": 999, "longitude": 77.2}, {"latitude": "north", "longitude": "east"},
                                 {"latitude": None, "longitude": None}],
                         ids=["latitude_999", "text", "nulls"])
def test_login_invalid_location_values(api, geo):
    """AUTH-API-008 — impossible location values are refused cleanly (4xx, never 2xx/5xx)."""
    r = _login(api, geo=geo)
    check(400 <= r.status_code < 500, f"Login with clientGeo={geo}", "HTTP 4xx", describe(r))


@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_login_sql_injection(api, payload):
    """AUTH-API-009 — SQL in email/password never signs in, never errors (403 from the firewall is fine)."""
    r = _login(api, email=payload, password=payload)
    check(r.status_code in (400, 401, 403), f"Login with SQL payload {payload!r}", "HTTP 400/401/403", describe(r),
          hint="2xx = authentication bypass, 5xx = the payload reached the database layer")
    check("sql" not in r.text.lower() and "syntax" not in r.text.lower(), "No database error text",
          "no SQL error in the body", r.text[:200])


@pytest.mark.negative
@pytest.mark.parametrize("field", ["email", "password"])
def test_login_oversized_input(api, field):
    """AUTH-API-010 — a 10 000-character email/password is refused cleanly (4xx)."""
    big = ("a" * 10_000 + "@example.com") if field == "email" else "A@1" + "a" * 10_000
    r = _login(api, **({"email": big} if field == "email" else {"password": big}))
    check(400 <= r.status_code < 500, f"Login with a 10k-char {field}", "HTTP 4xx (400/401/413)", describe(r))


@pytest.mark.negative
def test_login_wrong_content_type(api):
    """AUTH-API-011 — a form-encoded body is refused cleanly (4xx), not 500."""
    r = api.post(EP.login, data=f"email={FAKE_EMAIL}&password=x", auth=False,
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    check(400 <= r.status_code < 500, "Login with form encoding", "HTTP 4xx (400/415)", describe(r))


@pytest.mark.negative
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_login_wrong_method(api, method):
    """AUTH-API-012 — only POST is accepted on /auth/login (other verbs are refused:
    the API answers 401 because its auth filter runs before method routing)."""
    r = api.request(method, EP.login, auth=False)
    check(r.status_code in (401, 403, 404, 405), f"{method} /auth/login", "refused (405, or 401/403/404)",
          describe(r), hint="any 2xx means the endpoint does something on an unexpected verb")


@requires_admin
@pytest.mark.positive
def test_login_correct_password_needs_otp(api):
    """AUTH-API-013 — the right password alone gives NO token: it returns otpRequired,
    a challenge reference and a masked destination. (Sends one OTP mail.)"""
    body = expect_api(_login(api, email=settings.admin_email, password=settings.admin_password),
                      "Login with the correct password", status=200)
    data = body.get("data") or {}
    check(data.get("otpRequired") is True, "Second factor", "otpRequired=true", data.get("otpRequired"))
    check(not data.get("accessToken") and "accessToken" not in json.dumps(body), "No token before the OTP",
          "no accessToken", "accessToken present", hint="the password alone must not give a session")
    check(data.get("challengeReference"), "Challenge reference", "present", "missing")
    dest = data.get("otpDestination") or ""
    check("•" in dest and settings.admin_email not in dest, "OTP destination masked", "a••••r@…", dest)


# ===================================================================== OTP
@pytest.mark.negative
def test_verify_otp_empty_body(api):
    """AUTH-API-020 — verify-otp without fields names challengeReference and code."""
    expect_api(api.post(EP.verify_otp, json={}, auth=False), "Verify OTP with an empty body",
               status=400, code="VALIDATION_ERROR", fields=["challengeReference", "code"])


@pytest.mark.negative
def test_verify_otp_unknown_challenge(api):
    """AUTH-API-021 — a code for an unknown/expired challenge says to sign in again."""
    r = api.post(EP.verify_otp, json={"challengeReference": BOGUS_CHALLENGE, "code": "000000"}, auth=False)
    expect_api(r, "Verify OTP for an unknown challenge", status=401, code="OTP_RESTART_REQUIRED", message=OTP_RESTART)


@pytest.mark.negative
@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", ""], ids=["5", "7", "letters", "space", "empty"])
def test_verify_otp_bad_code_format(api, code):
    """AUTH-API-022 — a code that is not 6 digits is refused (4xx), never 2xx/5xx."""
    r = api.post(EP.verify_otp, json={"challengeReference": BOGUS_CHALLENGE, "code": code}, auth=False)
    check(r.status_code in (400, 401), f"Verify OTP with code {code!r}", "HTTP 400/401", describe(r))


@pytest.mark.negative
def test_resend_otp_unknown_challenge(api):
    """AUTH-API-023 — resending for an unknown challenge says to sign in again."""
    r = api.post(EP.resend_otp, json={"challengeReference": BOGUS_CHALLENGE}, auth=False)
    expect_api(r, "Resend OTP for an unknown challenge", status=401, code="OTP_RESTART_REQUIRED")


@requires_admin
@lockout_risk
@pytest.mark.security
def test_otp_guessing_is_stopped(api):
    """AUTH-API-024 — repeated wrong codes on one challenge are stopped (OTP_RESTART_REQUIRED
    or 429) within 6 tries. RUN_LOCKOUT_TESTS=1 only."""
    ch = (_login(api, email=settings.admin_email, password=settings.admin_password).json().get("data") or {})
    ref = ch.get("challengeReference")
    check(ref, "Challenge for the guessing test", "a challenge", ch)
    answers = []
    for guess in ("000000", "111111", "222222", "333333", "444444", "555555"):
        r = api.post(EP.verify_otp, json={"challengeReference": ref, "code": guess}, auth=False)
        answers.append(f"{r.status_code}/{api_summary(r)['code']}")
        if r.status_code == 429 or api_summary(r)["code"] == "OTP_RESTART_REQUIRED":
            return
    check(False, "OTP guessing", "stopped within 6 wrong codes", " ".join(answers),
          hint="without a try limit a 6-digit code can be brute-forced")


# ================================================================= session
@pytest.mark.positive
def test_me_returns_signed_in_user(ui_token_api):
    """AUTH-API-030 — /auth/me with a valid token returns the signed-in user, no secrets."""
    body = expect_api(ui_token_api.get(EP.auth_me), "GET /auth/me with a valid token", status=200)
    text = json.dumps(body).lower()
    check(settings.admin_email.lower() in text, "Signed-in user", settings.admin_email, text[:200])
    for key in ('"password"', '"otp"', '"secret"'):
        check(key not in text, "No secrets in /auth/me", f"no {key} field", "present")


@pytest.mark.security
@pytest.mark.parametrize("path_attr", ["auth_me", "logout", "change_password", "navigation", "beneficiaries"])
def test_session_endpoints_need_token(api, path_attr):
    """AUTH-API-031 — session endpoints refuse an anonymous call with 401 UNAUTHORIZED."""
    path = getattr(EP, path_attr)
    method = "GET" if path_attr in ("auth_me", "navigation", "beneficiaries") else "POST"
    expect_api(api.request(method, path, auth=False, json=None if method == "GET" else {}),
               f"{method} {path} without a token", status=401, code="UNAUTHORIZED")


@pytest.mark.security
@pytest.mark.parametrize("auth", ["Bearer abc.def.ghi", "Bearer ", "Basic YWRtaW46YWRtaW4=", "Token x"],
                         ids=["garbage", "empty", "basic", "wrong_scheme"])
def test_me_rejects_bad_credentials(api, auth):
    """AUTH-API-032 — garbage, empty or wrong-scheme Authorization headers get 401."""
    expect_api(api.get(EP.auth_me, auth=False, headers={"Authorization": auth}),
               f"/auth/me with '{auth.split()[0]} …'", status=401)


@pytest.mark.security
def test_forged_signature_rejected(api, admin_token):
    """AUTH-API-033 — the real token with one signature character changed is refused."""
    head, payload, sig = admin_token.split(".")
    forged = f"{head}.{payload}.{('A' if sig[0] != 'A' else 'B') + sig[1:]}"
    expect_api(api.get(EP.auth_me, auth=False, headers={"Authorization": f"Bearer {forged}"}),
               "/auth/me with a forged signature", status=401,
               hint="the server is not verifying the token signature")


@pytest.mark.security
def test_alg_none_token_rejected(api, admin_token):
    """AUTH-API-034 — an unsigned (alg=none) copy of the real token is refused."""
    none_head = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    token = f"{none_head}.{admin_token.split('.')[1]}."
    expect_api(api.get(EP.auth_me, auth=False, headers={"Authorization": f"Bearer {token}"}),
               "/auth/me with alg=none", status=401, hint="alg=none tokens must never be accepted")


@pytest.mark.security
def test_tampered_claims_rejected(api, admin_token):
    """AUTH-API-035 — changing the token's claims (e.g. a later expiry) invalidates it."""
    head, payload, sig = admin_token.split(".")
    claims = _jwt_parts(admin_token)[1]
    claims["exp"] = int(time.time()) + 10 * 365 * 86400
    new_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    expect_api(api.get(EP.auth_me, auth=False, headers={"Authorization": f"Bearer {head}.{new_payload}.{sig}"}),
               "/auth/me with an extended expiry", status=401)


@pytest.mark.security
def test_token_claims_are_safe(admin_token):
    """AUTH-API-036 — the token is signed (not alg=none), expires within an hour and
    carries no password / OTP."""
    head, claims = _jwt_parts(admin_token)
    check(head.get("alg", "").lower() not in ("", "none"), "Token algorithm", "a signing algorithm", head)
    exp, iat = claims.get("exp"), claims.get("iat") or time.time()
    check(exp, "Token expiry", "an exp claim", claims.keys())
    life_min = (exp - iat) / 60
    check(0 < life_min <= 60, "Token lifetime", "60 minutes or less", f"{life_min:.0f} minutes")
    # permission names such as 'user.reset_password' and the boolean 'pwd' flag are fine;
    # a claim that CARRIES a secret is not
    secret_keys = [k for k, v in claims.items()
                   if k.lower() in ("password", "passwd", "otp", "code", "secret", "pin") and isinstance(v, str)]
    check(not secret_keys, "Token contents", "no password / OTP / secret claim",
          f"claims {secret_keys} (all claims: {sorted(claims)})",
          hint="a JWT is only base64 — anyone holding it can read every claim")


@requires_admin
@pytest.mark.security
def test_logout_revokes_token(api, browser):
    """AUTH-API-037 — after POST /auth/logout the same token is refused everywhere.
    Uses its own sign-in so the shared session is not touched."""
    from conftest import _context_kwargs
    from pages.login_page import LoginPage
    context = browser.new_context(**_context_kwargs())
    page = context.new_page()
    try:
        LoginPage(page).open().login(settings.admin_email, settings.admin_password)
        page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
        token = json.loads(page.evaluate("sessionStorage.getItem('sprintexcrow.session')"))["accessToken"]
    finally:
        context.close()
    hdr = {"Authorization": f"Bearer {token}"}
    expect_api(api.get(EP.auth_me, auth=False, headers=hdr), "/auth/me before logout", status=200)
    r = api.post(EP.logout, auth=False, headers=hdr)
    check(r.status_code in (200, 204), "POST /auth/logout", "HTTP 200/204", describe(r))
    for path in (EP.auth_me, EP.beneficiaries):
        expect_api(api.get(path, auth=False, headers=hdr), f"GET {path} with the logged-out token", status=401,
                   hint="logout must revoke the token server-side")


# ========================================================= change password
@pytest.mark.negative
def test_change_password_empty_body(ui_token_api):
    """AUTH-API-040 — change-password with {} names every missing field (nothing changes)."""
    expect_api(ui_token_api.post(EP.change_password, json={}), "Change password with an empty body",
               status=400, code="VALIDATION_ERROR", fields=["currentPassword", "newPassword", "confirmPassword"])


@pytest.mark.negative
@pytest.mark.parametrize("new", ["abc", "abcdefgh", "ABCD@1234", "Abcd@12345678"],
                         ids=["3_chars", "no_upper_digit_symbol", "no_lowercase", "13_chars"])
def test_change_password_weak_new_refused(ui_token_api, new):
    """AUTH-API-041 — a weak new password is refused by the server and nothing changes.
    The server checks the current password first ('Your current password is incorrect.'),
    so with a wrong current password the rule itself cannot be reached safely — sending
    the real current password would CHANGE it if the rule were missing."""
    r = ui_token_api.post(EP.change_password, json={"currentPassword": "Wrong@Cur1", "newPassword": new,
                                                    "confirmPassword": new})
    expect_api(r, f"Change password to {new!r}", status=(400, 422),
               hint="2xx = the password was changed to a weak value without the current password")
    expect_api(ui_token_api.get(EP.auth_me), "Session still valid after the refused change", status=200)


@pytest.mark.negative
def test_change_password_mismatch_refused(ui_token_api):
    """AUTH-API-042 — newPassword and confirmPassword must match on the server too."""
    r = ui_token_api.post(EP.change_password, json={"currentPassword": "Wrong@Cur1", "newPassword": "Qa@New1234",
                                                    "confirmPassword": "Qa@New9999"})
    check(r.status_code in (400, 422), "Change password with a mismatched confirm", "HTTP 400/422", describe(r))


@pytest.mark.negative
def test_change_password_wrong_current_refused(ui_token_api):
    """AUTH-API-043 — a wrong current password is refused and the token stays valid."""
    r = ui_token_api.post(EP.change_password, json={"currentPassword": "Wrong@Cur1", "newPassword": "Qa@New1234",
                                                    "confirmPassword": "Qa@New1234"})
    check(r.status_code in (400, 401, 403, 422), "Change password with a wrong current password",
          "refused (4xx)", describe(r), hint="2xx = the password was CHANGED without knowing the current one")
    expect_api(ui_token_api.get(EP.auth_me), "Session after a refused change", status=200)


# ===================================================== forgot / reset password
@pytest.mark.security
def test_forgot_password_unknown_email_generic(api):
    """AUTH-API-050 — an unknown email gets 200 and the generic 'If an account exists…' message."""
    expect_api(api.post(EP.forgot_password, json={"email": FAKE_EMAIL}, auth=False),
               "Forgot password for an unknown email", status=200, message_contains="If an account exists")


@requires_admin
@pytest.mark.security
def test_forgot_password_same_answer_real_and_unknown(api):
    """AUTH-API-051 — the real account gets the identical answer (no account discovery).
    Sends one reset mail to the admin (the password is not changed)."""
    real = api.post(EP.forgot_password, json={"email": settings.admin_email}, auth=False)
    fake = api.post(EP.forgot_password, json={"email": FAKE_EMAIL}, auth=False)
    a, b = api_summary(real), api_summary(fake)
    check((a["status"], a["message"]) == (b["status"], b["message"]), "Forgot password: real vs unknown email",
          f"identical answers ({describe(fake)})", f"real account got: {describe(real)}")


@pytest.mark.negative
@pytest.mark.parametrize("email", ["", "abc", "abc@"], ids=["empty", "no_at", "no_domain"])
def test_forgot_password_bad_email(api, email):
    """AUTH-API-052 — forgot-password checks the email format."""
    expect_api(api.post(EP.forgot_password, json={"email": email}, auth=False), f"Forgot password for {email!r}",
               status=400, code="VALIDATION_ERROR", fields=["email"])


@pytest.mark.security
@pytest.mark.parametrize("token", ["bogus", "0" * 64, "' OR '1'='1"], ids=["word", "zeros", "sql"])
def test_reset_link_check_rejects_bad_token(api, token):
    """AUTH-API-053 — a made-up reset token is reported as not usable (valid=false)."""
    r = api.post(EP.reset_password_verify, json={"token": token}, auth=False)
    check(r.status_code in (200, 400, 403, 404, 410), f"Reset-link check for {token!r}", "refused / valid=false",
          describe(r))
    if r.status_code == 200:
        valid = ((r.json().get("data") or {}).get("valid"))
        check(valid is False, f"Reset-link check for {token!r}", "valid=false", f"valid={valid}",
              hint="an unguessable, single-use token is what protects the reset")


@pytest.mark.security
def test_reset_with_bad_token_refused(api):
    """AUTH-API-054 — a password reset with a made-up token never succeeds."""
    r = api.post(EP.reset_password, json={"token": "bogus", "newPassword": "Qa@New1234",
                                          "confirmPassword": "Qa@New1234"}, auth=False)
    check(r.status_code not in (200, 204) and r.status_code < 500, "Reset with a made-up token",
          "refused (4xx)", describe(r), hint="2xx = anyone can reset a password without the mailed link")


# ================================================================ hardening
@pytest.mark.security
def test_auth_responses_have_security_headers(api):
    """AUTH-API-055 — auth responses carry HSTS, nosniff, frame protection and no-store."""
    r = _login(api)
    missing = assert_security_headers(dict(r.headers))
    check(not missing, "Security headers on /auth/login", "all present", f"missing: {missing}")
    check("no-store" in r.headers.get("Cache-Control", ""), "Caching of auth responses", "Cache-Control: no-store",
          r.headers.get("Cache-Control", "(none)"))


@pytest.mark.security
def test_auth_cors_refuses_foreign_origin(api):
    """AUTH-API-056 — the login API does not allow a foreign site to call it from a browser."""
    r = api.request("OPTIONS", EP.login, auth=False, headers={
        "Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    acao = r.headers.get("Access-Control-Allow-Origin", "")
    check(acao not in ("*", "https://evil.example.com"), "CORS preflight from evil.example.com",
          "origin not allowed", f"Access-Control-Allow-Origin: {acao}")


@pytest.mark.security
def test_auth_error_has_request_id(api):
    """AUTH-API-057 — every auth error carries a request id support can trace."""
    s = api_summary(_login(api))
    check(s["request_id"], "Request id on an auth error", "requestId / X-Request-ID", "missing")


@lockout_risk
@pytest.mark.security
def test_login_is_rate_limited(api):
    """AUTH-API-060 — repeated failed logins (unknown email) are throttled with 429 within 25 tries.
    RUN_LOCKOUT_TESTS=1 only (it can throttle this machine)."""
    codes = []
    for _ in range(25):
        r = _login(api, email="qa.bruteforce@example.com")
        codes.append(r.status_code)
        if r.status_code == 429:
            return
    check(False, "Login brute force", "HTTP 429 within 25 failed attempts", f"statuses: {codes}",
          hint="no throttling lets an attacker guess passwords at full speed")


@lockout_risk
@pytest.mark.security
def test_forgot_password_is_rate_limited(api):
    """AUTH-API-061 — repeated reset requests are throttled (429) within 15 tries. RUN_LOCKOUT_TESTS=1 only."""
    codes = []
    for _ in range(15):
        r = api.post(EP.forgot_password, json={"email": "qa.flood@example.com"}, auth=False)
        codes.append(r.status_code)
        if r.status_code == 429:
            return
    check(False, "Reset-mail flood", "HTTP 429 within 15 requests", f"statuses: {codes}",
          hint="without throttling the endpoint can be used to spam any mailbox")
