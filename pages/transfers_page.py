"""Transfers (approver side) page object — Workflows 1 & 2 approver steps."""
from __future__ import annotations

from pages.base_page import BasePage


class TransfersPage(BasePage):
    PATH = "/transfers"

    def open(self) -> "TransfersPage":
        self.goto(self.PATH)
        return self

    def rows(self):
        return self.page.locator("table tbody tr, [role='row']")

    def search(self, term: str) -> None:
        self.field("Search").fill(term)
        self.page.keyboard.press("Enter")

    def status_badges(self, text: str = "Pending for Authorization"):
        return self.page.get_by_text(text, exact=False)

    def open_journey_for_pending(self) -> bool:
        """Open the Transfer Journey of the first pending transfer. Returns False
        if there are none to action."""
        badges = self.status_badges()
        if not badges.count():
            return False
        badges.first.click()
        return True

    def journey_text(self) -> str:
        drawer = self.page.locator('.drawer, [role="dialog"], .journey')
        return drawer.first.inner_text() if drawer.count() else self.page.inner_text("body")

    def approve(self) -> None:
        self.button("Approve").first.click()
        self._confirm()

    def deny(self) -> None:
        self.button("Deny").first.click()
        self._confirm()

    def _confirm(self) -> None:
        for name in ("Confirm", "Yes", "OK", "Proceed"):
            b = self.button(name)
            if b.count() and b.first.is_visible():
                b.first.click()
                return

    def can_approve(self) -> bool:
        b = self.button("Approve")
        return bool(b.count() and b.first.is_visible() and b.first.is_enabled())
