"""Scrub secrets from anything the server hands back to the model."""
from __future__ import annotations

import json
import re
from typing import Any

_SECRET_KEY = re.compile(r"pass|otp|secret|token|authori[sz]ation|cvv|cookie|^pin$", re.I)
_MASK = "***redacted***"


def redact(obj: Any) -> Any:
    """Recursively mask values whose key looks sensitive."""
    if isinstance(obj, dict):
        return {k: (_MASK if _SECRET_KEY.search(str(k)) and v not in (None, "") else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def redact_headers(headers: dict) -> dict:
    return {k: (_MASK if _SECRET_KEY.search(k) else v) for k, v in (headers or {}).items()}


def body_preview(response, limit: int = 6000) -> Any:
    """Parsed + redacted JSON body if possible, else truncated text."""
    if not response.content:
        return None
    try:
        data = redact(response.json())
        text = json.dumps(data, ensure_ascii=False)
        return data if len(text) <= limit else text[:limit] + " …[truncated]"
    except ValueError:
        text = response.text or ""
        return text[:limit] + (" …[truncated]" if len(text) > limit else "")
