"""
Beneficiary module, API (/api/v1/beneficiaries): functional, mandatory /
optional fields, account-number rules, duplicate beneficiary code, and
security.

Auth: API login needs the email OTP, so these tests use the bearer token of
the signed-in UI session (fixture `ui_token_api`).

Envelope (confirmed on UAT 2026-10-21):
    success -> {"success": true,  "message": ..., "data": {...}}
    failure -> {"success": false, "message": ..., "data": {"code": "VALIDATION_ERROR" | ...},
                "errors": [{"field": "beneName", "message": ...}, ...]}

Data policy: validation tests send an otherwise-valid body with one bad field,
so nothing is created while the server enforces its rules. Only the tests
marked "Creates" register a 'QA Auto' beneficiary.
"""
from __future__ import annotations

import json
import re

import pytest

from config.settings import settings
from utils.checks import check, describe, expect_api
from utils.assertions import (SQLI_PAYLOADS, XSS_PAYLOADS, assert_no_sensitive,
                              assert_security_headers, is_masked)
from utils.data_factory import beneficiary_payload

pytestmark = [pytest.mark.api, pytest.mark.functional]

EP = settings.endpoints
BEN = EP.beneficiaries
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
MANDATORY = {"beneCode", "beneName", "beneAccNum", "beneIfscCode", "beneEmailAddr1"}
UNKNOWN_REF = "00000000-0000-0000-0000-000000000000"


# ------------------------------------------------------------------- helpers
def issue_code(api) -> str:
    body = expect_api(api.post(EP.beneficiary_code, json={}), "Issue a beneficiary code (test setup)", status=200)
    return body["data"]["beneCode"]


def error_fields(r) -> set[str]:
    try:
        return {e.get("field") for e in (r.json().get("errors") or [])}
    except ValueError:
        return set()


def error_code(r) -> str:
    try:
        return ((r.json().get("data") or {}).get("code")) or ""
    except ValueError:
        return ""


def list_page(api, **params) -> dict:
    r = api.get(BEN, params={"page": 0, "size": 25, **params})
    return expect_api(r, f"List beneficiaries {params or ''}".strip(), status=200)["data"]


@pytest.fixture
def first_beneficiary(ui_token_api) -> dict:
    items = list_page(ui_token_api)["content"]
    if not items:
        pytest.skip("No beneficiaries on UAT to read")
    return items[0]


def assert_refused(r, field: str | None = None, allowed: tuple = (400, 422), what: str = "") -> None:
    """A validation refusal: 4xx (never 2xx / 5xx), naming `field` when given.
    A 403 from the web firewall (no JSON errors) is passed via `allowed`."""
    body = json.loads(r.request.body or "{}") if r.request.body else {}
    title = what or (f"Register a beneficiary with {field}={body.get(field)!r}" if field else "Register a beneficiary")
    hint = ""
    if r.status_code in (200, 201):
        created = (r.json().get("data") or {})
        hint = (f"the API ACCEPTED it and CREATED beneficiary {created.get('beneCode')} "
                f"(ref {created.get('beneficiaryReference')}) — the server is missing this rule; "
                "the record is now on UAT and was sent to the bank")
    elif r.status_code >= 500:
        hint = "server error — the bad value was not validated before reaching the bank/database"
    expect_api(r, title, status=allowed,
               fields=[field] if field and r.status_code in (400, 422) else None, hint=hint)


# ================================================================ functional
@pytest.mark.smoke
@pytest.mark.positive
def test_list_beneficiaries(ui_token_api):
    """API-BEN-001 — the list returns the envelope and paging fields."""
    r = ui_token_api.get(BEN, params={"page": 0, "size": 25})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("content", "number", "size", "totalElements"):
        assert key in data, f"Paging field '{key}' missing"
    assert data["size"] == 25 and data["number"] == 0


@pytest.mark.positive
def test_list_item_shape(ui_token_api, first_beneficiary):
    """API-BEN-002 — each item carries the fields the screen needs."""
    for key in ("beneficiaryReference", "beneCode", "beneName", "status", "registrationStatus", "createdAt"):
        assert key in first_beneficiary, f"Item field '{key}' missing"
    assert first_beneficiary["status"] in ("PENDING", "ACTIVE", "INACTIVE", "BLOCKED", "REJECTED")
    assert first_beneficiary["registrationStatus"] in ("NOT_REGISTERED", "PENDING", "SUCCESS", "FAILED", "REJECTED")


@pytest.mark.positive
def test_get_beneficiary_detail(ui_token_api, first_beneficiary):
    """API-BEN-003 — detail by reference returns the same beneficiary with bank fields."""
    ref = first_beneficiary["beneficiaryReference"]
    r = ui_token_api.get(f"{BEN}/{ref}")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["beneficiaryReference"] == ref and d["beneCode"] == first_beneficiary["beneCode"]
    for key in ("attemptCount", "updatedAt"):
        assert key in d, f"Detail field '{key}' missing"


@pytest.mark.positive
def test_search_by_code(ui_token_api, first_beneficiary):
    """API-BEN-004 — search by code returns that beneficiary."""
    code = first_beneficiary["beneCode"]
    codes = [i["beneCode"] for i in list_page(ui_token_api, search=code)["content"]]
    assert code in codes


@pytest.mark.positive
def test_issue_code_format_and_uniqueness(ui_token_api):
    """API-BEN-005 — issued codes match the code format and are never repeated."""
    codes = [issue_code(ui_token_api) for _ in range(5)]
    bad = [c for c in codes if not CODE_RE.match(c)]
    assert not bad, f"Badly formed codes: {bad}"
    assert len(set(codes)) == 5, f"Repeated codes: {codes}"


@pytest.mark.negative
def test_issued_code_not_in_use(ui_token_api):
    """API-BEN-006 — a newly issued code does not belong to an existing beneficiary."""
    code = issue_code(ui_token_api)
    assert not [i for i in list_page(ui_token_api, search=code)["content"] if i["beneCode"] == code]


@pytest.mark.negative
def test_unknown_reference_404(ui_token_api):
    """API-BEN-007 — an unknown reference is 404 NOT_FOUND."""
    r = ui_token_api.get(f"{BEN}/{UNKNOWN_REF}")
    assert r.status_code == 404 and error_code(r) == "NOT_FOUND"


@pytest.mark.negative
@pytest.mark.parametrize("ref", ["abc", "..%2F..%2Fetc%2Fpasswd", "' OR 1=1--", "1" * 300, "%00"])
def test_malformed_reference_handled(ui_token_api, ref):
    """API-BEN-008 — malformed references are refused cleanly (4xx, never 5xx)."""
    r = ui_token_api.get(f"{BEN}/{ref}")
    assert 400 <= r.status_code < 500, f"Reference {ref[:30]!r} gave HTTP {r.status_code}"


@pytest.mark.negative
@pytest.mark.parametrize("action", ["enquiry", "toggle-status"])
def test_actions_on_unknown_reference_404(ui_token_api, action):
    """API-BEN-009 — Check status / Block on an unknown reference is 404."""
    method = "POST" if action == "enquiry" else "PATCH"
    r = ui_token_api.request(method, f"{BEN}/{UNKNOWN_REF}/{action}", json={})
    assert r.status_code == 404, f"{action} on unknown reference gave HTTP {r.status_code}"


# ===================================================== mandatory / optional
@pytest.mark.negative
def test_empty_body_lists_every_mandatory_field(ui_token_api):
    """API-BEN-010 — {} is refused with VALIDATION_ERROR naming all five mandatory
    fields — and not the optional mobile."""
    r = ui_token_api.post(BEN, json={})
    assert_refused(r)
    assert error_code(r) == "VALIDATION_ERROR"
    fields = error_fields(r)
    assert MANDATORY <= fields, f"Mandatory fields not reported: {MANDATORY - fields}"
    assert "beneMobileNo" not in fields, "Optional mobile reported as required"


@pytest.mark.negative
@pytest.mark.parametrize("field", sorted(MANDATORY))
def test_each_mandatory_field_missing(ui_token_api, field):
    """API-BEN-011 — a valid body without one mandatory field is refused."""
    body = beneficiary_payload(issue_code(ui_token_api))
    body.pop(field)
    assert_refused(ui_token_api.post(BEN, json=body), field)


@pytest.mark.negative
@pytest.mark.parametrize("field", sorted(MANDATORY))
@pytest.mark.parametrize("blank", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_each_mandatory_field_blank(ui_token_api, field, blank):
    """API-BEN-012 — empty, spaces-only or null in a mandatory field is refused."""
    body = beneficiary_payload(issue_code(ui_token_api))
    body[field] = blank
    assert_refused(ui_token_api.post(BEN, json=body), field)


# ============================================================ field rules
INVALID_VALUES = [
    ("beneAccNum", "12345678", "8_digits"),
    ("beneAccNum", "1234567890123456789", "19_digits"),
    ("beneAccNum", "5010abc0123456", "letters"),
    ("beneAccNum", "5010-0123-4567", "dashes"),
    ("beneAccNum", "50100 1234567", "space"),
    ("beneAccNum", "-123456789", "negative"),
    ("beneIfscCode", "HDFC000123", "ifsc_10"),
    ("beneIfscCode", "HDFC00012345", "ifsc_12"),
    ("beneIfscCode", "HDFC1001234", "ifsc_5th_not_0"),
    ("beneIfscCode", "1234567890A", "ifsc_digits_first"),
    ("beneIfscCode", "HDFC0-01234", "ifsc_symbol"),
    ("beneEmailAddr1", "abc", "email_no_at"),
    ("beneEmailAddr1", "abc@x", "email_no_domain_dot"),
    ("beneEmailAddr1", "a b@x.com", "email_space"),
    ("beneEmailAddr1", "abc@@x.com", "email_double_at"),
    ("beneMobileNo", "98765", "mobile_5"),
    ("beneMobileNo", "98765432101", "mobile_11"),
    ("beneMobileNo", "abcdefghij", "mobile_letters"),
    ("beneMobileNo", "+919876543210", "mobile_country_code"),
    ("beneName", "A" * 300, "name_300_chars"),
    ("beneCode", "EX CODE 01", "code_spaces"),
    ("beneCode", "X" * 51, "code_51_chars"),
    ("beneCode", "EX<001>", "code_symbols"),
]


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("field,value", [(f, v) for f, v, _ in INVALID_VALUES],
                         ids=[i for _, _, i in INVALID_VALUES])
def test_invalid_field_value_refused(ui_token_api, field, value):
    """API-BEN-013 — the server enforces each field rule itself (not only the UI)."""
    body = beneficiary_payload(issue_code(ui_token_api))
    body[field] = value
    assert_refused(ui_token_api.post(BEN, json=body), field)


@pytest.mark.negative
@pytest.mark.parametrize("field,value", [("beneName", ["QA"]), ("beneEmailAddr1", {"a": 1}),
                                         ("beneAccNum", True), ("beneIfscCode", ["SBIN0000001"])],
                         ids=["name_array", "email_object", "acc_boolean", "ifsc_array"])
def test_wrong_json_types_refused(ui_token_api, field, value):
    """API-BEN-014 — wrong JSON types are refused cleanly (4xx), not 5xx.
    (A JSON number for account/mobile is coerced to text by the server — accepted by design.)"""
    body = beneficiary_payload(issue_code(ui_token_api))
    body[field] = value
    r = ui_token_api.post(BEN, json=body)
    assert r.status_code not in (200, 201) and r.status_code < 500, f"HTTP {r.status_code}: {r.text[:200]}"


@pytest.mark.negative
def test_malformed_json_refused(ui_token_api):
    """API-BEN-015 — a malformed JSON body is 400, not 500."""
    r = ui_token_api.post(BEN, data='{"beneName": "QA",', headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 500, f"Malformed JSON gave HTTP {r.status_code}"


# ===================================================== create + duplicates
@pytest.mark.positive
def test_create_mandatory_only_then_duplicate_code_refused(ui_token_api, report):
    """API-BEN-020 — Creates. A body with only the mandatory fields (no mobile) is
    registered; the account is masked in the reply and the detail. Re-sending the
    SAME body is an idempotent retry (same beneficiary back, nothing new); the same
    code for a DIFFERENT payee is refused as a duplicate."""
    code = issue_code(ui_token_api)
    body = beneficiary_payload(code, with_mobile=False)
    report.data(code=code, name=body["beneName"], ifsc=body["beneIfscCode"], account_last4=body["beneAccNum"][-4:])
    with report.step("Create with mandatory fields only"):
        r = ui_token_api.post(BEN, json=body)
        created = expect_api(r, "Register with the mandatory fields only (no mobile)", status=(200, 201))["data"]
        check(created["beneCode"] == code, "Code in the create reply", code, created["beneCode"])
        check(is_masked(created["beneAccNum"]) and created["beneAccNum"].endswith(body["beneAccNum"][-4:]),
              "Account in the create reply", f"masked, ending {body['beneAccNum'][-4:]}", created["beneAccNum"])
        check(body["beneAccNum"] not in r.text, "Full account number in the create reply", "absent", "echoed back")
    with report.step("Detail shows it, masked, without a mobile"):
        d = ui_token_api.get(f"{BEN}/{created['beneficiaryReference']}").json()["data"]
        for key in ("beneName", "beneIfscCode", "beneEmailAddr1"):
            check(d[key] == body[key], f"Detail {key}", body[key], d[key])
        check(not d.get("beneMobileNo"), "Detail mobile", "empty (none was sent)", d.get("beneMobileNo"))
        check(is_masked(d["beneAccNum"]), "Detail account", "masked", d["beneAccNum"])
    with report.step("Same request again (retry after a timeout) returns the same beneficiary"):
        again = expect_api(ui_token_api.post(BEN, json=body), "Re-send the identical request (retry)",
                           status=(200, 201))["data"]
        check(again["beneficiaryReference"] == created["beneficiaryReference"], "Retry of the same request",
              f"the same beneficiary {created['beneficiaryReference']}", again["beneficiaryReference"],
              hint="a retry after a timeout must not create a second payee")
    with report.step("Same code, different payee, is refused"):
        dup = ui_token_api.post(BEN, json=beneficiary_payload(code))
        report.actual(f"Same code, other payee: {describe(dup)}")
        expect_api(dup, f"Register a DIFFERENT payee with the used code {code}", status=(400, 409, 422),
                   code="DUPLICATE_REFERENCE",
                   hint="the form only shows 'code already in use' and issues a fresh code on DUPLICATE_REFERENCE; "
                        "any other code leaves the user stuck with a misleading message")
    matches = [i for i in list_page(ui_token_api, search=code)["content"] if i["beneCode"] == code]
    check(len(matches) == 1, f"Beneficiaries carrying code {code}", "exactly 1", len(matches))


@pytest.mark.negative
def test_duplicate_of_existing_code_refused(ui_token_api, first_beneficiary):
    """API-BEN-021 — an existing beneficiary's code cannot be registered again."""
    code = first_beneficiary["beneCode"]
    before = list_page(ui_token_api)["totalElements"]
    r = ui_token_api.post(BEN, json=beneficiary_payload(code))
    expect_api(r, f"Register a new payee with the existing code {code}", status=(400, 409, 422),
               code="DUPLICATE_REFERENCE",
               hint="the form only recovers (fresh code + clear message) on DUPLICATE_REFERENCE")
    after = list_page(ui_token_api)["totalElements"]
    check(after == before, "Beneficiary count after the duplicate attempt", before, after,
          hint="a beneficiary was created with a duplicate code")


@pytest.mark.negative
@pytest.mark.parametrize("variant", ["lower_case", "leading_trailing_spaces"])
def test_duplicate_code_variants_refused(ui_token_api, first_beneficiary, variant):
    """API-BEN-022 — a case or whitespace variant of an existing code must not create
    a second payee that looks the same (refused as duplicate or as invalid)."""
    code = first_beneficiary["beneCode"]
    variant_code = code.lower() if variant == "lower_case" else f"  {code}  "
    if variant_code == code:
        pytest.skip("Code has no letters to change case")
    r = ui_token_api.post(BEN, json=beneficiary_payload(variant_code))
    assert_refused(r, what=f"Register with {variant_code!r}, a variant of the existing code {code}",
                   allowed=(400, 409, 422))


@pytest.mark.negative
def test_same_account_and_ifsc_twice(ui_token_api, report):
    """API-BEN-023 — Creates. Registering the same account + IFSC under a second code
    should be refused or flagged (the same payee twice)."""
    first = beneficiary_payload(issue_code(ui_token_api))
    expect_api(ui_token_api.post(BEN, json=first), "First registration (test setup)", status=(200, 201))
    second = beneficiary_payload(issue_code(ui_token_api))
    second.update(beneAccNum=first["beneAccNum"], beneIfscCode=first["beneIfscCode"])
    r2 = ui_token_api.post(BEN, json=second)
    report.actual(f"Second create with the same account + IFSC: {describe(r2)}")
    assert_refused(r2, what="Register the same account + IFSC again under a new code",
                   allowed=(400, 409, 422))


# ================================================================== security
@pytest.mark.security
@pytest.mark.parametrize("call", [("GET", ""), ("GET", f"/{UNKNOWN_REF}"), ("POST", ""),
                                  ("POST", "/code"), ("POST", f"/{UNKNOWN_REF}/enquiry"),
                                  ("PATCH", f"/{UNKNOWN_REF}/toggle-status")],
                         ids=["list", "detail", "create", "issue_code", "enquiry", "toggle_status"])
def test_every_endpoint_requires_token(api, call):
    """API-BEN-030 — every beneficiary endpoint refuses an anonymous call with 401."""
    method, suffix = call
    r = api.request(method, BEN + suffix, auth=False, json={} if method != "GET" else None)
    expect_api(r, f"{method} {BEN + suffix} without a token", status=401, code="UNAUTHORIZED")


@pytest.mark.security
@pytest.mark.parametrize("auth", ["Bearer abc.def.ghi", "Bearer ", "Basic YWRtaW46YWRtaW4=", "Bearer null"],
                         ids=["tampered", "empty_bearer", "basic", "null"])
def test_bad_tokens_rejected(api, auth):
    """API-BEN-031 — tampered, empty or wrong-scheme credentials are 401."""
    r = api.get(BEN, auth=False, headers={"Authorization": auth})
    assert r.status_code == 401, f"{auth.split()[0]} credential gave HTTP {r.status_code}"


@pytest.mark.security
def test_altered_token_signature_rejected(api, admin_token):
    """API-BEN-032 — the real token with its signature changed is rejected."""
    head, payload, sig = admin_token.split(".")
    forged = f"{head}.{payload}.{sig[:-2] + ('AA' if sig[-2:] != 'AA' else 'BB')}"
    r = api.get(BEN, auth=False, headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401, f"Forged signature accepted: HTTP {r.status_code}"


@pytest.mark.security
def test_unsigned_alg_none_token_rejected(api, admin_token):
    """API-BEN-033 — an alg=none token with the real claims is rejected."""
    import base64
    none_head = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    payload = admin_token.split(".")[1]
    r = api.get(BEN, auth=False, headers={"Authorization": f"Bearer {none_head}.{payload}."})
    assert r.status_code == 401, f"alg=none token accepted: HTTP {r.status_code}"


@pytest.mark.security
def test_accounts_masked_in_list_response(ui_token_api):
    """API-BEN-034 — no full account number anywhere in the list response."""
    r = ui_token_api.get(BEN, params={"page": 0, "size": 100})
    items = r.json()["data"]["content"]
    unmasked = [i["beneCode"] for i in items if i.get("beneAccNum") and not is_masked(i["beneAccNum"])]
    assert not unmasked, f"Unmasked accounts for: {unmasked}"
    # mobiles are 10 raw digits by design; only account fields must never be raw
    assert not re.search(r'"beneAccNum"\s*:\s*"\d{5,}"', r.text), "A raw account number is in the response"


@pytest.mark.security
def test_account_masked_in_detail_response(ui_token_api, first_beneficiary):
    """API-BEN-035 — the detail response masks the account too."""
    d = ui_token_api.get(f"{BEN}/{first_beneficiary['beneficiaryReference']}").json()["data"]
    assert not d.get("beneAccNum") or is_masked(d["beneAccNum"]), f"Detail shows {d['beneAccNum']!r}"


@pytest.mark.security
def test_no_sensitive_fields_in_responses(ui_token_api, first_beneficiary):
    """API-BEN-036 — no password / OTP / secret / token keys in list or detail."""
    for r in (ui_token_api.get(BEN), ui_token_api.get(f"{BEN}/{first_beneficiary['beneficiaryReference']}")):
        hits = assert_no_sensitive(r.text)
        assert not hits, f"Sensitive keys in {r.url}: {hits}"


@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_in_search(ui_token_api, payload):
    """API-BEN-037 — SQL in the search parameter neither errors nor widens the result."""
    r = ui_token_api.get(BEN, params={"search": payload, "page": 0, "size": 25})
    assert r.status_code < 500, f"HTTP {r.status_code} for {payload!r}"
    assert "sql" not in r.text.lower() and "syntax" not in r.text.lower(), "Database error leaked"
    if r.status_code == 200:
        assert r.json()["data"]["totalElements"] == 0, f"SQL payload {payload!r} matched rows"


@pytest.mark.security
@pytest.mark.parametrize("payload", XSS_PAYLOADS[:1] + ["Robert'); DROP TABLE beneficiaries;--"],
                         ids=["script_tag", "sql_in_name"])
def test_markup_and_sql_in_name_refused(ui_token_api, payload):
    """API-BEN-038 — a name with markup or SQL is refused (bank names are plain text).
    Creates a beneficiary only if the server wrongly accepts it."""
    body = beneficiary_payload(issue_code(ui_token_api))
    body["beneName"] = payload
    # 403 = blocked by the web firewall before the app, which is also a refusal
    assert_refused(ui_token_api.post(BEN, json=body), "beneName", allowed=(400, 403, 422))


@pytest.mark.security
def test_mass_assignment_ignored(ui_token_api):
    """API-BEN-039 — Creates. Status / registration / reference fields in the body are
    ignored: a new payee is never ACTIVE or SUCCESS before the bank confirms."""
    code = issue_code(ui_token_api)
    body = beneficiary_payload(code)
    body.update(status="ACTIVE", registrationStatus="SUCCESS", beneficiaryReference=UNKNOWN_REF,
                bankReference="QA-FORGED", attemptCount=99, createdAt="2000-01-01T00:00:00Z")
    r = ui_token_api.post(BEN, json=body)
    if r.status_code in (400, 422):
        return  # refusing unknown fields outright is also correct
    assert r.status_code in (200, 201), f"HTTP {r.status_code}: {r.text[:200]}"
    d = ui_token_api.get(f"{BEN}/{r.json()['data']['beneficiaryReference']}").json()["data"]
    assert d["beneficiaryReference"] != UNKNOWN_REF, "Client chose the beneficiary reference"
    assert d.get("bankReference") != "QA-FORGED", "Client set the bank reference"
    assert d.get("attemptCount") != 99 and not d["createdAt"].startswith("2000"), "Client set server fields"
    if d["registrationStatus"] == "SUCCESS":
        assert d.get("bankMessage"), "Marked SUCCESS with no bank confirmation"


@pytest.mark.security
@pytest.mark.parametrize("method,suffix", [("DELETE", "/{ref}"), ("PUT", "/{ref}"), ("PUT", ""),
                                           ("DELETE", ""), ("TRACE", "")])
def test_unsupported_methods_refused(ui_token_api, first_beneficiary, method, suffix):
    """API-BEN-040 — beneficiaries cannot be deleted / overwritten via other verbs."""
    path = BEN + suffix.format(ref=first_beneficiary["beneficiaryReference"])
    r = ui_token_api.request(method, path, json={} if method in ("PUT",) else None)
    assert r.status_code in (403, 404, 405, 501), f"{method} {suffix or '/'} gave HTTP {r.status_code}"


@pytest.mark.security
def test_security_headers_on_beneficiary_api(ui_token_api):
    """API-BEN-041 — security headers present and the response is not cached."""
    r = ui_token_api.get(BEN)
    missing = assert_security_headers(dict(r.headers))
    assert not missing, f"Missing security headers: {missing}"
    assert "no-store" in r.headers.get("Cache-Control", ""), "Beneficiary data may be cached"


@pytest.mark.security
def test_security_headers_sent_once(ui_token_api):
    """API-BEN-046 — each security header is set once (proxy + app both setting it
    gives 'DENY, DENY', which some clients treat as invalid and ignore)."""
    r = ui_token_api.get(BEN)
    doubled = {}
    for h in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Strict-Transport-Security"):
        if "," in r.headers.get(h, ""):
            doubled[h] = r.headers[h]
    if r.headers.get("Content-Security-Policy", "").count("default-src") > 1:
        doubled["Content-Security-Policy"] = "two policies"
    assert not doubled, f"Headers set more than once: {doubled}"


@pytest.mark.security
def test_cors_does_not_trust_foreign_origin(ui_token_api):
    """API-BEN-042 — a foreign Origin is not echoed back as allowed."""
    r = ui_token_api.get(BEN, headers={"Origin": "https://evil.example.com"})
    acao = r.headers.get("Access-Control-Allow-Origin", "")
    assert acao not in ("*", "https://evil.example.com"), f"CORS allows {acao!r}"


@pytest.mark.security
@pytest.mark.parametrize("size", [1000, 100000])
def test_page_size_is_capped(ui_token_api, size):
    """API-BEN-043 — a huge page size is capped or refused (no bulk dump in one call)."""
    r = ui_token_api.get(BEN, params={"page": 0, "size": size})
    assert r.status_code < 500
    if r.status_code == 200:
        assert r.json()["data"]["size"] <= 100, f"size={size} honoured (returned size {r.json()['data']['size']})"


@pytest.mark.negative
@pytest.mark.parametrize("params", [{"page": -1}, {"size": 0}, {"size": -5}, {"page": "abc"}],
                         ids=["page_-1", "size_0", "size_-5", "page_text"])
def test_bad_paging_handled(ui_token_api, params):
    """API-BEN-044 — invalid paging values are handled (4xx or clamped), never 5xx."""
    r = ui_token_api.get(BEN, params=params)
    assert r.status_code < 500, f"{params} gave HTTP {r.status_code}"


@pytest.mark.security
def test_issue_code_rate_or_volume_sane(ui_token_api):
    """API-BEN-045 — issuing 20 codes quickly does not error (and may be rate-limited)."""
    statuses = [ui_token_api.post(EP.beneficiary_code, json={}).status_code for _ in range(20)]
    assert all(s in (200, 429) for s in statuses), f"Unexpected statuses: {statuses}"
