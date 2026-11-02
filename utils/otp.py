"""Pluggable OTP provider so the login flow can run unattended in UAT/CI."""
from __future__ import annotations

import time

import requests

from config.settings import settings


class OtpError(RuntimeError):
    pass


def get_otp(email: str | None = None, timeout_s: int = 30, since: float | None = None,
            subject: str | None = None) -> str:
    """
    Return a 6-digit OTP according to OTP_STRATEGY.

    - imap   : the code from the NEWEST matching mail in the Gmail inbox that
               arrived at or after `since` (epoch secs; take it just before
               the click that sends the code).
    - static : use OTP_STATIC (a fixed UAT test OTP). Best for CI.
    - api    : GET OTP_API_URL (a test mailbox / helper endpoint) and read `otp`.
    - manual : prompt on the console (local, interactive runs only).
    """
    strategy = (settings.otp_strategy or "static").lower()

    if strategy in ("imap", "gmail"):
        from utils.mailbox import MailboxError, extract_otp, latest_mail
        try:
            msg = latest_mail(subject or settings.otp_mail_subject,
                              since=since if since is not None else time.time() - 120,
                              timeout_s=max(timeout_s, settings.otp_mail_timeout_s))
            return extract_otp(msg)
        except MailboxError as exc:
            raise OtpError(str(exc)) from exc

    if strategy in ("gmail_web", "gmail-web", "browser"):
        # needs the browser: LoginPage.login() reads it through utils.gmail_web
        raise OtpError("OTP_STRATEGY=gmail_web reads the code in the browser via LoginPage.login(); "
                       "use ui_submit_otp from the MCP server, or OTP_STRATEGY=imap.")

    if strategy == "static":
        if not settings.otp_static:
            raise OtpError("OTP_STRATEGY=static but OTP_STATIC is not set.")
        return settings.otp_static

    if strategy == "api":
        if not settings.otp_api_url:
            raise OtpError("OTP_STRATEGY=api but OTP_API_URL is not set.")
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            try:
                r = requests.get(
                    settings.otp_api_url,
                    params={"email": email} if email else None,
                    timeout=10,
                )
                if r.ok:
                    code = (r.json() or {}).get("otp")
                    if code:
                        return str(code)
                last = f"{r.status_code}: {r.text[:120]}"
            except requests.RequestException as exc:  # pragma: no cover
                last = str(exc)
            time.sleep(2)
        raise OtpError(f"Timed out fetching OTP from the mailbox hook. Last: {last}")

    if strategy == "manual":  # pragma: no cover - interactive only
        import sys
        if not sys.stdin or not sys.stdin.isatty():
            # pytest: LoginPage waits for the code typed in the browser; MCP: ui_submit_otp
            raise OtpError("OTP_STRATEGY=manual: type the OTP in the headed browser "
                           "(or use ui_submit_otp from the MCP server).")
        code = input(f"Enter the OTP sent to {email or 'the test account'}: ").strip()
        if not code:
            raise OtpError("No OTP entered.")
        return code

    raise OtpError(f"Unknown OTP_STRATEGY: {settings.otp_strategy!r}")
