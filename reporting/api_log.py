"""
API request/response logging.

``requests_hook`` is a requests response hook. ApiClient registers it on its
session, so every API call made during a test lands in that test's report
(method, URL, status, timing, redacted headers and bodies). Outside a test it
does nothing.

Other code can log a call explicitly:

    from reporting import current
    rec = current()
    if rec: rec.log_api(response)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp_server.redact import redact, redact_headers


def _parse_body(raw: Any, limit: int) -> Any:
    if raw in (None, b"", ""):
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(raw)} bytes binary>"
    text = str(raw)
    try:
        data = redact(json.loads(text))
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except ValueError:
        pass
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


def entry_from_requests(response, limit: int = 4000) -> dict:
    """Build a log entry from a ``requests.Response``."""
    req = response.request
    return {
        "source": "api",
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "method": req.method,
        "url": req.url,
        "status": response.status_code,
        "ok": response.ok,
        "duration_ms": int(response.elapsed.total_seconds() * 1000),
        "request_headers": redact_headers(dict(req.headers)),
        "request_body": _parse_body(req.body, limit),
        "response_headers": redact_headers(dict(response.headers)),
        "response_body": _parse_body(response.content, limit),
    }


def entry_from_playwright(response, limit: int = 4000) -> dict:
    """Build a log entry from a Playwright ``Response`` (XHR / fetch only).

    Only properties are read here - no blocking calls inside event handlers -
    so response bodies are not captured for browser traffic.
    """
    req = response.request
    try:
        body = req.post_data
    except Exception:  # noqa: BLE001 - binary post data raises on decode
        body = "<binary>"
    return {
        "source": "browser",
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "method": req.method,
        "url": response.url,
        "status": response.status,
        "ok": response.ok,
        "duration_ms": None,
        "request_headers": redact_headers(req.headers),
        "request_body": _parse_body(body, limit),
        "response_headers": redact_headers(response.headers),
        "response_body": None,
    }


def requests_hook(response, *args, **kwargs):
    """requests ``response`` hook - records the call on the running test."""
    from reporting.recorder import current  # late import: avoids a cycle
    rec = current()
    if rec is not None:
        try:
            rec.log_api(response)
        except Exception:  # noqa: BLE001 - logging must never break a test
            pass
    return response
