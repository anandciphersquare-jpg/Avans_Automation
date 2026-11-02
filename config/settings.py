"""
Central configuration for the SprintEXcrow / Awanse Console automation suite.

Nothing sensitive is hardcoded. Everything is read from environment variables
(optionally via a local .env file). Copy .env.example to .env and fill it in.

NOTE ON CREDENTIALS: the original testing brief pasted the admin password in
plain text. Treat that credential as exposed — rotate it and supply the new
one through the environment, never in source control.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    # optional: load a local .env if present
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional at runtime
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Endpoints:
    """
    API paths used by the API / security tests, relative to API_BASE_URL.
    These are best-effort defaults — CONFIRM each path against the real backend
    (DevTools > Network) and override via the matching env var if different.
    A test that hits an unconfigured/placeholder path should skip, not fail.
    """
    # confirmed against the live app's code and network calls, 2026-10-21
    login: str = os.getenv("EP_LOGIN", "/api/v1/auth/login")
    verify_otp: str = os.getenv("EP_VERIFY_OTP", "/api/v1/auth/verify-otp")
    resend_otp: str = os.getenv("EP_RESEND_OTP", "/api/v1/auth/resend-otp")
    forgot_password: str = os.getenv("EP_FORGOT_PASSWORD", "/api/v1/auth/forgot-password")
    reset_password: str = os.getenv("EP_RESET_PASSWORD", "/api/v1/auth/reset-password")
    reset_password_verify: str = os.getenv("EP_RESET_PASSWORD_VERIFY", "/api/v1/auth/reset-password/verify")
    change_password: str = os.getenv("EP_CHANGE_PASSWORD", "/api/v1/auth/change-password")
    logout: str = os.getenv("EP_LOGOUT", "/api/v1/auth/logout")
    auth_me: str = os.getenv("EP_AUTH_ME", "/api/v1/auth/me")
    navigation: str = os.getenv("EP_NAVIGATION", "/api/v1/navigation")
    dashboard: str = os.getenv("EP_DASHBOARD", "/api/v1/dashboard/summary")
    beneficiaries: str = os.getenv("EP_BENEFICIARIES", "/api/v1/beneficiaries")
    beneficiary_code: str = os.getenv("EP_BENEFICIARY_CODE", "/api/v1/beneficiaries/code")
    users: str = os.getenv("EP_USERS", "/api/v1/users")
    # not yet seen in the live build (modules pending) — best-effort, a 404 skips
    transfers: str = os.getenv("EP_TRANSFERS", "/api/v1/transfers")
    transfer_approve: str = os.getenv("EP_TRANSFER_APPROVE", "/api/v1/transfers/{id}/approve")
    roles: str = os.getenv("EP_ROLES", "/api/v1/roles")
    audit: str = os.getenv("EP_AUDIT", "/api/v1/audit-trail")

    # paths behind modules that are NOT live in the current build — these must
    # be locked (403/404) for the current release.
    hidden_create_transfer: str = os.getenv("EP_HIDDEN_CREATE_TRANSFER", "/api/v1/transfers/create")
    hidden_approvals: str = os.getenv("EP_HIDDEN_APPROVALS", "/api/v1/approvals")
    hidden_virtual_id: str = os.getenv("EP_HIDDEN_VIRTUAL_ID", "/api/v1/virtual-ids")
    hidden_master_escrow: str = os.getenv("EP_HIDDEN_MASTER_ESCROW", "/api/v1/master-escrow")
    hidden_deposits: str = os.getenv("EP_HIDDEN_DEPOSITS", "/api/v1/deposits")
    hidden_qr_settlements: str = os.getenv("EP_HIDDEN_QR", "/api/v1/qr-settlements")


@dataclass(frozen=True)
class Settings:
    # --- targets -----------------------------------------------------------
    base_url: str = os.getenv("BASE_URL", "https://uat-avanse.sprintexcrow.in")
    api_base_url: str = os.getenv("API_BASE_URL", os.getenv("BASE_URL", "https://uat-avanse.sprintexcrow.in"))

    # --- credentials (from env only) --------------------------------------
    admin_email: str = os.getenv("ADMIN_EMAIL", "")
    # use the `admin_password` property: it prefers a password saved by the
    # forgot-password flow over this .env value
    admin_password_env: str = os.getenv("ADMIN_PASSWORD", "")
    # a separate, limited-role (non-admin) user for access-control tests
    user_email: str = os.getenv("USER_EMAIL", "")
    user_password: str = os.getenv("USER_PASSWORD", "")
    # a user configured as Maker (to verify maker != checker)
    maker_email: str = os.getenv("MAKER_EMAIL", "")
    maker_password: str = os.getenv("MAKER_PASSWORD", "")

    # --- OTP ---------------------------------------------------------------
    # strategy: "gmail_web" (open Gmail in the browser, copy the newest code;
    # the tester only does Google's 2-step verification once), "imap" (read
    # the latest code over IMAP - needs an App Password), "static"
    # (OTP_STATIC in UAT), "api" (fetch from a mailbox hook), or "manual"
    # (you type the code into the browser yourself — run with --headed; local
    # runs only, not CI).
    otp_strategy: str = os.getenv("OTP_STRATEGY", "static")
    otp_static: str = os.getenv("OTP_STATIC", "")
    otp_api_url: str = os.getenv("OTP_API_URL", "")  # used when strategy == "api"
    otp_manual_timeout_s: int = _int("OTP_MANUAL_TIMEOUT_S", 180)  # time to type it by hand

    # --- mailbox (OTP_STRATEGY=imap and the forgot-password flow) -----------
    mail_imap_host: str = os.getenv("MAIL_IMAP_HOST", "imap.gmail.com")
    mail_user: str = os.getenv("MAIL_USER", "")
    mail_app_password: str = os.getenv("MAIL_APP_PASSWORD", "")
    # OTP_STRATEGY=gmail_web: Gmail opened in the browser; the 2-step code is typed by the tester
    mail_password: str = os.getenv("MAIL_PASSWORD", "")  # blank = tester types it in the browser
    gmail_state_path: str = os.getenv("GMAIL_STATE", ".auth/gmail_state.json")
    gmail_login_timeout_s: int = _int("GMAIL_LOGIN_TIMEOUT_S", 300)
    otp_mail_subject: str = os.getenv("OTP_MAIL_SUBJECT", "Your SprintEXcrow sign-in code")
    reset_mail_subject: str = os.getenv("RESET_MAIL_SUBJECT", "password")
    otp_mail_timeout_s: int = _int("OTP_MAIL_TIMEOUT_S", 90)

    # password set by the forgot-password flow, reused by every later login
    credentials_store_path: str = os.getenv("CREDENTIALS_STORE", ".auth/credentials.json")
    # new password for the reset; blank = generate one
    reset_new_password: str = os.getenv("RESET_NEW_PASSWORD", "")

    # --- geolocation (sign-in is blocked without Allow Location) -----------
    geo_latitude: float = float(os.getenv("GEO_LAT", "28.6139"))   # default: Delhi
    geo_longitude: float = float(os.getenv("GEO_LNG", "77.2090"))

    # --- runtime -----------------------------------------------------------
    headless: bool = _bool("HEADLESS", True)
    slow_mo: int = _int("SLOW_MO", 0)
    default_timeout_ms: int = _int("DEFAULT_TIMEOUT_MS", 30_000)
    browser: str = os.getenv("BROWSER", "chromium")
    storage_state_path: str = os.getenv("STORAGE_STATE", ".auth/admin_state.json")

    endpoints: Endpoints = field(default_factory=Endpoints)

    # --- helpers -----------------------------------------------------------
    def url(self, path: str = "/") -> str:
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def api(self, path: str) -> str:
        return self.api_base_url.rstrip("/") + "/" + path.lstrip("/")

    @property
    def admin_password(self) -> str:
        # read on every access so a reset earlier in the same run is picked up
        from utils.credential_store import saved_password
        saved = saved_password(self.credentials_store_path, self.admin_email) if self.admin_email else None
        return saved or self.admin_password_env

    @property
    def has_admin_creds(self) -> bool:
        return bool(self.admin_email and self.admin_password)

    @property
    def has_user_creds(self) -> bool:
        return bool(self.user_email and self.user_password)


settings = Settings()
