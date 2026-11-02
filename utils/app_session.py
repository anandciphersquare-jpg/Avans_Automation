"""
Save and reuse the signed-in SprintEXcrow session across browser contexts.

The app keeps its login in sessionStorage (key ``sprintexcrow.session``), which
belongs to one tab: Playwright's ``storage_state`` (cookies + localStorage)
does not include it, and every new tab opens on /login. So next to the usual
storage-state file we save sessionStorage, and inject it into new contexts
with an init script before the app's own code runs.
"""
from __future__ import annotations

import json
from pathlib import Path

from config.settings import settings


def _session_file(state_path: str | Path) -> Path:
    p = Path(state_path)
    return p.with_name(p.stem + "_session.json")


def save(page, state_path: str | Path) -> None:
    """Save cookies/localStorage (storage_state) and sessionStorage of `page`."""
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    page.context.storage_state(path=str(state_path))
    data = {"origin": page.evaluate("location.origin"),
            "session_storage": page.evaluate("Object.fromEntries(Object.entries(sessionStorage))")}
    _session_file(state_path).write_text(json.dumps(data), encoding="utf-8")


def has_session(state_path: str | Path) -> bool:
    f = _session_file(state_path)
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")).get("session_storage"))
    except (OSError, ValueError):
        return False


def restore(context, state_path: str | Path) -> None:
    """Make every page of `context` start with the saved sessionStorage."""
    f = _session_file(state_path)
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    items = data.get("session_storage") or {}
    if not items:
        return
    context.add_init_script(
        "(([origin, items]) => {"
        "  if (location.origin !== origin) return;"
        "  for (const [k, v] of Object.entries(items)) {"
        "    if (sessionStorage.getItem(k) === null) sessionStorage.setItem(k, v);"
        "  }"
        f"}})({json.dumps([data.get('origin') or settings.base_url.rstrip('/'), items])});")


def is_signed_in(page) -> bool:
    """Open the dashboard; True when the app does not send us back to /login."""
    page.goto(settings.base_url.rstrip("/") + "/dashboard", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    return "/login" not in page.url
