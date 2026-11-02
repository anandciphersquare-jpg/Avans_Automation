"""
QA view of a test result: what was checked, what happened, why, and what to do.

The raw exception ("Locator.click: Timeout 30000ms exceeded ... element is not
enabled") is written for developers. ``qa_analysis()`` turns it into the
fields a tester puts in a defect or a run summary:

    verdict    Application defect | Needs review | Test script issue |
               Environment / configuration | Not executed
    summary    one plain-English sentence
    failed_at  the step where it stopped
    expected   what should have happened
    actual     what actually happened
    cause      probable cause
    action     the next thing to do

The raw error and stack trace stay in the record for developers.
"""
from __future__ import annotations

import re

from reporting.models import BLOCKED, FAIL, PASS, SKIPPED

APP_DEFECT = "Application defect"
NEEDS_REVIEW = "Needs review"
SCRIPT = "Test script issue"
ENVIRONMENT = "Environment / configuration"
NOT_EXECUTED = "Not executed"
PENDING = "Pending development"

# Playwright API name -> what the tester would say
_VERBS = {
    "click": "click", "dblclick": "double-click", "fill": "fill in", "type": "type into",
    "press": "press a key in", "check": "tick", "uncheck": "untick", "hover": "hover over",
    "select_option": "pick an option in", "set_input_files": "upload a file to",
    "wait_for": "find", "inner_text": "read", "text_content": "read", "input_value": "read",
    "is_visible": "find", "is_enabled": "check", "focus": "focus",
}

_SETTING = re.compile(r"\b([A-Z][A-Z0-9_]{2,}(?:\s*/\s*[A-Z][A-Z0-9_]{2,})*)\s+(?:is|are)\s+not set", re.I)
_PW_TIMEOUT = re.compile(r"(Locator|Page|Frame|ElementHandle)\.(\w+): Timeout (\d+)ms exceeded")
_EXPECT = re.compile(r"Locator expected (?:to |not to )?(.+?)(?:\n|$)")
_EXPECTED_VAL = re.compile(r"Expected (?:value|string|pattern|substring)?\s*:\s*(.+)")
_ACTUAL_VAL = re.compile(r"(?:Actual|Received) (?:value|string)?\s*:\s*(.+)")
_PLAIN_ASSERT = re.compile(r"^assert (.+?) == (.+)$", re.M)
_HTTP_STATUS = re.compile(r"\b(?:status(?: code)?|HTTP)\D{0,5}([45]\d\d)\b", re.I)


# messages raised by pages/login_page.py (LoginError) and utils/gmail_web.py (GmailWebError)
_LOGIN_RULES = [
    {"match": r"2-step verification was not entered|Gmail sign-in was not completed",
     "verdict": ENVIRONMENT,
     "actual": "The run waited for Google's 2-step verification in the Gmail tab, but it was not completed.",
     "cause": "Gmail needs the 2-step verification code once; nobody entered it in time.",
     "action": "Run with --headed, watch for the Gmail tab and enter the 2-step code there. "
               "The Gmail session is then saved and reused."},
    {"match": r"Google blocked the Gmail sign-in",
     "verdict": ENVIRONMENT,
     "actual": "Google refused to sign in inside the automation browser.",
     "cause": "Google's protection against automated browsers.",
     "action": "Run once: python -m utils.gmail_web login (opens your Chrome), sign in, then re-run the tests."},
    {"match": r"Gmail rejected the password",
     "verdict": ENVIRONMENT,
     "actual": "Gmail said \"Wrong password\" for the address in MAIL_USER.",
     "cause": "MAIL_PASSWORD in .env is wrong or out of date.",
     "action": "Correct MAIL_PASSWORD in .env (or leave it blank and type it in the browser)."},
    {"match": r"No new .* mail reached",
     "verdict": NEEDS_REVIEW,
     "actual": "Sign in was clicked, but no new sign-in code mail appeared in Gmail in time.",
     "cause": "The app did not send the OTP mail, it was delayed, or the subject filter (OTP_MAIL_SUBJECT) does not match.",
     "action": "Check the inbox by hand. If no mail arrived after Sign in, raise a defect for OTP delivery."},
    {"match": r"has no 6-digit code in it",
     "verdict": NEEDS_REVIEW,
     "actual": "The newest sign-in mail did not contain a 6-digit code.",
     "cause": "The mail format changed, or a different mail matched the subject.",
     "action": "Open the mail by hand and confirm its content; raise a defect if the code is missing."},
    {"match": r"OTP screen did not appear",
     "verdict": NEEDS_REVIEW,
     "actual": "After Sign in the app did not move to the OTP step.",
     "cause": "Wrong email / password, location not allowed, or the app rejected the sign-in.",
     "action": "Check the screenshot for the message shown; verify ADMIN_EMAIL / ADMIN_PASSWORD by hand."},
    {"match": r"OTP from the latest mail was entered",
     "verdict": APP_DEFECT,
     "actual": "A fresh OTP from Gmail was entered, but the app did not accept it.",
     "cause": "The app rejected a valid, just-received code (or it had already expired).",
     "action": "Repeat by hand with a fresh code. If a fresh code is also rejected, raise a defect."},
    {"match": r"Manual OTP was not entered",
     "verdict": ENVIRONMENT,
     "actual": "The run waited for the OTP to be typed by hand, but it was not entered.",
     "cause": "OTP_STRATEGY=manual needs someone at the browser.",
     "action": "Use OTP_STRATEGY=gmail_web to read the code automatically, or type it within the wait time."},
]


# --------------------------------------------------------------------------- #
# element description from a Playwright call log / locator string
# --------------------------------------------------------------------------- #
def describe_locator(text: str) -> str:
    """'get_by_role("button", name="Sign in")' -> 'the "Sign in" button'."""
    m = re.search(r'get_by_role\("(\w+)"(?:,\s*name="([^"]+)")?', text)
    if m:
        role, name = m.group(1), m.group(2)
        role = {"textbox": "field", "combobox": "dropdown", "link": "link"}.get(role, role)
        return f'the "{name}" {role}' if name else f"a {role}"
    for fn, noun in (("get_by_label", "field"), ("get_by_placeholder", "field"),
                     ("get_by_test_id", "element"), ("get_by_title", "element")):
        m = re.search(fn + r'\("([^"]+)"', text)
        if m:
            return f'the "{m.group(1)}" {noun}'
    m = re.search(r'get_by_text\("([^"]+)"', text)
    if m:
        return f'the text "{m.group(1)}"'
    m = re.search(r'locator\("(.+?)"\)(?:\.|$|\s)', text)
    if m:
        css = m.group(1).replace('\\"', '"')
        if 'type="submit"' in css:
            return "the form's submit button"
        aria = re.search(r'aria-label[\^*$]?="([^"]+)"', css)
        if aria:
            return f'the "{aria.group(1)}" input'
        return f"the element `{css[:70]}`"
    return "the element"


def _target(text: str) -> str:
    """The element Playwright was waiting for (its call log), else the whole text."""
    m = re.search(r"waiting for (?:locator\()?(.+)", text)
    if not m:
        return text
    line = m.group(0)
    if line.startswith("waiting for locator(") or "get_by_" in line:
        return line
    # page.click("#id") logs: waiting for locator("#id")
    return f'locator("{m.group(1).strip()}")'


def _seconds(ms: str) -> str:
    s = int(ms) / 1000
    return f"{s:g} s"


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
def _failed_step(record: dict) -> str:
    for i, s in enumerate(record.get("steps") or [], 1):
        if s.get("status") == "failed":
            return f"Step {i}: {s.get('title', '')}"
    return ""


def _first_message(record: dict) -> str:
    reason = record.get("failure_reason") or ""
    reason = re.sub(r"^(Setup|Teardown) failed - ", "", reason)
    reason = re.sub(r"^[\w.]*(Error|Exception): ", "", reason)
    return reason.strip()


def _analyse_error(record: dict) -> dict:
    """Fields for a FAIL / BLOCKED record (before phase-specific wording)."""
    reason = record.get("failure_reason") or ""
    trace = record.get("stack_trace") or ""
    text = f"{reason}\n{trace}"
    etype = record.get("error_type") or ""
    msg = _first_message(record)

    # 0. login / Gmail stages raise messages already written for the report
    for rule in _LOGIN_RULES:
        if re.search(rule["match"], text, re.I):
            return {"verdict": rule["verdict"], "summary": msg if etype in ("LoginError", "GmailWebError")
                    else rule.get("summary", msg), "actual": rule.get("actual", msg),
                    "cause": rule["cause"], "action": rule["action"]}
    if "has been closed" in text and ("Target page" in text or "TargetClosedError" in text):
        return {
            "verdict": ENVIRONMENT,
            "summary": "The browser window was closed while the test was still running.",
            "actual": "The page / browser disappeared in the middle of a step, so the check could not finish.",
            "cause": "The automation browser was closed by hand, or it crashed / ran out of memory.",
            "action": "Leave the automation browser open until the run ends, then run this test again.",
        }

    # 1. a required setting is missing
    m = _SETTING.search(text)
    if m:
        names = re.sub(r"\s*/\s*", " / ", m.group(1))
        what = "the OTP / mailbox login" if re.search(r"MAIL|OTP", names) else "this test"
        return {
            "verdict": ENVIRONMENT,
            "summary": f"Could not complete {what}: the setting {names} is not configured.",
            "actual": f"The run stopped before the check, because {names} has no value in .env.",
            "cause": "Missing test configuration. This is not a fault in the application.",
            "action": f"Set {names} in .env (or switch OTP_STRATEGY=manual and run with --headed "
                      "to type the OTP yourself), then run the test again.",
        }

    # 2. mailbox problems
    if re.search(r"AUTHENTICATIONFAILED|Invalid credentials|Application-specific password", text, re.I):
        return {
            "verdict": ENVIRONMENT,
            "summary": "Gmail refused the mailbox login, so the OTP / reset mail could not be read.",
            "actual": "IMAP login to the test mailbox was rejected.",
            "cause": "MAIL_APP_PASSWORD is wrong or is the normal account password. Gmail needs an App Password.",
            "action": "Create a Google App Password, put it in MAIL_APP_PASSWORD, and run again.",
        }
    if etype in ("MailboxError", "OtpError") or "No matching mail" in text:
        return {
            "verdict": NEEDS_REVIEW,
            "summary": f"The OTP / reset mail was not received in time: {msg}",
            "actual": msg,
            "cause": "The application did not send the mail, it was delayed, or the subject filter does not match.",
            "action": "Check the inbox manually. If no mail arrived, raise a defect; if it did, "
                      "fix OTP_MAIL_SUBJECT / RESET_MAIL_SUBJECT.",
        }

    # 3. application / server not reachable
    if re.search(r"net::ERR_|ConnectionError|getaddrinfo|Connection refused|Name or service not known"
                 r"|ECONNREFUSED|Max retries exceeded", text):
        host = re.search(r"https?://[^\s/'\"]+", text)
        return {
            "verdict": ENVIRONMENT,
            "summary": f"The application{' at ' + host.group(0) if host else ''} could not be reached.",
            "actual": "The browser / API client got a network error before any page or response loaded.",
            "cause": "The server is down, the URL is wrong, or VPN / network access is missing.",
            "action": "Open the URL manually. If it is down, report it to the environment owner and re-run later.",
        }

    # 4. Playwright expect() assertions
    m = _EXPECT.search(text)
    if m:
        element = describe_locator(_target(text))
        exp = _EXPECTED_VAL.search(text)
        act = _ACTUAL_VAL.search(text)
        what = m.group(1).strip().rstrip(".")
        actual = (f"{element[0].upper() + element[1:]} did not {what.replace('to ', '', 1)}"
                  + (f" (found: {act.group(1).strip()})" if act else "") + ".")
        return {
            "verdict": APP_DEFECT,
            "summary": f"Check failed: {element} was expected to {what}"
                       + (f" ({exp.group(1).strip()})" if exp else "") + ", but it did not.",
            "actual": actual,
            "cause": "The screen did not show what the requirement describes.",
            "action": "Reproduce with the steps and the screenshot. If confirmed, raise a defect with this evidence.",
        }

    # 5. Playwright timeouts
    m = _PW_TIMEOUT.search(text)
    if m:
        kind, api, ms = m.group(1), m.group(2), m.group(3)
        wait = _seconds(ms)
        element = describe_locator(_target(text))
        el_cap = element[0].upper() + element[1:]
        if api == "goto":
            return {
                "verdict": ENVIRONMENT,
                "summary": f"The page did not finish loading within {wait}.",
                "actual": f"Navigation timed out after {wait}.",
                "cause": "The server is slow or not responding.",
                "action": "Open the page manually and check the response time; re-run when the environment is stable.",
            }
        if api in ("wait_for_url", "wait_for_navigation", "expect_navigation"):
            return {
                "verdict": APP_DEFECT,
                "summary": f"The application did not move to the next screen within {wait}.",
                "actual": f"The browser stayed on the same page for {wait} after the action.",
                "cause": "The action was rejected (check the screenshot for an error), or the app is slow.",
                "action": "Check the screenshot for a validation or error message. If none is shown, raise a defect.",
            }
        if api in ("wait_for_load_state", "wait_for_timeout"):
            return {
                "verdict": ENVIRONMENT,
                "summary": f"The page kept loading for more than {wait}.",
                "actual": f"Network activity did not settle within {wait}.",
                "cause": "Slow or polling requests on the page.",
                "action": "Re-run. If it repeats, check the Network tab for the slow request.",
            }
        verb = _VERBS.get(api, api.replace("_", " "))
        if "element is not enabled" in text:
            return {
                "verdict": NEEDS_REVIEW,
                "summary": f"{el_cap} stayed disabled, so the test could not {verb} it ({wait} wait).",
                "actual": f"{el_cap} was on the screen but disabled for the whole {wait}.",
                "cause": "The app keeps this control disabled until its conditions are met (a required field, "
                         "permission such as location, or consent is missing). If the inputs were valid, "
                         "this is a defect; if the test expects it to be blocked, the script must check "
                         "'disabled' instead of clicking.",
                "action": "Look at the screenshot: confirm whether the button should be enabled with this data.",
            }
        if "element is not visible" in text or "element is outside of the viewport" in text:
            return {
                "verdict": NEEDS_REVIEW,
                "summary": f"{el_cap} exists but was hidden, so the test could not {verb} it.",
                "actual": f"{el_cap} was present in the page but not visible for {wait}.",
                "cause": "A dialog, loader or collapsed section covers it, or the flow changed.",
                "action": "Check the screenshot. If the element should be visible at this step, raise a defect.",
            }
        if "intercepts pointer events" in text:
            return {
                "verdict": NEEDS_REVIEW,
                "summary": f"Another element covered {element}, so it could not be clicked.",
                "actual": f"A popup, toast or overlay sat on top of {element} for {wait}.",
                "cause": "An overlay (toast, modal, cookie bar) was still open.",
                "action": "Check the screenshot for the overlay. Close it in the script or raise a UI defect.",
            }
        if "strict mode violation" in text:
            return {
                "verdict": SCRIPT,
                "summary": f"More than one element matched {element}; the script cannot tell which to use.",
                "actual": "The locator matched several elements.",
                "cause": "The locator is not specific enough for the current screen.",
                "action": "Make the locator unique (add a label, test id or .first).",
            }
        found = "locator resolved to" in text
        return {
            "verdict": SCRIPT if found else NEEDS_REVIEW,
            "summary": f"{el_cap} was not found on the screen within {wait}.",
            "actual": f"The test waited {wait} to {verb} {element}, but it never appeared.",
            "cause": "The screen changed (renamed label / new layout) or the previous step did not "
                     "lead to this screen.",
            "action": "Check the screenshot. If the element is there under another name, update the locator; "
                      "if the screen is wrong, raise a defect.",
        }

    if "strict mode violation" in text:
        return {
            "verdict": SCRIPT,
            "summary": "A locator matched more than one element.",
            "actual": msg,
            "cause": "The locator is not specific enough.",
            "action": "Make the locator unique.",
        }

    # 6. HTTP / API status
    m = _HTTP_STATUS.search(reason)
    if m and etype in ("HTTPError", "AssertionError", ""):
        code = int(m.group(1))
        return {
            "verdict": APP_DEFECT if code >= 500 else NEEDS_REVIEW,
            "summary": f"The API answered with HTTP {code}{' (server error)' if code >= 500 else ''}.",
            "actual": msg,
            "cause": "Server-side error." if code >= 500 else "The request was rejected (auth, validation or path).",
            "action": "Open the API calls tab for the request / response, and raise a defect with them."
                      if code >= 500 else "Check the request in the API calls tab against the API contract.",
        }

    # 7. plain assertions
    if etype == "AssertionError" or reason.startswith("AssertionError") or record.get("failure_category") == "Assertion":
        check = msg.split("\nassert")[0].strip()
        m = _PLAIN_ASSERT.search(trace)
        detail = ""
        if m and not check:
            detail = f" Expected {m.group(2).strip()}, got {m.group(1).strip()}."
        if not check or check.startswith("assert "):
            check = "the expected condition was not met"
        return {
            "verdict": APP_DEFECT,
            "summary": f"Check failed: {check}.".replace("..", "."),
            "actual": f"{check[0].upper() + check[1:]}.{detail}".replace("..", "."),
            "cause": "The application did not behave as the requirement describes.",
            "action": "Reproduce manually with the steps and screenshot; if confirmed, raise a defect "
                      f"for the {record.get('module', '')} module.",
        }

    # 8. anything else is the script itself
    return {
        "verdict": SCRIPT,
        "summary": f"The test script stopped with an unexpected error: {etype or 'Error'}.",
        "actual": msg or reason,
        "cause": "A coding problem in the test or page object, not a check on the application.",
        "action": "Hand to the automation engineer with the technical details below.",
    }


def qa_analysis(record: dict) -> dict:
    status = record.get("status")
    expected = record.get("expected") or ""
    base = {"verdict": "", "summary": "", "failed_at": _failed_step(record), "expected": expected,
            "actual": "", "cause": "", "action": ""}

    if status == PASS:
        base.update(verdict="Passed", summary="Behaved as expected; all checks passed.",
                    actual="Behaved as expected; all checks passed.")
        return base

    if status == SKIPPED and (record.get("skip_reason") or "").startswith("PENDING DEVELOPMENT: "):
        reason = record["skip_reason"].split(": ", 1)[1]
        found = _analyse_error(record)["summary"] if record.get("failure_reason") else ""
        base.update(
            verdict=PENDING,
            summary=f"Pending development: {reason}." + (f" Current gap: {found}" if found else ""),
            actual=("Ran against the unfinished build. " + found) if found else "Ran against the unfinished build.",
            cause="The feature is not complete on the developer side. This is a known gap, not a new defect.",
            action="Re-test when the developers hand this feature over; then remove @pytest.mark.pending_dev.",
        )
        return base

    if status == SKIPPED:
        why = record.get("skip_reason") or "Skipped"
        m = _SETTING.search(why)
        is_cfg = bool(m) or re.search(r"\bset [A-Z_]{3,}|login failed|not reached", why, re.I)
        inner = _analyse_error({**record, "failure_reason": why, "stack_trace": ""}) if is_cfg else {}
        if inner.get("verdict") == SCRIPT:  # the generic fallback says nothing useful for a skip
            inner = {}
        if re.search(r"not reached", why, re.I):
            inner = {"cause": "The earlier screen did not lead to the step this test checks "
                              "(login rejected, or the screen flow changed).",
                     "action": "Walk the flow manually up to this step; if it no longer appears, "
                               "raise a defect or update the test."}
        base.update(
            verdict=NOT_EXECUTED,
            summary=f"Not executed: {why}",
            actual="The test did not run, so this requirement is not verified in this run.",
            cause=inner.get("cause") or "A precondition for this test is not available in this run.",
            action=inner.get("action") or "Provide the precondition, then run the test again.",
        )
        return base

    found = _analyse_error(record)
    needs_login = any("signed in" in p.lower() for p in record.get("preconditions") or [])
    on_login = [u for u in record.get("page_urls") or [] if "/login" in u]
    if needs_login and on_login and found["verdict"] != ENVIRONMENT:
        found = {
            "verdict": ENVIRONMENT,
            "summary": "The test was on the Sign-in page instead of the module: the admin session was "
                       "not active, so the screen it checks never opened.",
            "actual": f"The browser was at {on_login[0]} when the step failed. Original problem: "
                      f"{found['summary']}",
            "cause": "The saved login session expired or was not carried into this browser window. "
                     "This is not a defect in the module.",
            "action": "Re-run: the suite signs in again when the saved session is no longer valid. "
                      "If it repeats, check the Login module result first.",
        }
    base.update(found)
    if status == BLOCKED:
        base["verdict"] = found["verdict"] if found["verdict"] == ENVIRONMENT else NEEDS_REVIEW
        base["summary"] = "Blocked: the test could not start. " + found["summary"]
        base["actual"] = "Precondition / setup failed, so the test steps were not run. " + found["actual"]
    elif status == FAIL and (record.get("failure_reason") or "").startswith("Teardown failed"):
        base["summary"] = "Clean-up after the test failed. " + found["summary"]
    return base
