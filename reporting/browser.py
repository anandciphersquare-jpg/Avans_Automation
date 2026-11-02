"""
Playwright capture for one test: console errors, page errors, network failures,
XHR/fetch API calls, tracing, screenshots and video.

The plugin calls ``watch()`` on every Page / BrowserContext the test received
as a fixture (and ``report.attach_page()`` adds pages a test creates itself).
New pages / popups opened in a watched context are followed automatically.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reporting.api_log import entry_from_playwright

if TYPE_CHECKING:  # pragma: no cover
    from reporting.recorder import TestRecorder

try:
    from playwright.sync_api import BrowserContext, Page
except ImportError:  # API-only environments
    BrowserContext = Page = None  # type: ignore[assignment,misc]

_API_RESOURCE_TYPES = {"xhr", "fetch"}


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def is_page(obj: Any) -> bool:
    return Page is not None and isinstance(obj, Page)


def is_context(obj: Any) -> bool:
    return BrowserContext is not None and isinstance(obj, BrowserContext)


class PageWatcher:
    def __init__(self, recorder: "TestRecorder"):
        self.rec = recorder
        self._pages: dict[int, tuple[Any, dict]] = {}
        self._contexts: dict[int, Any] = {}
        self._traced: dict[int, Any] = {}       # contexts whose tracing we started
        self._videos: list[tuple[str, str]] = []  # (source path, page label)

    # -- attach ---------------------------------------------------------------
    def watch(self, target: Any) -> None:
        if is_page(target):
            self._watch_page(target)
        elif is_context(target):
            self._watch_context(target)
            for p in list(target.pages):
                self._watch_page(p)

    def _watch_page(self, page) -> None:
        if id(page) in self._pages or page.is_closed():
            return
        handlers = {
            "console": self._on_console,
            "pageerror": self._on_pageerror,
            "requestfailed": self._on_requestfailed,
            "response": self._on_response,
        }
        for event, handler in handlers.items():
            page.on(event, handler)
        self._pages[id(page)] = (page, handlers)
        self._watch_context(page.context)
        if not self.rec.browser_version:
            try:
                browser = page.context.browser
                if browser is not None:
                    self.rec.browser_version = browser.version
                    self.rec.browser_name = browser.browser_type.name
            except Exception:  # noqa: BLE001
                pass

    def _watch_context(self, context) -> None:
        if id(context) in self._contexts:
            return
        self._contexts[id(context)] = context
        context.on("page", self._watch_page)
        if self.rec.cfg.trace != "off":
            try:
                context.tracing.start(title=self.rec.item.nodeid, screenshots=True,
                                      snapshots=True, sources=False)
                self._traced[id(context)] = context
            except Exception:  # noqa: BLE001 - already tracing (e.g. --tracing on)
                pass

    # -- event handlers (properties only; never block inside a handler) --------
    def _on_console(self, msg) -> None:
        if msg.type not in ("error", "warning"):
            return
        loc = msg.location or {}
        self.rec.add_console({
            "time": _now(), "type": msg.type, "text": msg.text[:2000],
            "location": f"{loc.get('url', '')}:{loc.get('lineNumber', '')}".strip(":"),
        })

    def _on_pageerror(self, error) -> None:
        self.rec.add_console({"time": _now(), "type": "pageerror", "text": str(error)[:2000],
                              "location": ""})

    def _on_requestfailed(self, request) -> None:
        self.rec.add_network({
            "time": _now(), "kind": "request failed", "method": request.method,
            "url": request.url, "status": None, "resource_type": request.resource_type,
            "error": request.failure or "",
        })

    def _on_response(self, response) -> None:
        request = response.request
        if response.status >= 400:
            self.rec.add_network({
                "time": _now(), "kind": "HTTP error", "method": request.method,
                "url": response.url, "status": response.status,
                "resource_type": request.resource_type, "error": response.status_text,
            })
        if request.resource_type in _API_RESOURCE_TYPES:
            self.rec.add_api(entry_from_playwright(response, self.rec.cfg.max_body_chars))

    # -- evidence ---------------------------------------------------------------
    def open_pages(self) -> list:
        return [p for p, _ in self._pages.values() if not p.is_closed()]

    def screenshot_all(self, label: str) -> None:
        """Screenshot every open page (popups included) and note where each one was."""
        for idx, page in enumerate(self.open_pages(), start=1):
            try:
                self.rec.page_urls.append(page.url)
            except Exception:  # noqa: BLE001
                pass
            suffix = f"{label}" if idx == 1 else f"{label}-page{idx}"
            self.rec.take_screenshot(page, suffix)

    def stop_tracing(self, keep: bool) -> None:
        for idx, context in enumerate(self._traced.values(), start=1):
            try:
                if keep:
                    path = self.rec.artifact_path("traces", f"trace{idx}", ".zip")
                    context.tracing.stop(path=str(path))
                    self.rec.attach(path, "trace", "Playwright trace")
                else:
                    context.tracing.stop()
            except Exception:  # noqa: BLE001 - context closed by the test itself
                pass
        self._traced.clear()

    def remember_videos(self) -> None:
        """Note each page's video path while the page is still alive."""
        for idx, page in enumerate(self.open_pages(), start=1):
            try:
                if page.video is not None:
                    self._videos.append((page.video.path(), f"page{idx}"))
            except Exception:  # noqa: BLE001
                pass

    def collect_videos(self, keep: bool) -> None:
        """After contexts close, move kept videos into the run folder."""
        for src, label in self._videos:
            source = Path(src)
            if not source.exists():
                continue
            if keep:
                dest = self.rec.artifact_path("videos", label, ".webm")
                try:
                    shutil.move(str(source), dest)
                    self.rec.attach(dest, "video", f"Video ({label})")
                except OSError:
                    pass
            else:
                source.unlink(missing_ok=True)
        self._videos.clear()

    def detach(self) -> None:
        for page, handlers in self._pages.values():
            for event, handler in handlers.items():
                try:
                    page.remove_listener(event, handler)
                except Exception:  # noqa: BLE001
                    pass
        for context in self._contexts.values():
            try:
                context.remove_listener("page", self._watch_page)
            except Exception:  # noqa: BLE001
                pass
        self._pages.clear()
        self._contexts.clear()
