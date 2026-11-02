"""Base page object with shared navigation and helpers.

SELECTOR NOTE
-------------
Locators here and in every page object are best-effort, derived from the
SprintEXcrow Focused Workflow Guide (field labels, button text) plus standard
patterns. They are centralised on purpose: when a locator does not match the
live DOM, fix it HERE in the page object and every test keeps working.
Prefer role/label/text locators; fall back to data-test attributes if the app
exposes them (update SEL_* constants accordingly).
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from config.settings import settings


class BasePage:
    def __init__(self, page: Page):
        self.page = page
        self.page.set_default_timeout(settings.default_timeout_ms)

    # -- generic helpers ----------------------------------------------------
    def goto(self, path: str = "/") -> None:
        self.page.goto(settings.url(path))

    def toast_text(self) -> str:
        """Return the first visible toast/snackbar/alert text, if any."""
        for sel in ['[role="alert"]', ".toast", ".snackbar", ".Toastify__toast",
                    ".ant-message", ".MuiAlert-message"]:
            loc = self.page.locator(sel)
            if loc.count() and loc.first.is_visible():
                return (loc.first.inner_text() or "").strip()
        return ""

    def field(self, label: str):
        """A form input located by its visible label / placeholder / name."""
        by_label = self.page.get_by_label(label, exact=False)
        if by_label.count():
            return by_label.first
        by_ph = self.page.get_by_placeholder(label, exact=False)
        if by_ph.count():
            return by_ph.first
        return self.page.locator(
            f'input[name*="{label.lower().replace(" ", "")}"], '
            f'textarea[name*="{label.lower().replace(" ", "")}"]'
        ).first

    def button(self, name: str):
        return self.page.get_by_role("button", name=name, exact=False)

    def expect_url_contains(self, fragment: str) -> None:
        expect(self.page).to_have_url(lambda u: fragment in u)
