"""
Failure messages a developer and a QA can both act on.

Every failed check reads the same way, in the console and in the report:

    [AUTH-API-005] Login with an unknown email is refused
      Request    : POST /api/v1/auth/login
      Expected   : HTTP 401 | code UNAUTHORIZED | message "Invalid email or password."
      Actual     : HTTP 200 | code - | message "Signed in successfully"
      Field errors: email: Enter a valid email address
      Request-ID : 01M5EXE4AG5A1CEPQNV16RJGYR  (search the server log for this id)
      Hint       : the API accepted credentials it should have refused

The test case id is filled in automatically (conftest sets it per test).
"""
from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlsplit

CURRENT_ID = ""  # set by the autouse fixture in conftest.py


# ---------------------------------------------------------------- formatting
def _header(title: str) -> str:
    return f"[{CURRENT_ID}] {title}" if CURRENT_ID else title


def _q(text: Any) -> str:
    return f'"{text}"' if text not in (None, "") else "-"


def _body(r) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def api_summary(r) -> dict:
    """status / code / message / field errors / request id of an API response."""
    body = _body(r)
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    errors = body.get("errors") or []
    return {
        "request": f"{r.request.method} {urlsplit(r.request.url).path}",
        "status": r.status_code,
        "code": data.get("code") or "-",
        "message": body.get("message") or ("" if body else (r.text or "")[:120].strip()),
        "fields": "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors if isinstance(e, dict)),
        "request_id": body.get("requestId") or r.headers.get("X-Request-ID", ""),
        "non_json": not body,
    }


def describe(r) -> str:
    s = api_summary(r)
    parts = [f"HTTP {s['status']}", f"code {s['code']}", f"message {_q(s['message'])}"]
    if s["non_json"] and s["status"] == 403:
        parts.append("(HTML page — blocked by the web firewall, not by the application)")
    return " | ".join(parts)


def report_lines(title: str, expected: str, actual: str, *, request: str = "",
                 fields: str = "", request_id: str = "", hint: str = "") -> str:
    lines = [_header(title)]
    if request:
        lines.append(f"  Request    : {request}")
    lines.append(f"  Expected   : {expected}")
    lines.append(f"  Actual     : {actual}")
    if fields:
        lines.append(f"  Field errors: {fields}")
    if request_id:
        lines.append(f"  Request-ID : {request_id}  (search the server log for this id)")
    if hint:
        lines.append(f"  Hint       : {hint}")
    return "\n".join(lines)


# --------------------------------------------------------------------- checks
def check(condition: Any, title: str, expected: str, actual: Any, hint: str = "") -> None:
    """Generic (UI or data) check with the standard message."""
    if not condition:
        raise AssertionError(report_lines(title, expected, str(actual), hint=hint))


def expect_api(r, title: str, *, status: int | Iterable[int], code: str | None = None,
               message: str | None = None, message_contains: str | None = None,
               fields: Iterable[str] | None = None, hint: str = "") -> dict:
    """Check an API response; return its JSON body on success."""
    allowed = (status,) if isinstance(status, int) else tuple(status)
    s = api_summary(r)
    problems = []
    if s["status"] not in allowed:
        problems.append("status")
    if code and s["code"] != code:
        problems.append("code")
    if message is not None and s["message"] != message:
        problems.append("message")
    if message_contains and message_contains.lower() not in (s["message"] or "").lower():
        problems.append("message")
    missing = []
    if fields:
        reported = {f.split(":")[0].strip() for f in s["fields"].split(";") if f.strip()}
        missing = [f for f in fields if f not in reported]
        if missing:
            problems.append("fields")
    if problems:
        want = [f"HTTP {' or '.join(map(str, allowed))}"]
        if code:
            want.append(f"code {code}")
        if message is not None:
            want.append(f"message {_q(message)}")
        if message_contains:
            want.append(f"message containing {_q(message_contains)}")
        if fields:
            want.append(f"field errors for {', '.join(fields)}")
        auto_hint = hint
        if not auto_hint:
            if s["status"] in (200, 201) and not any(st in (200, 201) for st in allowed):
                auto_hint = "the API ACCEPTED a request it should refuse — a server-side rule is missing"
            elif s["status"] >= 500:
                auto_hint = "server error — the input reached code that does not handle it; check the server log"
            elif missing:
                auto_hint = f"the refusal does not name {', '.join(missing)} — the client cannot tell the user what to fix"
        raise AssertionError(report_lines(
            title, " | ".join(want), describe(r), request=s["request"], fields=s["fields"],
            request_id=s["request_id"], hint=auto_hint))
    return _body(r)
