"""Remember a password changed by the forgot-password flow between runs.

The file lives under .auth/ (git-ignored). Once a reset has succeeded,
every later login uses the saved password and the reset test is skipped.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def saved_password(path: str, email: str) -> str | None:
    return (_load(path).get(email.lower()) or {}).get("password")


def reset_done(path: str, email: str) -> bool:
    return bool((_load(path).get(email.lower()) or {}).get("reset_done"))


def save_password(path: str, email: str, password: str, reset_done: bool = True) -> None:
    data = _load(path)
    data[email.lower()] = {
        "password": password,
        "reset_done": reset_done,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
