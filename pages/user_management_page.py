"""User Management page object — Roles + Users (Workflow 6)."""
from __future__ import annotations

from pages.base_page import BasePage


class UserManagementPage(BasePage):
    PATH = "/users"

    def open(self) -> "UserManagementPage":
        self.goto(self.PATH)
        return self

    def open_tab(self, name: str) -> None:
        self.page.get_by_role("tab", name=name, exact=False).first.click()

    # -- roles --------------------------------------------------------------
    def new_role(self) -> None:
        for name in ("New role", "+ New role", "Add role", "Create role"):
            b = self.button(name)
            if b.count():
                b.first.click()
                return

    def fill_role(self, name: str, description: str = "") -> None:
        self.field("Role name").fill(name)
        if description:
            self.field("Description").fill(description)

    def set_module_access(self, module: str, level: str) -> None:
        """level in {None, View, Manage, Full} for a module row in the matrix."""
        row = self.page.get_by_role("row", name=module, exact=False)
        target = row if row.count() else self.page
        target.get_by_text(level, exact=True).first.click()

    def save_role(self) -> None:
        for name in ("Save", "Publish", "Create"):
            b = self.button(name)
            if b.count():
                b.first.click()
                return

    def role_row(self, name: str):
        return self.page.get_by_role("row", name=name, exact=False)

    # -- users --------------------------------------------------------------
    def add_user(self) -> None:
        for name in ("Add User", "+ Add User", "Invite", "Invite User"):
            b = self.button(name)
            if b.count():
                b.first.click()
                return

    def fill_user(self, email: str, full_name: str, contact: str) -> None:
        self.field("Email").fill(email)
        self.field("Full Name").fill(full_name)
        self.field("Contact Number").fill(contact)

    def select_role(self, role: str) -> None:
        self.field("Role").click()
        self.page.get_by_text(role, exact=False).first.click()

    def assigned_vid_visible(self) -> bool:
        loc = self.page.get_by_text("Assigned Virtual ID", exact=False)
        return bool(loc.count() and loc.first.is_visible())

    def set_hierarchy(self, level: str) -> None:
        """level in {Maker, Approver Level 1, Approver Level 2}."""
        self.page.get_by_text(level, exact=False).first.click()

    def send_invitation(self) -> None:
        self.button("Send Invitation").first.click()

    def user_row(self, email: str):
        return self.page.get_by_role("row", name=email, exact=False)
