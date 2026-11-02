"""Dashboard + sidebar navigation page object."""
from __future__ import annotations

from pages.base_page import BasePage

# Sidebar items and whether they are LIVE in the current build (from the
# sidebar screenshot). Non-live items must not navigate / must stay locked.
MENU = {
    "Dashboard": True,
    "Beneficiary List": True,
    "Create Transfer": False,
    "Approvals": False,
    "Master Escrow": False,
    "Escrow Transfer": False,
    "Escrow Deposit": False,
    "Virtual ID": False,
    "Transfers": True,
    "Deposits": False,
    "QR Settlements": False,
    "Audit Trail": True,
    "User Management": True,
    "Change password": True,
    "Sign out": True,
}
LIVE_MENU = [k for k, v in MENU.items() if v]
HIDDEN_MENU = [k for k, v in MENU.items() if not v]

# best-effort route map for direct-URL access-control tests
ROUTES = {
    "Dashboard": "/dashboard",
    "Beneficiary List": "/beneficiaries",
    "Transfers": "/transfers",
    "Audit Trail": "/audit-trail",
    "User Management": "/users",
    "Create Transfer": "/create-transfer",
    "Approvals": "/approvals",
    "Virtual ID": "/virtual-id",
    "Master Escrow": "/master-escrow",
    "Deposits": "/deposits",
    "QR Settlements": "/qr-settlements",
}


class DashboardPage(BasePage):
    def menu_item(self, name: str):
        return self.page.get_by_role("link", name=name, exact=False)

    def is_menu_enabled(self, name: str) -> bool:
        loc = self.menu_item(name)
        try:  # the side menu renders after the dashboard data loads (skeleton first)
            loc.first.wait_for(state="visible", timeout=15_000)
        except Exception:  # noqa: BLE001
            return False
        el = loc.first
        if not el.is_visible():
            return False
        aria = (el.get_attribute("aria-disabled") or "").lower()
        cls = (el.get_attribute("class") or "").lower()
        return aria != "true" and "disabled" not in cls

    def open_menu(self, name: str) -> None:
        self.menu_item(name).first.click()

    def role_label(self) -> str:
        loc = self.page.get_by_text("MERCHANT_OWNER", exact=False)
        return loc.first.inner_text().strip() if loc.count() else ""

    def balance_cards(self):
        return self.page.locator('.balance, .summary-card, [data-test*="balance"]')
