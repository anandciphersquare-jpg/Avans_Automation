"""Login, location gate, OTP and forgot-password page object."""
from __future__ import annotations

import re
import secrets
import time

from playwright.sync_api import Page, expect

from config.settings import settings
from pages.base_page import BasePage
from utils.credential_store import save_password
from utils.otp import get_otp


GMAIL_WEB = ("gmail_web", "gmail-web", "browser")


class LoginError(RuntimeError):
    """A login stage failed; the message is written for the test report."""


def _strategy() -> str:
    return (settings.otp_strategy or "").lower()


# Messages shown by the live build (2026-10-21), used by the auth tests.
MSG = {
    "email_required": "Enter your email",
    "email_format": "That does not look like an email address",
    "password_required": "Enter your password",
    "bad_credentials": "Invalid email or password.",
    "otp_six_digits": "Enter all six digits.",
    "otp_restart": "This code can no longer be used. Sign in again to get a new one.",
    "location_denied_title": "Location access is required to sign in",
    "reset_sent": "If an account exists for",
}


class LoginPage(BasePage):
    PATH = "/login"
    FORGOT_PATH = "/forgot-password"

    def open(self, next_path: str | None = None) -> "LoginPage":
        from urllib.parse import quote
        self.goto(self.PATH + (f"?next={quote(next_path, safe='')}" if next_path else ""))
        self.page.locator("#email").wait_for()
        return self

    # -- credential entry ---------------------------------------------------
    def enter_credentials(self, email: str, password: str) -> None:
        self.page.locator("#email").fill(email)
        self.page.locator("#password").fill(password)

    def sign_in_button(self):
        return self.page.locator("form button[type='submit']").first

    def wait_location_ready(self, timeout: int = 15_000) -> None:
        """Sign in is enabled only once the browser has reported a location."""
        self.page.wait_for_function(
            "() => { const b = document.querySelector(\"form button[type='submit']\");"
            " return b && !b.disabled && b.textContent.trim() === 'Sign in'; }", timeout=timeout)

    def submit(self) -> None:
        try:
            self.wait_location_ready()
        except Exception:  # noqa: BLE001 - location blocked: click anyway, the test checks
            pass
        self.sign_in_button().click(force=True)

    # -- messages on the sign-in form ---------------------------------------
    def field_error(self, field: str) -> str:
        """Inline message under #email / #password ('' when none)."""
        loc = self.page.locator(f"#{field}-error")
        return loc.inner_text().strip() if loc.count() else ""

    def form_alert(self, timeout: int = 8_000) -> str:
        """The server's refusal under the form, e.g. 'Invalid email or password.'"""
        loc = self.page.locator("form p[role='alert']")
        try:
            loc.first.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001
            return ""
        return loc.first.inner_text().strip()

    def location_banner(self) -> str:
        loc = self.page.locator("form [role='status']")
        return loc.first.inner_text().strip() if loc.count() else ""

    def on_otp_step(self) -> bool:
        return self.page.get_by_role("heading", name="Enter the code").is_visible()

    def resend_button(self):
        return self.page.get_by_role("button", name=re.compile(r"^Send a new code"))

    def use_different_account(self) -> None:
        self.page.get_by_role("button", name="Use a different account").click()

    def login(self, email: str, password: str, with_otp: bool = True) -> None:
        gmail, baseline = None, "" 
        if with_otp and _strategy() in GMAIL_WEB:
            from utils.gmail_web import reader_for
            gmail = reader_for(self.page)
            baseline = gmail.snapshot()  # Gmail signed in + newest OTP mail noted BEFORE Sign in
            self.page.bring_to_front()
        self.enter_credentials(email, password)
        sent_at = time.time()  # only a code mailed after this click is accepted
        self.submit()
        if with_otp:
            self.complete_otp(email=email, since=sent_at, gmail=gmail, baseline=baseline)

    # -- OTP ----------------------------------------------------------------
    def otp_inputs(self):
        # live UI: six boxes labelled "Digit 1".."Digit 6"; fall back to a single field
        boxes = self.page.locator('input[aria-label^="Digit" i], '
                                  'input[autocomplete="one-time-code"], '
                                  'input[name*="otp"], input[aria-label*="OTP" i]')
        return boxes

    def enter_otp(self, code: str) -> None:
        boxes = self.otp_inputs()
        count = boxes.count()
        if count >= 6:
            for i, ch in enumerate(code[:6]):
                boxes.nth(i).fill(ch)
        elif count == 1:
            boxes.first.fill(code)
        else:  # last resort — type into the focused element
            self.page.keyboard.type(code)

    def verify_button(self):
        b = self.page.get_by_role("button", name="Verify and sign in")
        if b.count():
            return b.first
        for name in ("Verify", "Submit", "Confirm"):
            b = self.button(name)
            if b.count():
                return b.first
        return self.page.locator('button[type="submit"]').first

    def otp_error(self, timeout: int = 8_000) -> str:
        loc = self.page.locator("form[aria-labelledby='otp-heading'] p[role='alert']")
        try:
            loc.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001
            return ""
        return loc.inner_text().strip()

    def complete_otp(self, email: str | None = None, since: float | None = None,
                     gmail=None, baseline: str = "") -> None:
        email = email or settings.admin_email
        try:
            self.otp_inputs().first.wait_for(timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            message = self.error_text()
            raise LoginError(
                "After clicking Sign in, the OTP screen did not appear within 30 s"
                + (f'; the page shows: "{message}"' if message else "")
                + ". The email / password may be wrong, or location was not allowed.") from exc
        if _strategy() == "manual":
            self.wait_for_manual_otp(email)
            return
        tried: set[str] = set()
        for attempt in range(3 if gmail is not None else 1):
            if gmail is not None:
                # an OTP mail requested earlier (e.g. by an OTP-step test) can land after the
                # baseline was taken; if the app refuses a code, try the next newer one
                code = gmail.wait_for_new_code(baseline if attempt == 0 else "", exclude=tried)
                tried.add(code)
                self.page.bring_to_front()
            else:
                code = get_otp(email=email, since=since)
            self.enter_otp(code)
            self.verify_button().click()
            try:
                self.page.wait_for_url(lambda u: "/login" not in u, timeout=20_000)
                return
            except Exception as exc:  # noqa: BLE001
                message = self.otp_error(timeout=1_000) or self.error_text()
                if gmail is not None and "not valid" in message.lower() and attempt < 2:
                    continue
                raise LoginError(
                    f"The OTP from the latest mail was entered and Verify was clicked, but the app stayed on "
                    f"the login page" + (f'; it shows: "{message}"' if message else "")
                    + f". Codes tried: {len(tried) or 1}. The code may be expired or rejected.") from exc

    def wait_for_manual_otp(self, email: str) -> None:
        """OTP_STRATEGY=manual: the tester types the mailed code into the
        (headed) browser and clicks Verify; the test continues once the app
        leaves /login."""
        timeout_s = settings.otp_manual_timeout_s
        notify_tester(f"Manual OTP: enter the code sent to {email} in the browser window "
                      f"and click Verify (waiting up to {timeout_s}s).")
        self.page.bring_to_front()
        self.page.evaluate(_BANNER_JS, f"Enter the OTP sent to {email} and click Verify. "
                                       f"Automation is waiting ({timeout_s}s).")
        try:
            self.page.wait_for_url(lambda u: "/login" not in u, timeout=timeout_s * 1000)
        except Exception as exc:  # noqa: BLE001
            raise LoginError(f"Manual OTP was not entered in the browser within {timeout_s}s.") from exc

    # -- forgot password ----------------------------------------------------
    def open_forgot_password(self) -> None:
        self.page.get_by_role("link", name="Forgot password?").click()
        self.page.get_by_role("heading", name="Forgot your password?").wait_for()

    def request_reset(self, email: str) -> None:
        self.page.locator("#email").fill(email)
        for name in ("Send reset link", "Send", "Reset", "Submit"):
            b = self.button(name)
            if b.count():
                b.first.click()
                return

    def reset_password_via_mail(self, email: str, new_password: str | None = None) -> str:
        """
        Forgot password end to end: request the reset, read the newest reset
        mail, follow its link or enter its OTP, set the new password, and save
        it so later logins use it. Returns the new password.
        """
        from utils.mailbox import extract_link, extract_otp, latest_mail

        new_password = new_password or settings.reset_new_password or _generate_password()
        self.goto(self.FORGOT_PATH)
        sent_at = time.time()
        self.request_reset(email)

        msg = latest_mail(settings.reset_mail_subject, since=sent_at,
                          timeout_s=settings.otp_mail_timeout_s)
        link = extract_link(msg, contains=settings.base_url.split("//")[-1].split("/")[0])
        if link:
            self.page.goto(link)
        if self.otp_inputs().count():
            self.enter_otp(extract_otp(msg))
            verify = self.verify_button()
            if verify.is_enabled() and not self._password_inputs().count():
                verify.click()

        pw = self._password_inputs()
        pw.first.wait_for()
        for i in range(pw.count()):  # new password + confirm password
            pw.nth(i).fill(new_password)
        for name in ("Reset password", "Set password", "Update password", "Save", "Submit", "Continue"):
            b = self.button(name)
            if b.count():
                b.first.click()
                break
        else:
            self.page.locator('button[type="submit"]').first.click()
        self.page.wait_for_load_state("networkidle")

        save_password(settings.credentials_store_path, email, new_password, reset_done=True)
        return new_password

    def _password_inputs(self):
        return self.page.locator('input[type="password"]')

    # -- assertions ---------------------------------------------------------
    def error_text(self) -> str:
        alert = self.form_alert(timeout=5_000)
        if alert:
            return alert
        t = self.toast_text()
        if t:
            return t
        err = self.page.locator('.error, .invalid-feedback, [role="alert"]')
        return (err.first.inner_text().strip() if err.count() else "")


# banner shown in the browser while the tester types the OTP (does not block clicks)
_BANNER_JS = """(text) => {
  const id = 'qa-manual-otp-banner';
  document.getElementById(id)?.remove();
  const b = document.createElement('div');
  b.id = id; b.textContent = text;
  b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;' +
    'background:#b45309;color:#fff;font:600 14px/1.4 system-ui,sans-serif;text-align:center;pointer-events:none';
  document.body.appendChild(b);
}"""


def notify_tester(message: str) -> None:
    """Print to the terminal even while pytest captures output."""
    from utils.console import say
    say(message)


def _generate_password() -> str:
    # upper + lower + digit + special, 12 chars
    return f"Escrow@{secrets.randbelow(90000) + 10000}"
