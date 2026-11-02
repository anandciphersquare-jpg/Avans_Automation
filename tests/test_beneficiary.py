"""
Beneficiary module, UI (Workflow 4): the whole Beneficiary List screen, the
Add beneficiary form and the details panel.

Field rules (live UAT build, 2026-10-21):
    Beneficiary code   system-issued on form open, read-only
    Beneficiary name   mandatory
    Account number     mandatory, 9-18 digits
    Confirm account    mandatory, must match, paste blocked
    IFSC               mandatory, 4 letters + 0 + 6 letters/digits (typed upper-case)
    Mobile number      OPTIONAL, 10 digits when given
    Email address      mandatory, valid address

Data policy: most form checks fake the create call (page.route), so nothing
reaches the bank. Only test_register_valid_beneficiary_end_to_end and the
duplicate-code test send a real request; their names start with 'QA Auto'.
"""
from __future__ import annotations

import re

import pytest

from pages.beneficiary_page import (CODE_RE, COLUMNS, MSG, REGISTRATION_LABELS,
                                    BeneficiaryPage)
from utils.assertions import (FULL_ACCOUNT_RE, INVALID_EMAILS, SQLI_PAYLOADS,
                              XSS_PAYLOADS, is_masked)
from utils.checks import check
from utils.data_factory import new_beneficiary

pytestmark = [pytest.mark.functional, pytest.mark.ui]

MANDATORY = ["name", "account_number", "confirm_account_number", "ifsc", "email"]
OPTIONAL = ["mobile"]


def _open_form(page) -> BeneficiaryPage:
    return BeneficiaryPage(page).open().open_add_form()


def _dialog_watch(page) -> dict:
    """Record whether any JS dialog (alert/confirm) fires — an XSS tell."""
    fired = {"count": 0}

    def on_dialog(d):
        fired["count"] += 1
        d.dismiss()

    page.on("dialog", on_dialog)
    return fired


# =============================================================== full screen
@pytest.mark.smoke
@pytest.mark.positive
def test_list_screen_layout(logged_in_page, report):
    """BEN-UI-001 — heading, subtitle, search, Reset Filters, Add Beneficiary,
    all eight columns, and the 'Showing N' count all render."""
    bp = BeneficiaryPage(logged_in_page).open()
    body = logged_in_page.inner_text("body")
    report.expected("Full Beneficiary List screen renders with every control and column")
    assert "Payees registered with the bank" in body, "Subtitle missing"
    assert logged_in_page.locator("#q").get_attribute("placeholder") == "Search by code or name…"
    assert bp.button("Reset Filters").is_visible(), "Reset Filters missing"
    assert bp.button("Add Beneficiary").is_visible(), "Add Beneficiary missing"
    headers = [h.lower() for h in bp.column_headers()]
    missing = [c for c in COLUMNS if c.lower() not in headers]
    assert not missing, f"Columns missing: {missing} (found {headers})"
    count = bp.showing_count()
    report.actual(f"Showing {count} beneficiaries; {bp.rows().count()} rows on page 1")
    assert bp.rows().count() == min(count, 25), "Row count does not match the 'Showing N' total (page size 25)"


@pytest.mark.positive
def test_side_menu_marks_beneficiary_list_active(logged_in_page):
    """BEN-UI-002 — the Beneficiary List menu entry routes to /beneficiaries."""
    BeneficiaryPage(logged_in_page).open()
    link = logged_in_page.get_by_role("link", name="Beneficiary List").first
    assert link.get_attribute("href") == "/beneficiaries"
    assert logged_in_page.url.rstrip("/").endswith("/beneficiaries")


@pytest.mark.security
def test_every_account_masked_in_list(logged_in_page):
    """BEN-UI-003 — the Account column shows the last four digits only."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    unmasked = [a for a in bp.column_values("Account") if a != "—" and not is_masked(a)]
    assert not unmasked, f"Unmasked account numbers in the list: {unmasked}"
    assert not FULL_ACCOUNT_RE.search(logged_in_page.inner_text("table")), "A full account number is in the grid"


@pytest.mark.positive
def test_registration_and_status_values_are_known(logged_in_page):
    """BEN-UI-004 — Registration shows one of the documented labels for every row."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    unknown = [v for v in bp.column_values("Registration") if v not in REGISTRATION_LABELS]
    assert not unknown, f"Unexpected Registration labels: {unknown}"


@pytest.mark.positive
def test_search_by_exact_code(logged_in_page):
    """BEN-UI-005 — searching a code lists that beneficiary."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    code = bp.column_values("Code")[0]
    bp.search(code)
    assert code in bp.column_values("Code"), f"{code} not found by search"


@pytest.mark.positive
def test_search_by_partial_name(logged_in_page):
    """BEN-UI-006 — searching part of a name lists matching beneficiaries only."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    name = bp.column_values("Name")[0]
    term = name.split()[0][:4]
    bp.search(term)
    names = bp.column_values("Name")
    assert names, f"No rows for '{term}'"
    assert all(term.lower() in n.lower() for n in names) or any(term.lower() in c.lower()
                                                               for c in bp.column_values("Code")), \
        f"Search '{term}' returned non-matching rows: {names}"


@pytest.mark.negative
def test_search_no_match_shows_empty_state_and_reset_restores(logged_in_page):
    """BEN-UI-007 — a search with no match shows the empty state; Reset Filters brings the list back."""
    bp = BeneficiaryPage(logged_in_page).open()
    total = bp.showing_count()
    bp.search("QA-NO-SUCH-PAYEE-9X9")
    assert bp.showing_count() == 0, "Search with no match still lists rows"
    bp.reset_filters()
    assert logged_in_page.locator("#q").input_value() == "", "Reset Filters did not clear the search box"
    assert bp.showing_count() == total, "Reset Filters did not restore the full list"


@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS + XSS_PAYLOADS)
def test_search_box_injection_is_harmless(logged_in_page, payload):
    """BEN-UI-008 — SQL / script payloads in search neither error nor execute."""
    fired = _dialog_watch(logged_in_page)
    bp = BeneficiaryPage(logged_in_page).open()
    bp.search(payload)
    body = logged_in_page.inner_text("body").lower()
    assert fired["count"] == 0, "Search payload executed a script dialog"
    assert not any(s in body for s in ("sql", "syntax error", "exception", "stack trace")), \
        "Search payload surfaced a server error"
    # search is literal: rows may only match when a name/code really contains the text
    stray = [n for n, c in zip(bp.column_values("Name"), bp.column_values("Code"))
             if payload.lower() not in n.lower() and payload.lower() not in c.lower()]
    assert not stray, f"Payload {payload!r} matched unrelated rows: {stray}"


@pytest.mark.positive
def test_details_panel_shows_all_sections(logged_in_page):
    """BEN-UI-009 — clicking a code opens the details with Payee and With-the-bank sections."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    code = bp.column_values("Code")[0]
    bp.open_details(code)
    labels = bp.detail_labels()
    for want in ("Beneficiary code", "Name", "Account", "IFSC", "Status with us", "Added", "Registration"):
        assert want in labels, f"Details panel is missing '{want}' (has {labels})"
    assert bp.detail_value("Beneficiary code") == code
    assert bp.detail_description() == f"Beneficiary code {code}"
    assert bp.dialog.get_by_role("button", name="Check status").is_visible()


@pytest.mark.security
def test_account_masked_in_details(logged_in_page):
    """BEN-UI-010 — the details panel shows the account masked (last 4)."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    bp.open_details(bp.column_values("Code")[0])
    shown = bp.masked_account_text()
    assert shown and is_masked(shown), f"Account not masked in details: {shown!r}"


@pytest.mark.positive
def test_block_button_only_for_active_or_blocked(logged_in_page):
    """BEN-UI-011 — Block/Unblock is offered only when Status is ACTIVE or BLOCKED."""
    bp = BeneficiaryPage(logged_in_page).open()
    statuses = dict(zip(bp.column_values("Code"), bp.column_values("Status")))
    if not statuses:
        pytest.skip("No beneficiaries listed")
    for code, status in list(statuses.items())[:4]:
        bp.open_details(code)
        has_toggle = (bp.dialog.get_by_role("button", name="Block", exact=True).count()
                      + bp.dialog.get_by_role("button", name="Unblock", exact=True).count()) > 0
        expected = status.strip().upper() in ("ACTIVE", "BLOCKED")
        assert has_toggle == expected, f"{code} ({status}): Block/Unblock shown={has_toggle}"
        bp.close_dialog()


@pytest.mark.negative
def test_block_confirmation_cancel_keeps_status(logged_in_page):
    """BEN-UI-012 — cancelling the 'Block this beneficiary?' confirmation changes nothing."""
    bp = BeneficiaryPage(logged_in_page).open()
    active = [c for c, s in zip(bp.column_values("Code"), bp.column_values("Status")) if s.upper() == "ACTIVE"]
    if not active:
        pytest.skip("No ACTIVE beneficiary to try")
    bp.open_details(active[0])
    bp.block(confirm=False)
    logged_in_page.wait_for_timeout(500)
    assert bp.dialog.get_by_role("button", name="Block", exact=True).is_visible(), "Status changed after Cancel"


@pytest.mark.functional
def test_block_then_unblock_round_trip(logged_in_page, report):
    """BEN-UI-013 — Block (with confirmation) then Unblock; status returns to ACTIVE.
    Touches shared data briefly; always restores the original state."""
    bp = BeneficiaryPage(logged_in_page).open()
    active = [c for c, s in zip(bp.column_values("Code"), bp.column_values("Status")) if s.upper() == "ACTIVE"]
    if not active:
        pytest.skip("No ACTIVE beneficiary to try")
    code = active[0]
    report.data(beneficiary_code=code)
    bp.open_details(code)
    try:
        with report.step("Block with confirmation"):
            bp.block(confirm=True)
            bp.dialog.get_by_role("button", name="Unblock", exact=True).wait_for(timeout=15_000)
            assert "BLOCKED" in bp.detail_value("Status with us").upper()
    finally:
        with report.step("Unblock (restore)"):
            unblock = bp.dialog.get_by_role("button", name="Unblock", exact=True)
            if unblock.count():
                bp.unblock()
                bp.dialog.get_by_role("button", name="Block", exact=True).wait_for(timeout=15_000)
    assert "ACTIVE" in bp.detail_value("Status with us").upper(), "Unblock did not restore ACTIVE"


@pytest.mark.functional
def test_check_status_records_enquiry(logged_in_page):
    """BEN-UI-014 — Check status on a bank-confirmed (ACTIVE) payee asks the bank and
    updates 'Last checked'."""
    bp = BeneficiaryPage(logged_in_page).open()
    active = [c for c, s in zip(bp.column_values("Code"), bp.column_values("Status")) if s.upper() == "ACTIVE"]
    if not active:
        pytest.skip("No ACTIVE beneficiary to check with the bank")
    bp.open_details(active[0])
    with logged_in_page.expect_response(lambda r: "/enquiry" in r.url, timeout=30_000) as resp:
        bp.check_status()
    status, body = resp.value.status, resp.value.text()[:250]
    check(status < 500, f"Check status for {active[0]}", "HTTP 200 with the bank's answer", f"HTTP {status}: {body}",
          hint="5xx = the bank call failed (UPSTREAM_ERROR) for an already-active payee")
    bp.dialog.get_by_text(re.compile(r"^Last checked ")).wait_for(timeout=15_000)


@pytest.mark.negative
def test_check_status_bank_error_is_explained(logged_in_page):
    """BEN-UI-016 — when the bank cannot answer (status check fails), the user sees a
    clear message instead of nothing. The bank error is simulated."""
    import json as _json
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    logged_in_page.route("**/enquiry", lambda route: route.fulfill(
        status=502, content_type="application/json",
        body=_json.dumps({"success": False, "message": "QA: the bank did not answer",
                          "data": {"code": "UPSTREAM_ERROR"}})))
    bp.open_details(bp.column_values("Code")[0])
    bp.check_status()
    shown = logged_in_page.get_by_text("QA: the bank did not answer")
    try:
        shown.first.wait_for(timeout=8_000)
        visible = True
    except Exception:  # noqa: BLE001
        visible = False
    check(visible, "Bank error on Check status", "the error message shown to the user", "nothing shown")


@pytest.mark.positive
@pytest.mark.parametrize("how", ["close_button", "escape"])
def test_details_panel_closes(logged_in_page, how):
    """BEN-UI-015 — the details panel closes with the X button and with Escape."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No beneficiaries listed")
    bp.open_details(bp.column_values("Code")[0])
    bp.close_dialog() if how == "close_button" else logged_in_page.keyboard.press("Escape")
    bp.dialog.wait_for(state="hidden")


# ============================================================ add form: layout
@pytest.mark.smoke
@pytest.mark.positive
def test_add_form_fields_and_buttons(logged_in_page):
    """BEN-UI-020 — the form shows all seven fields, Cancel and Register with bank."""
    bp = _open_form(logged_in_page)
    for key, label in bp.LABELS.items():
        assert bp.input(key).is_visible(), f"Field '{label}' missing"
        assert bp.dialog.locator(f"label[for='{bp.FIELDS[key]}']").inner_text().startswith(label)
    assert bp.dialog.get_by_role("button", name="Cancel").is_visible()
    assert bp.dialog.get_by_role("button", name="Register with bank").is_enabled()


@pytest.mark.positive
def test_mandatory_and_optional_markers(logged_in_page):
    """BEN-UI-021 — only Mobile number is marked (optional); Email says Required."""
    bp = _open_form(logged_in_page)
    for key in MANDATORY + OPTIONAL:
        label = bp.dialog.locator(f"label[for='{bp.FIELDS[key]}']").inner_text().lower()
        if key in OPTIONAL:
            assert "optional" in label, f"'{label}' should be marked optional"
        else:
            assert "optional" not in label, f"Mandatory field '{label}' is marked optional"
    assert "Required." in bp.dialog.inner_text(), "Email hint should say it is required"


@pytest.mark.positive
def test_code_is_generated_and_read_only(logged_in_page):
    """BEN-UI-022 — the code is issued by the system, matches the code format and cannot be edited."""
    bp = _open_form(logged_in_page)
    code = bp.code_value()
    assert CODE_RE.match(code), f"Issued code has an unexpected format: {code!r}"
    field = bp.input("code")
    assert field.get_attribute("readonly") is not None and field.get_attribute("aria-readonly") == "true"
    assert not field.is_editable(), "The beneficiary code field is editable"
    field.click()
    logged_in_page.keyboard.type("X9")
    assert bp.code_value() == code, "Typing changed the beneficiary code"


@pytest.mark.positive
def test_new_code_each_time_form_opens(logged_in_page):
    """BEN-UI-023 — every form opening is issued a different code (no reuse)."""
    bp = BeneficiaryPage(logged_in_page).open()
    codes = []
    for _ in range(3):
        bp.open_add_form()
        codes.append(bp.code_value())
        bp.cancel()
        bp.dialog.wait_for(state="hidden")
    assert len(set(codes)) == 3, f"Codes repeated between openings: {codes}"


@pytest.mark.negative
def test_issued_code_not_already_in_list(logged_in_page):
    """BEN-UI-024 — a freshly issued code is not an existing beneficiary's code."""
    bp = BeneficiaryPage(logged_in_page).open()
    bp.open_add_form()
    code = bp.code_value()
    bp.cancel()
    bp.search(code)
    assert bp.showing_count() == 0, f"Issued code {code} already belongs to a beneficiary"


@pytest.mark.negative
@pytest.mark.parametrize("how", ["cancel", "close_button", "escape"])
def test_closing_form_creates_nothing(logged_in_page, how):
    """BEN-UI-025 — Cancel / X / Escape close the form without sending anything."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    bp.fill_form(new_beneficiary())
    {"cancel": bp.cancel, "close_button": bp.close_dialog,
     "escape": lambda: logged_in_page.keyboard.press("Escape")}[how]()
    bp.dialog.wait_for(state="hidden")
    assert not sent, "Closing the form sent a create request"


# ===================================================== mandatory / optional
@pytest.mark.negative
def test_empty_form_is_refused(logged_in_page):
    """BEN-UI-030 — submitting the empty form is refused with the first rule's message."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    bp.register()
    assert bp.form_error() == MSG["name"]
    assert not sent and bp.is_form_open()


@pytest.mark.negative
@pytest.mark.parametrize("missing", MANDATORY)
def test_each_mandatory_field_required(logged_in_page, missing, report):
    """BEN-UI-031 — leaving one mandatory field empty (all others valid) blocks registration."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    report.data(missing_field=missing)
    bp.fill_form(data, skip={missing})
    bp.register()
    err = bp.form_error()
    report.actual(err or "(no message)")
    assert err.startswith(MSG[missing]), f"Missing {missing}: expected '{MSG[missing]}', got '{err}'"
    assert not sent, f"Create request sent although {missing} was empty"


@pytest.mark.negative
@pytest.mark.parametrize("key,value", [("name", "     "), ("email", "   "), ("ifsc", "   ")])
def test_whitespace_only_counts_as_empty(logged_in_page, key, value):
    """BEN-UI-032 — spaces alone do not satisfy a mandatory field."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data[key] = value
    bp.fill_form(data)
    bp.register()
    assert bp.form_error().startswith(MSG[key])
    assert not sent


@pytest.mark.positive
def test_mobile_is_optional(logged_in_page):
    """BEN-UI-033 — all mandatory fields filled, Mobile blank: the form submits without beneMobileNo."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    bp.fill_form(new_beneficiary(with_mobile=False))
    bp.register()
    bp.dialog.wait_for(state="hidden")
    assert len(sent) == 1, "Form with blank optional mobile was not submitted"
    assert "beneMobileNo" not in sent[0], f"Blank mobile still sent: {sent[0].get('beneMobileNo')!r}"


@pytest.mark.positive
def test_all_fields_sent_correctly(logged_in_page):
    """BEN-UI-034 — the submitted payload carries every field exactly as entered."""
    bp = _open_form(logged_in_page)
    code = bp.code_value()
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    bp.fill_form(data)
    bp.register()
    bp.dialog.wait_for(state="hidden")
    assert sent == [{"beneCode": code, "beneName": data["name"], "beneAccNum": data["account_number"],
                     "beneIfscCode": data["ifsc"], "beneMobileNo": data["mobile"],
                     "beneEmailAddr1": data["email"]}], f"Unexpected payload: {sent}"


@pytest.mark.negative
@pytest.mark.parametrize("mobile", ["98765", "987654321", "98765432101", "abcdefghij", "+919876543210"])
def test_mobile_when_given_must_be_ten_digits(logged_in_page, mobile):
    """BEN-UI-035 — an optional mobile, once entered, must be exactly 10 digits."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["mobile"] = mobile
    bp.fill_form(data)
    bp.register()
    assert bp.form_error() == MSG["mobile"], f"Mobile {mobile!r} was not refused"
    assert not sent


@pytest.mark.negative
@pytest.mark.parametrize("email", INVALID_EMAILS)
def test_invalid_email_refused(logged_in_page, email):
    """BEN-UI-036 — malformed email addresses are refused."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["email"] = email
    bp.fill_form(data)
    bp.register()
    assert bp.form_error().startswith(MSG["email"]), f"Email {email!r} was not refused"
    assert not sent


# ========================================== account number + confirm account
@pytest.mark.positive
@pytest.mark.boundary
@pytest.mark.parametrize("length", [9, 18])
def test_account_number_length_boundaries_accepted(logged_in_page, length):
    """BEN-UI-040 — 9 and 18 digits (the limits) are accepted."""
    from utils.data_factory import bank_account
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["account_number"] = data["confirm_account_number"] = bank_account(length)
    bp.fill_form(data)
    bp.register()
    bp.dialog.wait_for(state="hidden")
    assert sent and sent[0]["beneAccNum"] == data["account_number"]


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("acc", ["12345678", "1234567890123456789", "1", "abcdefghijk"],
                         ids=["8_digits", "19_digits", "1_digit", "letters_only"])
def test_account_number_out_of_range_refused(logged_in_page, acc):
    """BEN-UI-041 — fewer than 9 / more than 18 digits, or no digits, are refused."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["account_number"] = data["confirm_account_number"] = acc
    bp.fill_form(data)
    bp.register()
    assert bp.form_error() == MSG["account_number"], f"Account {acc!r} was not refused"
    assert not sent


@pytest.mark.negative
@pytest.mark.parametrize("acc", ["5010abc0123456", "50100123456789@", "5010-0123-4567"],
                         ids=["letters_inside", "symbol", "dashes"])
def test_account_number_with_non_digits_refused(logged_in_page, acc):
    """BEN-UI-042 — an account number with letters or symbols must be refused,
    not silently cleaned (cleaning hides a typo in the payee's account)."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["account_number"] = data["confirm_account_number"] = acc
    bp.fill_form(data)
    bp.register()
    err = bp.form_error(timeout=2_000)
    check(not sent, f"Add beneficiary with account number {acc!r}",
          f"refused with '{MSG['account_number']}', nothing sent",
          f"accepted and sent to the API as {sent[0]['beneAccNum']!r}" if sent else "",
          hint="the form strips non-digits (value.replace(/\\D/g,'')) before checking, so a typo like "
               "letters or symbols is silently changed into a different account number")
    check(err == MSG["account_number"], "Account number message", MSG["account_number"], err)


@pytest.mark.negative
@pytest.mark.parametrize("variant", ["last_digit", "first_digit", "one_digit_short", "one_digit_extra", "swapped"])
def test_confirm_account_mismatch_refused(logged_in_page, variant):
    """BEN-UI-043 — any difference between Account and Confirm account is refused."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    acc = data["account_number"]
    data["confirm_account_number"] = {
        "last_digit": acc[:-1] + str((int(acc[-1]) + 1) % 10),
        "first_digit": str(int(acc[0]) % 9 + 1) + acc[1:],
        "one_digit_short": acc[:-1],
        "one_digit_extra": acc + "0",
        "swapped": acc[:-2] + acc[-1] + acc[-2] if acc[-1] != acc[-2] else acc[:-2] + "12",
    }[variant]
    bp.fill_form(data)
    bp.register()
    assert bp.form_error() == MSG["confirm_account_number"], f"Mismatch ({variant}) was not refused"
    assert not sent


@pytest.mark.positive
def test_confirm_account_match_accepted(logged_in_page):
    """BEN-UI-044 — identical Account and Confirm account pass."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    bp.fill_form(new_beneficiary())
    bp.register()
    bp.dialog.wait_for(state="hidden")
    assert len(sent) == 1


@pytest.mark.security
def test_paste_blocked_in_confirm_account(logged_in_page):
    """BEN-UI-045 — Confirm account number rejects paste (must be retyped)."""
    bp = _open_form(logged_in_page)
    assert bp.paste_into("confirm_account_number", "50100123456789") == "", "Paste into Confirm account worked"
    assert "do not paste" in (bp.input("confirm_account_number").get_attribute("placeholder") or "")


@pytest.mark.security
def test_account_fields_not_autofilled(logged_in_page):
    """BEN-UI-046 — both account inputs have autocomplete=off and a numeric keypad."""
    bp = _open_form(logged_in_page)
    for key in ("account_number", "confirm_account_number"):
        f = bp.input(key)
        assert f.get_attribute("autocomplete") == "off", f"{key} allows autocomplete"
        assert f.get_attribute("inputmode") == "numeric", f"{key} is not numeric input"


# ======================================================================= IFSC
@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("ifsc", ["HDFC000123", "HDFC00012345", "HDFCX001234", "HDFC1001234",
                                  "HDF0001234", "1234567890A", "HDFC0-01234", "HDFC 001234"])
def test_invalid_ifsc_refused(logged_in_page, ifsc):
    """BEN-UI-050 — IFSC must be 4 letters + '0' + 6 letters/digits (11 characters)."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["ifsc"] = ifsc
    bp.fill_form(data)
    bp.register()
    assert bp.form_error() == MSG["ifsc"], f"IFSC {ifsc!r} was not refused"
    assert not sent


@pytest.mark.positive
def test_ifsc_typed_lowercase_is_uppercased(logged_in_page):
    """BEN-UI-051 — a lower-case IFSC is shown and sent in upper case."""
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["ifsc"] = data["ifsc"].lower()
    bp.fill_form(data)
    assert bp.input("ifsc").input_value() == data["ifsc"].upper()
    bp.register()
    bp.dialog.wait_for(state="hidden")
    assert sent and sent[0]["beneIfscCode"] == data["ifsc"].upper()


# ============================================================ real creation
@pytest.mark.positive
def test_register_valid_beneficiary_end_to_end(logged_in_page, report):
    """BEN-UI-060 — a fully valid beneficiary is registered, listed, masked and searchable.
    Creates one 'QA Auto' beneficiary on UAT (sent to the bank)."""
    bp = _open_form(logged_in_page)
    code = bp.code_value()
    data = new_beneficiary()
    report.data(code=code, name=data["name"], ifsc=data["ifsc"], account_last4=data["account_number"][-4:])
    sent = bp.capture_create(mock=False)
    with report.step("Fill every field and register"):
        bp.fill_form(data)
        with logged_in_page.expect_response(lambda r: r.url.endswith("/api/v1/beneficiaries")
                                            and r.request.method == "POST", timeout=60_000) as resp:
            bp.register()
    status = resp.value.status
    report.actual(f"Create HTTP {status}")
    assert status in (200, 201), f"Create failed: HTTP {status} {resp.value.text()[:300]}"
    assert sent and sent[0]["beneCode"] == code
    bp.dialog.wait_for(state="hidden")
    with report.step("Find it in the list"):
        bp.search(code)
        row = bp.row_for(code)
        assert row.count() == 1, f"{code} not listed after registration"
        acc = bp.column_values("Account")[0]
        assert is_masked(acc) and acc.endswith(data["account_number"][-4:]), f"List shows {acc!r}"
        assert bp.column_values("Registration")[0] in REGISTRATION_LABELS
    with report.step("Details show the entered data, account masked"):
        bp.open_details(code)
        assert bp.detail_value("Name") == data["name"]
        assert bp.detail_value("IFSC") == data["ifsc"]
        assert bp.detail_value("Email") == data["email"]
        assert bp.detail_value("Mobile") == data["mobile"]
        assert is_masked(bp.detail_value("Account"))
    assert data["account_number"] not in logged_in_page.content(), "Full account number is in the page"


@pytest.mark.negative
def test_duplicate_beneficiary_code_refused(logged_in_page, report):
    """BEN-UI-061 — registering with a code that already exists is refused, and the
    form issues a fresh code. The request's code is swapped for an existing one."""
    bp = BeneficiaryPage(logged_in_page).open()
    if not bp.rows().count():
        pytest.skip("No existing beneficiary code to duplicate")
    existing = bp.column_values("Code")[0]
    total = bp.showing_count()
    bp.open_add_form()
    original = bp.code_value()
    report.data(existing_code=existing, issued_code=original)
    sent = bp.rewrite_create_code(existing)
    bp.fill_form(new_beneficiary())
    with logged_in_page.expect_response(lambda r: r.url.endswith("/api/v1/beneficiaries")
                                        and r.request.method == "POST", timeout=60_000) as resp:
        bp.register()
    body = resp.value.text()
    report.actual(f"HTTP {resp.value.status}: {body[:300]}")
    check(sent and sent[0]["beneCode"] == existing, "Request carried the existing code", existing, sent)
    check(resp.value.status in (400, 409, 422), f"Register with the existing code {existing}",
          "refused (HTTP 409/422)", f"HTTP {resp.value.status}", hint="a beneficiary was created with a duplicate code")
    check("DUPLICATE_REFERENCE" in body, f"API answer to the duplicate code {existing}",
          "data.code = DUPLICATE_REFERENCE", body[:300],
          hint="the form shows 'code already in use' and issues a fresh code ONLY for DUPLICATE_REFERENCE; "
               "with this answer the user sees a misleading message and cannot recover")
    shown = bp.form_error(timeout=10_000)
    check(shown.startswith(MSG["duplicate_code"]), "Message shown in the form", MSG["duplicate_code"], shown)
    logged_in_page.wait_for_function(
        "c => document.getElementById('bene-code').value && document.getElementById('bene-code').value !== c",
        arg=original, timeout=15_000)
    assert bp.code_value() not in (original, existing), "A fresh code was not issued after the duplicate"
    bp.cancel()
    logged_in_page.reload()
    assert bp.showing_count() == total, "A beneficiary was created with a duplicate code"


# ================================================================== security
@pytest.mark.security
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_xss_in_name_not_executed(logged_in_page, payload):
    """BEN-UI-070 — script payloads typed into the name never execute in the form."""
    fired = _dialog_watch(logged_in_page)
    bp = _open_form(logged_in_page)
    sent = bp.capture_create(mock=True)
    data = new_beneficiary()
    data["name"] = payload
    bp.fill_form(data)
    bp.register()
    logged_in_page.wait_for_timeout(800)
    assert fired["count"] == 0, "XSS payload executed a dialog"
    if sent:  # the client passes it on — the API tests check the server refuses it
        assert sent[0]["beneName"] == payload


@pytest.mark.security
def test_no_full_account_in_web_storage_after_entry(logged_in_page):
    """BEN-UI-071 — the typed account number is not kept in local/session storage."""
    bp = _open_form(logged_in_page)
    bp.capture_create(mock=True)
    data = new_beneficiary()
    bp.fill_form(data)
    bp.register()
    bp.dialog.wait_for(state="hidden")
    dump = logged_in_page.evaluate("() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
    assert data["account_number"] not in dump, "Full account number stored in web storage"
