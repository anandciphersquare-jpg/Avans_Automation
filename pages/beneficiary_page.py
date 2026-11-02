"""Beneficiary List + Add beneficiary + details panel page object (Workflow 4).

Locators were taken from the live UAT build (2026-10-21): the form inputs carry
stable ids (bene-*), the list is a table, and the form and details panel are
dialogs. Validation runs on "Register with bank" and shows ONE message at a
time (the first failing rule) in a role=alert paragraph inside the dialog.
"""
from __future__ import annotations

import json
import re

from pages.base_page import BasePage

CREATE_API = "**/api/v1/beneficiaries"          # POST = register (exact path, no suffix)
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")    # the app's own rule for an issued code

# The app's validation messages, in the order the app checks them.
MSG = {
    "name": "The beneficiary name is required.",
    "account_number": "The account number must be 9 to 18 digits.",
    "confirm_account_number": "The two account numbers do not match.",
    "ifsc": "The IFSC must be 11 characters: four letters, a zero, then six letters or digits.",
    "mobile": "The mobile number must be 10 digits.",
    "email": "A valid email address is required",
    "duplicate_code": "That beneficiary code is already in use, so a new one has been issued.",
}

# Labels shown in the Registration column / details panel.
REGISTRATION_LABELS = ["Registered", "Sent to bank", "Send failed", "Refused by bank", "Not sent"]
COLUMNS = ["Code", "Name", "Bank", "Account", "IFSC", "Registration", "Status", "Added"]


class BeneficiaryPage(BasePage):
    PATH = "/beneficiaries"

    FIELDS = {  # data key -> input id
        "code": "bene-code",
        "name": "bene-name",
        "account_number": "bene-acc",
        "confirm_account_number": "bene-acc-confirm",
        "ifsc": "bene-ifsc",
        "mobile": "bene-mobile",
        "email": "bene-email",
    }
    LABELS = {
        "code": "Beneficiary code",
        "name": "Beneficiary name",
        "account_number": "Account number",
        "confirm_account_number": "Confirm account number",
        "ifsc": "IFSC",
        "mobile": "Mobile number",
        "email": "Email address",
    }

    def open(self) -> "BeneficiaryPage":
        self.goto(self.PATH)
        self.page.get_by_role("heading", name="Beneficiary List").wait_for()
        self.wait_for_list()
        return self

    # -- list ---------------------------------------------------------------
    def wait_for_list(self) -> None:
        self.page.get_by_text(re.compile(r"^Showing \d+ beneficiaries$")).wait_for()

    def showing_count(self) -> int:
        self.wait_for_list()
        txt = self.page.get_by_text(re.compile(r"^Showing \d+ beneficiaries$")).inner_text()
        return int(re.search(r"\d+", txt).group())

    def rows(self):
        return self.page.locator("table tbody tr")

    def column_headers(self) -> list[str]:
        return [h.strip() for h in self.page.locator("table thead th").all_inner_texts()]

    def column_values(self, header: str) -> list[str]:
        idx = [h.lower() for h in self.column_headers()].index(header.lower())
        return [t.strip() for t in self.rows().locator(f"td:nth-child({idx + 1})").all_inner_texts()]

    def row_for(self, code: str):
        return self.rows().filter(has=self.page.get_by_role("button", name=code, exact=True))

    def search(self, term: str) -> None:
        box = self.page.locator("#q")
        box.fill(term)
        box.press("Enter")
        self.page.wait_for_timeout(800)  # debounced filter
        self.page.wait_for_load_state("networkidle")
        self.wait_for_list()

    def reset_filters(self) -> None:
        self.button("Reset Filters").click()
        self.page.wait_for_load_state("networkidle")
        self.wait_for_list()

    # -------------------------------------- Add form -----------------------------------------------------------
    @property
    def dialog(self):
        return self.page.get_by_role("dialog").last

    def open_add_form(self) -> "BeneficiaryPage":
        self.button("Add Beneficiary").first.click()
        self.dialog.get_by_role("heading", name="Add beneficiary").wait_for()
        self.wait_for_code()
        return self

    def input(self, key: str):
        return self.page.locator(f"#{self.FIELDS[key]}")

    def wait_for_code(self, timeout: int = 15_000) -> str:
        """The code is issued by the server when the form opens."""
        self.page.wait_for_function(
            "() => (document.getElementById('bene-code') || {}).value", timeout=timeout)
        return self.code_value()

    def code_value(self) -> str:
        return self.input("code").input_value()

    def fill_form(self, data: dict, skip: set[str] | None = None) -> None:
        skip = skip or set()
        for key in ("name", "account_number", "confirm_account_number", "ifsc", "mobile", "email"):
            if key in skip or key not in data:
                continue
            self.input(key).fill(str(data[key]))

    def register(self) -> None:
        self.dialog.get_by_role("button", name="Register with bank").click()

    def form_error(self, timeout: int = 5_000) -> str:
        """The inline validation / duplicate message ('' when none appears)."""
        loc = self.dialog.locator("p[role='alert']")
        try:
            loc.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001
            return ""
        return loc.inner_text().strip()

    def cancel(self) -> None:
        self.dialog.get_by_role("button", name="Cancel").click()

    def close_dialog(self) -> None:
        self.dialog.get_by_role("button", name="Close").click()

    def is_form_open(self) -> bool:
        return self.page.get_by_role("heading", name="Add beneficiary").is_visible()

    def paste_into(self, key: str, text: str) -> str:
        """Paste `text` via the clipboard (Ctrl+V). Returns the field value after."""
        self.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        self.page.evaluate("t => navigator.clipboard.writeText(t)", text)
        self.input(key).click()
        self.page.keyboard.press("Control+V")
        self.page.wait_for_timeout(300)
        return self.input(key).input_value()

    # ----------------------------- create-request capture --------------------------------------------
    
    def capture_create(self, mock: bool = True) -> list[dict]:
        """Record every POST to the create API. With mock=True the request never
        reaches the server (a success reply is faked), so client-side behaviour
        can be checked without creating data on the shared UAT."""
        sent: list[dict] = []

        def handler(route):
            req = route.request
            if req.method != "POST":
                return route.continue_()
            body = json.loads(req.post_data or "{}")
            sent.append(body)
            if not mock:
                return route.continue_()
            data = {"beneficiaryReference": "00000000-0000-0000-0000-qa0000000000",
                    "beneCode": body.get("beneCode", ""), "beneName": body.get("beneName", ""),
                    "beneAccNum": "*" * 10 + str(body.get("beneAccNum", ""))[-4:],
                    "beneIfscCode": body.get("beneIfscCode", ""), "bankName": "QA mock bank",
                    "status": "PENDING"}
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"success": True, "message": "mocked by QA", "data": data}))

        self.page.route(CREATE_API, handler)
        return sent

    def rewrite_create_code(self, code: str) -> list[dict]:
        """Send the real create request but with beneCode replaced (duplicate test)."""
        sent: list[dict] = []

        def handler(route):
            req = route.request
            if req.method != "POST":
                return route.continue_()
            body = json.loads(req.post_data or "{}")
            body["beneCode"] = code
            sent.append(body)
            return route.continue_(post_data=json.dumps(body))

        self.page.route(CREATE_API, handler)
        return sent

    # ---------------------------------------------- details / actions --------------------------------------------------
    def open_details(self, code: str) -> None:
        self.page.get_by_role("button", name=code, exact=True).first.click()
        self.dialog.get_by_role("heading", name="With the bank").wait_for()

    def detail_value(self, label: str) -> str:
        """Value of a <dt>label</dt><dd>value</dd> pair in the details panel.
        Labels are upper-cased by CSS, so textContent (not innerText) is matched."""
        return self.dialog.evaluate(
            """(d, label) => {
                const dt = [...d.querySelectorAll('dt')].find(e => e.textContent.trim() === label);
                const dd = dt && dt.nextElementSibling;
                return dd ? dd.textContent.trim() : '';
            }""", label)

    def detail_labels(self) -> list[str]:
        return self.dialog.evaluate("d => [...d.querySelectorAll('dt')].map(e => e.textContent.trim())")

    def detail_description(self) -> str:
        """The panel's (screen-reader) description, e.g. 'Beneficiary code EX000056'."""
        return self.dialog.evaluate(
            "d => { const id = d.getAttribute('aria-describedby');"
            " return id && document.getElementById(id) ? document.getElementById(id).textContent.trim() : ''; }")

    def masked_account_text(self) -> str:
        return self.detail_value("Account")

    def check_status(self) -> None:
        self.dialog.get_by_role("button", name="Check status").click()

    def block(self, confirm: bool = True) -> None:
        self.dialog.get_by_role("button", name="Block", exact=True).click()
        confirm_dlg = self.page.get_by_role("dialog").filter(has_text="Block this beneficiary?").last
        confirm_dlg.wait_for()
        confirm_dlg.get_by_role("button", name="Block beneficiary" if confirm else "Cancel").click()

    def unblock(self) -> None:
        self.dialog.get_by_role("button", name="Unblock", exact=True).click()
