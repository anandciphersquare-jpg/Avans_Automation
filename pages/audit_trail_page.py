"""Audit Trail page object."""
from __future__ import annotations

from pages.base_page import BasePage


class AuditTrailPage(BasePage):
    PATH = "/audit-trail"

    def open(self) -> "AuditTrailPage":
        self.goto(self.PATH)
        return self

    def rows(self):
        return self.page.locator("table tbody tr, [role='row']")

    def search(self, term: str) -> None:
        self.field("Search").fill(term)
        self.page.keyboard.press("Enter")

    def table_text(self) -> str:
        return self.page.inner_text("table") if self.page.locator("table").count() \
            else self.page.inner_text("body")

    def download_report(self):
        with self.page.expect_download() as dl:
            self.button("Download").first.click()
        return dl.value
