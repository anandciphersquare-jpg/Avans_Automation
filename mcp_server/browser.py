"""
One long-lived Playwright browser shared by all UI / UX tools.

The page objects in pages/ use Playwright's *sync* API, which cannot run on the
MCP server's asyncio loop. So every browser operation is funnelled through a
single dedicated worker thread (`BrowserSession.call`) - Playwright objects stay
on the thread that created them, and the page objects are reused unchanged.
"""
from __future__ import annotations

import asyncio
import functools
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

from config.settings import settings
from pages.base_page import BasePage

DESKTOP = {"width": 1440, "height": 900}


class BrowserSession:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")
        self._pw = None
        self._browser = None
        self.context = None
        self._page: Page | None = None
        self.role = "anonymous"
        self.console: deque[dict] = deque(maxlen=500)
        self.network: deque[dict] = deque(maxlen=500)
        self.dialogs: deque[str] = deque(maxlen=100)

    async def call(self, fn, *args, **kwargs):
        """Run fn(*args) on the Playwright thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    # ---- everything below runs on the Playwright thread only ----------------
    def start(self, headless: bool | None = None, storage_state: str | None = None,
              geolocation: bool = True) -> None:
        self.stop()
        self._pw = sync_playwright().start()
        launcher = getattr(self._pw, settings.browser, self._pw.chromium)
        self._browser = launcher.launch(headless=settings.headless if headless is None else headless,
                                        slow_mo=settings.slow_mo)
        kwargs: dict = {"locale": "en-IN", "viewport": DESKTOP, "bypass_csp": True}
        if geolocation:  # sign-in is blocked without Allow Location
            kwargs["permissions"] = ["geolocation"]
            kwargs["geolocation"] = {"latitude": settings.geo_latitude, "longitude": settings.geo_longitude}
        if storage_state and Path(storage_state).exists():
            kwargs["storage_state"] = storage_state
        self.context = self._browser.new_context(**kwargs)
        self.context.set_default_timeout(settings.default_timeout_ms)
        self._page = self.context.new_page()
        self._wire(self._page)

    def _wire(self, page: Page) -> None:
        page.on("console", lambda m: self.console.append(
            {"type": m.type, "text": m.text[:500], "url": page.url}))
        page.on("pageerror", lambda e: self.console.append(
            {"type": "pageerror", "text": str(e)[:500], "url": page.url}))
        page.on("requestfailed", lambda r: self.network.append(
            {"url": r.url[:300], "method": r.method, "error": r.failure}))
        page.on("response", lambda r: r.status >= 400 and self.network.append(
            {"url": r.url[:300], "method": r.request.method, "status": r.status}))
        page.on("dialog", self._on_dialog)

    def _on_dialog(self, dialog) -> None:
        self.dialogs.append(f"{dialog.type}: {dialog.message[:200]}")
        dialog.dismiss()

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            self.start()
        return self._page

    @property
    def running(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    def stop(self) -> None:
        for closer in (self.context, self._browser):
            try:
                closer and closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self.context = self._page = None
        self.role = "anonymous"


def locate(page: Page, target: str) -> Locator:
    """Resolve a target string to a locator.

    Prefixes: label=, placeholder=, button=, link=, text=, field= (smart
    label/placeholder/name lookup from BasePage), testid=. Anything else is
    passed to page.locator() (CSS, xpath=, role=..., etc.).
    """
    t = target.strip()
    prefix, sep, value = t.partition("=")
    if sep:
        if prefix == "label":
            return page.get_by_label(value, exact=False).first
        if prefix == "placeholder":
            return page.get_by_placeholder(value, exact=False).first
        if prefix == "button":
            return page.get_by_role("button", name=value, exact=False).first
        if prefix == "link":
            return page.get_by_role("link", name=value, exact=False).first
        if prefix == "text":
            return page.get_by_text(value, exact=False).first
        if prefix == "testid":
            return page.get_by_test_id(value).first
        if prefix == "field":
            return BasePage(page).field(value)
    return page.locator(t).first


session = BrowserSession()
