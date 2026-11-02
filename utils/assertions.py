"""Reusable payloads and security assertions shared across test modules."""
from __future__ import annotations

import re

# --- Attack payloads (non-destructive) ------------------------------------
# Boolean/format-based only. Do NOT add destructive DDL (DROP/DELETE) that
# could damage shared UAT data — these assert the app REJECTS the input.
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "admin'--",
    '" OR ""="',
    "') OR ('1'='1",
    "1 OR 1=1",
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "<svg/onload=alert(1)>",
]

INVALID_EMAILS = ["abc", "abc@", "abc@x", "a b@x.com", "@x.com", "abc@@x.com"]

INVALID_IFSC = ["HDFC000123", "HDFC00012345", "HDFCX001234", "hdfc0001234", "1234567890A"]

INVALID_IPS = ["999.1.1.1", "256.256.256.256", "10.0.0", "hello world", "203.0.113.0/33"]

# Things that must never appear in responses, storage, logs or audit text.
SENSITIVE_KEY_HINTS = ["password", "otp", "pin", "cvv", "secret", "token", "authorization"]
FULL_ACCOUNT_RE = re.compile(r"\b\d{9,18}\b")           # an unmasked bank account
MASKED_ACCOUNT_RE = re.compile(r"[*xX•]{2,}\d{2,4}$")   # e.g. ****1234


# --- Helpers ---------------------------------------------------------------
def is_masked(account_display: str) -> bool:
    """True when only the last few digits are visible (rest masked)."""
    s = (account_display or "").strip()
    if MASKED_ACCOUNT_RE.search(s):
        return True
    digits = re.sub(r"\D", "", s)
    return 0 < len(digits) <= 4  # only the tail is shown


def assert_security_headers(headers: dict) -> list[str]:
    """Return the list of MISSING recommended security headers (empty == good)."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    missing = []
    if "strict-transport-security" not in h:
        missing.append("Strict-Transport-Security")
    # a header set by both proxy and app arrives comma-joined ("nosniff, nosniff")
    if h.get("x-content-type-options", "").split(",")[0].strip().lower() != "nosniff":
        missing.append("X-Content-Type-Options: nosniff")
    if "x-frame-options" not in h and "content-security-policy" not in h:
        missing.append("X-Frame-Options or CSP frame-ancestors")
    if "referrer-policy" not in h:
        missing.append("Referrer-Policy")
    return missing


def assert_no_sensitive(blob: str) -> list[str]:
    """Return sensitive hints found in a text blob (empty list == clean)."""
    text = (blob or "").lower()
    hits = [k for k in SENSITIVE_KEY_HINTS if f'"{k}"' in text or f"{k}:" in text or f"{k}=" in text]
    return hits
