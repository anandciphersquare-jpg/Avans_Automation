"""Change password + Sign out page object (live build, 2026-10-21).

Form ids: #currentPassword, #newPassword, #confirmPassword; inline messages in
#<id>-error; the server's refusal in p[role=alert]. Sign out is a BUTTON in the
side menu (not a link).
"""
from __future__ import annotations

from pages.base_page import BasePage

MSG = {
    "current_required": "Enter your current password",
    "min_8": "Use at least 8 characters",
    "max_12": "Use at most 12 characters",
    "complexity": "Include a lowercase letter, an uppercase letter, a digit and a symbol",
    "confirm_required": "Type the new password again",
    "mismatch": "The two passwords do not match",
    "same_as_current": "Choose a password you have not used here before",
}


class ChangePasswordPage(BasePage):
    PATH = "/change-password"

    def open(self) -> "ChangePasswordPage":
        self.page.get_by_role("link", name="Change password", exact=False).first.click()
        self.page.get_by_role("heading", name="Change your password").wait_for()
        return self

    def fill(self, current: str, new: str, confirm: str | None = None) -> None:
        self.page.locator("#currentPassword").fill(current)
        self.page.locator("#newPassword").fill(new)
        self.page.locator("#confirmPassword").fill(confirm if confirm is not None else new)

    def submit(self) -> None:
        self.page.get_by_role("button", name="Change password and sign in again").click()

    def field_error(self, field: str) -> str:
        loc = self.page.locator(f"#{field}-error")
        return loc.inner_text().strip() if loc.count() else ""

    def server_error(self, timeout: int = 8_000) -> str:
        loc = self.page.locator("form p[role='alert']")
        try:
            loc.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001
            return ""
        return loc.inner_text().strip()

    def back_to_console(self) -> None:
        self.page.get_by_role("button", name="Back to the console").click()

    def sign_out(self) -> None:
        self.page.get_by_role("button", name="Sign out").first.click()
