"""
Thin API client used by the API + security tests.

It wraps requests.Session and centralises auth so tests read clearly:

    api = ApiClient()
    api.login()                      # obtains and stores a bearer token
    r = api.get(ep.beneficiaries)    # authenticated
    r = api.get(ep.beneficiaries, auth=False)   # no token -> expect 401

Endpoint paths come from config.settings.Endpoints. Where a path is a
best-effort default, prefer configuring it via env; a test can skip if the
endpoint is clearly not wired up (see is_placeholder()).
"""
from __future__ import annotations

from typing import Any

import requests

from config.settings import settings
from reporting.api_log import requests_hook


class ApiClient:
    def __init__(self, base_url: str | None = None, verify_tls: bool = True):
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify_tls
        # log every call into the running test's execution report (no-op outside tests)
        self.session.hooks["response"].append(requests_hook)
        self.token: str | None = None

    # -- auth ---------------------------------------------------------------
    def login(self, email: str | None = None, password: str | None = None) -> str:
        """Authenticate and store the token. Returns the raw token string.

        The exact token field differs per backend; we try the common ones.
        """
        email = email or settings.admin_email
        password = password or settings.admin_password
        if not (email and password):
            raise RuntimeError("No credentials provided; set ADMIN_EMAIL / ADMIN_PASSWORD.")
        resp = self.post(settings.endpoints.login, json={
            "email": email, "password": password, "clientGeo": self.client_geo()}, auth=False)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if (data.get("data") or {}).get("otpRequired"):
            raise RuntimeError("API login needs the emailed OTP (otpRequired=true): use the "
                               "`admin_token` fixture, which borrows the signed-in UI session.")
        token = (
            data.get("token")
            or data.get("accessToken")
            or data.get("access_token")
            or (data.get("data") or {}).get("token")
        )
        if not token:
            raise RuntimeError(f"Could not find a token in the login response: {data!r}")
        self.token = token
        return token

    @staticmethod
    def client_geo() -> dict:
        """The location block the app sends with a sign-in (it is mandatory)."""
        return {"latitude": settings.geo_latitude, "longitude": settings.geo_longitude,
                "timezone": "Asia/Calcutta"}

    def set_token(self, token: str | None) -> None:
        self.token = token

    # -- verbs --------------------------------------------------------------
    def _headers(self, auth: bool, extra: dict | None) -> dict:
        headers: dict[str, str] = {"Accept": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def request(self, method: str, path: str, *, auth: bool = True,
                headers: dict | None = None, **kwargs: Any) -> requests.Response:
        url = path if path.startswith("http") else self.base_url + "/" + path.lstrip("/")
        return self.session.request(
            method, url, headers=self._headers(auth, headers),
            timeout=kwargs.pop("timeout", 20), allow_redirects=False, **kwargs,
        )

    def get(self, path: str, **kw: Any) -> requests.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> requests.Response:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> requests.Response:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> requests.Response:
        return self.request("DELETE", path, **kw)

    # -- convenience --------------------------------------------------------
    @staticmethod
    def is_placeholder(response: requests.Response) -> bool:
        """Heuristic: the endpoint path is probably wrong/not wired (404 on an
        unauthenticated probe). Tests use this to skip rather than false-fail."""
        return response.status_code == 404
