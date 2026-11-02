"""Read sign-in / reset mails from the test Gmail inbox over IMAP.

Gmail only accepts an App Password over IMAP (the normal account password is
rejected with AUTHENTICATIONFAILED). Create one at
https://myaccount.google.com/apppasswords and put it in MAIL_APP_PASSWORD.
"""
from __future__ import annotations

import email
import imaplib
import re
import time
from email.header import decode_header, make_header
from email.message import Message

from config.settings import settings

OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
LINK_RE = re.compile(r"https?://[^\s\"'<>]+")
CLOCK_SKEW_S = 60  # tolerate a local clock that runs ahead of Gmail's


class MailboxError(RuntimeError):
    pass


def _subject(msg: Message) -> str:
    return str(make_header(decode_header(msg.get("Subject", ""))))


def body_text(msg: Message) -> str:
    """Plain-text body, falling back to tag-stripped HTML."""
    plain, html = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        (plain if ctype == "text/plain" else html).append(text)
    if plain:
        return "\n".join(plain)
    return re.sub(r"<[^>]+>", " ", "\n".join(html))


def _connect() -> imaplib.IMAP4_SSL:
    if not (settings.mail_user and settings.mail_app_password):
        raise MailboxError("MAIL_USER / MAIL_APP_PASSWORD are not set.")
    box = imaplib.IMAP4_SSL(settings.mail_imap_host, 993)
    try:
        box.login(settings.mail_user, settings.mail_app_password)
    except imaplib.IMAP4.error as exc:
        raise MailboxError(
            f"IMAP login failed for {settings.mail_user}: {exc}. Gmail needs an App "
            "Password here, not the normal account password."
        ) from exc
    return box


def latest_mail(subject: str, since: float, timeout_s: int = 90, poll_s: int = 3) -> Message:
    """
    Wait for and return the NEWEST mail whose subject contains `subject` and
    which Gmail received at or after `since` (epoch seconds). Older mails are
    ignored so a stale code from a previous run is never used.
    """
    deadline = time.time() + timeout_s
    since_day = time.strftime("%d-%b-%Y", time.localtime(since - 86_400))
    while True:
        box = _connect()
        try:
            box.select("INBOX", readonly=True)
            _, data = box.search(None, "SUBJECT", f'"{subject}"', "SINCE", since_day)
            newest, newest_ts = None, 0.0
            for msg_id in data[0].split():
                _, meta = box.fetch(msg_id, "(INTERNALDATE)")
                received = imaplib.Internaldate2tuple(meta[0])
                ts = time.mktime(received) if received else 0.0
                if ts >= since - CLOCK_SKEW_S and ts > newest_ts:
                    newest, newest_ts = msg_id, ts
            if newest is not None:
                _, raw = box.fetch(newest, "(BODY.PEEK[])")
                return email.message_from_bytes(raw[0][1])
        finally:
            box.logout()
        if time.time() >= deadline:
            raise MailboxError(f"No mail with subject {subject!r} arrived within {timeout_s}s.")
        time.sleep(poll_s)


def extract_otp(msg: Message) -> str:
    for text in (_subject(msg), body_text(msg)):
        m = OTP_RE.search(text)
        if m:
            return m.group(1)
    raise MailboxError(f"No 6-digit code found in mail {_subject(msg)!r}.")


def extract_link(msg: Message, contains: str = "") -> str | None:
    for url in LINK_RE.findall(body_text(msg)):
        url = url.rstrip(").,;")
        if contains in url:
            return url
    return None
