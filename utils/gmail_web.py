"""
Read the SprintEXcrow sign-in OTP from Gmail in the browser (OTP_STRATEGY=gmail_web).

    1. A separate tab in the test browser opens Gmail.
    2. Not signed in yet: the Gmail address (MAIL_USER) and password (MAIL_PASSWORD)
       are typed automatically. Google's 2-step verification is done BY YOU in
       that tab; the run waits up to GMAIL_LOGIN_TIMEOUT_S.
    3. The Google session is saved to GMAIL_STATE, so later runs skip the
       sign-in and the 2-step step.
    4. Before "Sign in" is clicked on SprintEXcrow the newest OTP mail is noted;
       afterwards Gmail is searched until a NEWER mail arrives, it is opened and
       its 6-digit code is copied into the OTP boxes.

If Google refuses to sign in inside the automation browser ("This browser or
app may not be secure"), sign in once with your installed Chrome:

    python -m utils.gmail_web login
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from config.settings import settings

MAIL_URL = "https://mail.google.com/mail/u/0/"
SIGNIN_URL = ("https://accounts.google.com/ServiceLogin?service=mail&passive=true"
              "&continue=https%3A%2F%2Fmail.google.com%2Fmail%2Fu%2F0%2F")
OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
ROWS = 'div[role="main"] tr.zA'

_readers: dict[int, "GmailReader"] = {}


class GmailWebError(RuntimeError):
    """Plain-English problem reading the OTP from Gmail (shown as-is in the report)."""


def reader_for(page) -> "GmailReader":
    """One Gmail tab per browser, reused by every login in the session."""
    browser = page.context.browser
    if browser is None:
        raise GmailWebError("Gmail OTP reading needs a normal browser context (not a persistent one).")
    key = id(browser)
    reader = _readers.get(key)
    if reader is None or reader.closed:
        reader = _readers[key] = GmailReader(browser)
    return reader


def _say(message: str) -> None:
    from utils.console import say
    say(message)


_BANNER_JS = """(text) => {
  if (!document.body) return;
  let b = document.getElementById('qa-gmail-banner');
  if (!b) {
    b = document.createElement('div'); b.id = 'qa-gmail-banner';
    b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;' +
      'background:#b45309;color:#fff;font:600 14px/1.4 system-ui,sans-serif;text-align:center;pointer-events:none';
    document.body.appendChild(b);
  }
  b.textContent = text;
}"""


class GmailReader:
    def __init__(self, browser):
        state = Path(settings.gmail_state_path)
        self.context = browser.new_context(
            storage_state=str(state) if state.exists() else None,
            locale="en-US", viewport={"width": 1280, "height": 860})
        self.page = self.context.new_page()
        self.signed_in = False
        self.last_code = ""

    @property
    def closed(self) -> bool:
        return self.page.is_closed()

    # ---------------------------------------------------------------- sign in
    def ensure_signed_in(self) -> None:
        if self.signed_in:
            return
        page = self.page
        page.goto(MAIL_URL, wait_until="domcontentloaded")
        if not page.url.startswith(MAIL_URL[:-5]):  # not in the mailbox -> sign in
            self._sign_in()
        page.locator('div[role="main"], input[name="q"]').first.wait_for(timeout=60_000)
        Path(settings.gmail_state_path).parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=settings.gmail_state_path)
        self.signed_in = True

    def _sign_in(self) -> None:
        if not settings.mail_user:
            raise GmailWebError("MAIL_USER is not set: the Gmail address to read the OTP from is missing in .env.")
        self.page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        self._wait_for_tester()

    def _visible(self, selector: str):
        loc = self.page.locator(selector)
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    def _step(self) -> str:
        """React to whatever Google shows now; returns what was done (for the log)."""
        page = self.page
        email = self._visible("#identifierId, input[type='email'][name='identifier']")
        if email is not None and not email.input_value():
            email.fill(settings.mail_user)
            page.locator("#identifierNext").first.click()
            return "typed the Gmail address"
        password = self._visible("input[name='Passwd']")
        if password is not None and settings.mail_password and not password.input_value():
            password.fill(settings.mail_password)
            page.locator("#passwordNext").first.click()
            return "typed the Gmail password"
        chooser = self._visible(f"[data-identifier='{settings.mail_user}']")
        if chooser is not None:
            chooser.click()
            return "picked the account"
        # optional prompts after sign-in (passkeys, recovery info, "stay signed in")
        for label in ("Not now", "Skip", "Remind me later", "Cancel"):
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() and btn.first.is_visible() and "challenge" not in page.url:
                btn.first.click()
                return f"dismissed the \"{label}\" prompt"
        return ""

    def _wait_for_tester(self) -> None:
        """Drive Google's sign-in; the tester only types the 2-step verification code."""
        page = self.page
        timeout_s = settings.gmail_login_timeout_s
        need = "the 2-step verification code" if settings.mail_password else "the Gmail password and 2-step code"
        _say(f"Gmail sign-in for {settings.mail_user}: the email{' and password are' if settings.mail_password else ' is'} "
             f"typed automatically. Enter {need} in the Gmail tab (waiting up to {timeout_s}s); "
             "the SprintEXcrow OTP is then read automatically.")
        page.bring_to_front()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if page.url.startswith(MAIL_URL[:-5]):
                return
            body = ""
            try:
                body = page.inner_text("body", timeout=2_000)
            except Exception:  # noqa: BLE001 - page is navigating
                pass
            if re.search(r"couldn.t find your google account", body, re.I):
                raise GmailWebError(f"Google says it couldn't find the account {settings.mail_user} (MAIL_USER).")
            if "browser or app may not be secure" in body.lower():
                raise GmailWebError(
                    "Google blocked the Gmail sign-in in the automation browser (\"This browser or app may "
                    "not be secure\"). Sign in once with your own Chrome: python -m utils.gmail_web login")
            if re.search(r"wrong password", body, re.I):
                raise GmailWebError("Gmail rejected the password in MAIL_PASSWORD (\"Wrong password\").")
            try:
                done = self._step()
                if done:
                    _say(f"Gmail sign-in: {done}.")
                    page.wait_for_timeout(2500)
                    continue
                page.evaluate(_BANNER_JS, f"Automation: enter {need} here. Waiting for Gmail to open…")
            except Exception:  # noqa: BLE001 - page is navigating
                pass
            page.wait_for_timeout(1500)
        raise GmailWebError(
            f"Gmail sign-in was not completed within {timeout_s}s: the 2-step verification was not "
            "entered in the Gmail tab.")

    # ---------------------------------------------------------------- reading
    def _search(self) -> None:
        query = f'subject:"{settings.otp_mail_subject}" newer_than:1d'
        target = MAIL_URL + "#search/" + quote(query, safe="")
        if self.page.url != target:
            self.page.goto(target, wait_until="domcontentloaded")
        else:
            self.page.reload(wait_until="domcontentloaded")
        # results, or Gmail's "No messages matched your search"
        self.page.locator(f'{ROWS}, td.TC').first.wait_for(timeout=30_000)
        self.page.wait_for_timeout(1500)  # the old list (inbox) can still show for a moment

    def _otp_row(self):
        """Newest list row whose subject is the OTP mail (never another SprintEXcrow mail)."""
        subject = settings.otp_mail_subject.lower()
        rows = self.page.locator(ROWS)
        for i in range(min(rows.count(), 50)):
            row = rows.nth(i)
            try:
                if row.is_visible() and subject in row.inner_text().lower():
                    return row
            except Exception:  # noqa: BLE001 - list re-rendered
                return None
        return None

    def _top_row(self) -> str:
        row = self._otp_row()
        return " ".join(row.inner_text().split()) if row is not None else ""

    def snapshot(self) -> str:
        """Newest OTP mail now (call BEFORE clicking Sign in on the app)."""
        self.ensure_signed_in()
        self._search()
        return self._top_row()

    def wait_for_new_code(self, baseline: str, timeout_s: int | None = None,
                          exclude: set[str] | None = None) -> str:
        """Wait for an OTP mail newer than `baseline`, open it, return its code.
        Codes in `exclude` (already tried and refused) are skipped."""
        timeout_s = timeout_s or settings.otp_mail_timeout_s
        deadline = time.time() + timeout_s
        exclude = exclude or set()
        while True:
            self._search()
            top = self._top_row()
            if top and top != baseline:
                code = self._open_top_and_read()
                if code and code != self.last_code and code not in exclude:
                    self.last_code = code
                    return code
            if time.time() >= deadline:
                raise GmailWebError(
                    f"No new \"{settings.otp_mail_subject}\" mail reached {settings.mail_user} within "
                    f"{timeout_s}s after Sign in, so there was no OTP to enter.")
            self.page.wait_for_timeout(3000)

    def _open_top_and_read(self) -> str:
        page = self.page
        row = self._otp_row()
        if row is None:
            return ""
        snippet = row.inner_text()
        row.click()
        bodies = page.locator("div.a3s")
        try:
            bodies.last.wait_for(timeout=15_000)
            text = bodies.last.inner_text()
        except Exception:  # noqa: BLE001 - fall back to the list snippet
            text = snippet
        codes = OTP_RE.findall(text) or OTP_RE.findall(snippet)
        if not codes:
            raise GmailWebError(
                f"The newest \"{settings.otp_mail_subject}\" mail was opened but has no 6-digit code in it.")
        return codes[-1]


# --------------------------------------------------------------------------- #
# one-time sign-in with the installed Chrome (if Google blocks the test browser)
# --------------------------------------------------------------------------- #
def _cli_login() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:  # noqa: BLE001 - Chrome not installed
            browser = p.chromium.launch(headless=False)
        reader = GmailReader(browser)
        reader.ensure_signed_in()
        print(f"Gmail session saved to {settings.gmail_state_path}. Tests will reuse it.")
        browser.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["login"]:
        _cli_login()
    else:
        print("usage: python -m utils.gmail_web login")
