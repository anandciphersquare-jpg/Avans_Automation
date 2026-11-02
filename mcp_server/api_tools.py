"""
API, API-security and API-performance checks.

Built on api.api_client.ApiClient and the endpoint map in config.settings, so
anything configured for the pytest suite (EP_* overrides, creds) applies here.
All functions are blocking; server.py runs them in a worker thread.
"""
from __future__ import annotations

import re
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields

from api.api_client import ApiClient
from config.settings import settings
from mcp_server.redact import body_preview, redact_headers
from utils.assertions import FULL_ACCOUNT_RE, SQLI_PAYLOADS, XSS_PAYLOADS, assert_security_headers

ROLES = {
    "admin": lambda: (settings.admin_email, settings.admin_password),
    "user": lambda: (settings.user_email, settings.user_password),
    "maker": lambda: (settings.maker_email, settings.maker_password),
}
_clients: dict[str, ApiClient] = {}

# hard caps so a load test can never turn into a flood against shared UAT
MAX_REQUESTS = 500
MAX_CONCURRENCY = 20


# --------------------------------------------------------------------------- auth
def login(role: str, email: str | None = None, password: str | None = None) -> dict:
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    env_email, env_password = ROLES[role]()
    c = ApiClient()
    token = c.login(email or env_email, password or env_password)
    _clients[role] = c
    return {"role": role, "logged_in": True, "token_length": len(token)}


def client(role: str) -> ApiClient:
    """A client for the role; logs in lazily from env creds on first use."""
    if role in ("anonymous", "none"):
        return ApiClient()
    if role not in _clients:
        login(role)
    return _clients[role]


# ----------------------------------------------------------------------- request
def request(method: str, path: str, role: str = "admin", json_body=None, params=None,
            headers=None, expected_status: int | list[int] | None = None,
            json_schema: dict | None = None, expect_contains: str | None = None,
            timeout_s: int = 20) -> dict:
    c = client(role)
    started = time.perf_counter()
    r = c.request(method.upper(), path, auth=role not in ("anonymous", "none"),
                  headers=headers, params=params, json=json_body, timeout=timeout_s)
    elapsed = round((time.perf_counter() - started) * 1000, 1)

    assertions = []
    if expected_status is not None:
        allowed = expected_status if isinstance(expected_status, list) else [expected_status]
        assertions.append({"check": f"status in {allowed}", "passed": r.status_code in allowed,
                           "actual": r.status_code})
    if expect_contains:
        assertions.append({"check": f"body contains {expect_contains!r}",
                           "passed": expect_contains in (r.text or "")})
    if json_schema:
        import jsonschema
        try:
            errors = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                      for e in jsonschema.Draft202012Validator(json_schema).iter_errors(r.json())][:10]
        except ValueError:
            errors = ["response body is not JSON"]
        assertions.append({"check": "matches json_schema", "passed": not errors, "errors": errors})

    return {
        "request": {"method": method.upper(), "url": r.url, "role": role},
        "status": r.status_code,
        "elapsed_ms": elapsed,
        "headers": redact_headers(dict(r.headers)),
        "body": body_preview(r),
        "assertions": assertions,
        "passed": all(a["passed"] for a in assertions) if assertions else None,
    }


# ---------------------------------------------------------------- endpoint probe
def probe_endpoints() -> dict:
    """GET every configured endpoint anonymously and (if possible) as admin."""
    admin = None
    if settings.has_admin_creds:
        try:
            admin = client("admin")
        except Exception as exc:  # noqa: BLE001
            admin_error = str(exc)
    anon = ApiClient()
    rows = []
    for f in fields(settings.endpoints):
        path = getattr(settings.endpoints, f.name)
        if "{" in path:
            continue
        row = {"name": f.name, "path": path, "anonymous": _status(anon, path)}
        if admin:
            row["admin"] = _status(admin, path)
        rows.append(row)
    out = {"base_url": settings.api_base_url, "endpoints": rows,
           "hint": "404 for both usually means the path is wrong - override it with the EP_* env var."}
    if settings.has_admin_creds and admin is None:
        out["admin_login_error"] = admin_error
    return out


def _status(c: ApiClient, path: str):
    try:
        return c.get(path, auth=bool(c.token), timeout=15).status_code
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc.__class__.__name__}"


# ------------------------------------------------------------------ security scan
_SQL_ERR = re.compile(r"sql syntax|sqlstate|ora-\d{5}|psql|sqlite|mysql|syntax error at or near|unclosed quotation", re.I)
_STACK = re.compile(r"traceback \(most recent|\bat [\w.$]+\([\w]+\.java:\d+\)|exception in thread|node_modules/|\.cs:line \d+", re.I)


def security_scan(path: str, role: str = "admin", query_param: str = "search") -> dict:
    checks: list[dict] = []

    def add(name, status, detail=""):
        checks.append({"check": name, "result": status, "detail": detail})

    anon = ApiClient()
    r = anon.get(path, auth=False)
    if r.status_code == 404:
        return {"path": path, "summary": "skipped",
                "detail": "Endpoint returned 404 unauthenticated - path probably not wired. Run api_probe_endpoints."}
    add("rejects unauthenticated request", "pass" if r.status_code in (401, 403) else "fail",
        f"status {r.status_code}")

    bad = ApiClient()
    bad.set_token("eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.")
    r = bad.get(path)
    add("rejects tampered/alg=none token", "pass" if r.status_code in (401, 403) else "fail",
        f"status {r.status_code}")

    try:
        c = client(role)
    except Exception as exc:  # noqa: BLE001
        add(f"login as {role}", "skip", str(exc))
        return _summarise(path, checks)

    base = c.get(path)
    add(f"{role} can access", "pass" if base.status_code < 400 else "warn", f"status {base.status_code}")

    missing = assert_security_headers(dict(base.headers))
    add("security headers present", "fail" if missing else "pass", ", ".join(missing) or "all present")

    disclosed = {k: v for k, v in base.headers.items()
                 if k.lower() in ("server", "x-powered-by", "x-aspnet-version") and re.search(r"\d", v)
                 or k.lower() == "x-powered-by"}
    add("no server/version disclosure", "warn" if disclosed else "pass", str(disclosed or ""))

    evil = "https://evil.example.com"
    r = c.get(path, headers={"Origin": evil})
    acao, acac = r.headers.get("Access-Control-Allow-Origin", ""), r.headers.get("Access-Control-Allow-Credentials", "")
    if acao in (evil, "*") and acac.lower() == "true":
        add("CORS does not trust arbitrary origins", "fail", f"ACAO={acao}, credentials=true")
    elif acao == evil:
        add("CORS does not trust arbitrary origins", "warn", "origin reflected (no credentials)")
    else:
        add("CORS does not trust arbitrary origins", "pass", f"ACAO={acao or '<none>'}")

    r = c.request("TRACE", path)
    add("TRACE method disabled", "pass" if r.status_code in (403, 404, 405, 501) else "fail",
        f"status {r.status_code}")

    sqli_fail = []
    for p in SQLI_PAYLOADS:
        r = c.get(path, params={query_param: p})
        if r.status_code >= 500 or _SQL_ERR.search(r.text or ""):
            sqli_fail.append(f"{p!r} -> {r.status_code}")
    add(f"SQLi in ?{query_param}= handled safely", "fail" if sqli_fail else "pass", "; ".join(sqli_fail))

    reflected = []
    for p in XSS_PAYLOADS:
        r = c.get(path, params={query_param: p})
        if "html" in r.headers.get("Content-Type", "") and p in (r.text or ""):
            reflected.append(p)
    add("XSS payload not reflected raw in HTML", "fail" if reflected else "pass", "; ".join(reflected))

    r = c.post(path, data='{"broken', headers={"Content-Type": "application/json"})
    leak = _STACK.search(r.text or "") or _SQL_ERR.search(r.text or "")
    add("malformed body gives no stack trace", "fail" if leak else "pass",
        f"status {r.status_code}" + (f", leaked: {leak.group(0)!r}" if leak else ""))

    body = (base.text or "").lower().replace(" ", "")
    exposed = [k for k in ("password", "otp", "secret", "cvv") if f'"{k}":' in body]
    add("no sensitive fields in response", "fail" if exposed else "pass", ", ".join(exposed))

    add("account numbers masked", "warn" if re.search(r'"\d{9,18}"', base.text or "") else "pass",
        "a 9-18 digit string value is present" if FULL_ACCOUNT_RE.search(base.text or "") else "")

    return _summarise(path, checks)


def _summarise(path: str, checks: list[dict]) -> dict:
    counts = Counter(c["result"] for c in checks)
    return {"path": path, "summary": dict(counts), "checks": checks}


def rate_limit_check(path: str | None = None, attempts: int = 25) -> dict:
    """Hammer the login endpoint with a FAKE account until 429 (never a real user)."""
    path = path or settings.endpoints.login
    attempts = max(1, min(attempts, 50))
    anon, codes = ApiClient(), []
    for _ in range(attempts):
        r = anon.post(path, json={"email": "mcp-bruteforce-probe@example.com", "password": "wrong"}, auth=False)
        codes.append(r.status_code)
        if r.status_code == 429:
            break
    return {"path": path, "attempts": len(codes), "throttled": 429 in codes,
            "first_429_at": codes.index(429) + 1 if 429 in codes else None,
            "status_counts": dict(Counter(codes))}


# --------------------------------------------------------------------- load test
def performance_test(path: str, method: str = "GET", role: str = "admin", total_requests: int = 50,
                     concurrency: int = 5, json_body=None) -> dict:
    total = max(1, min(total_requests, MAX_REQUESTS))
    conc = max(1, min(concurrency, MAX_CONCURRENCY))
    token = client(role).token if role not in ("anonymous", "none") else None

    def one(_):
        c = ApiClient()
        c.set_token(token)
        t = time.perf_counter()
        try:
            r = c.request(method.upper(), path, auth=bool(token), json=json_body)
            return (time.perf_counter() - t) * 1000, r.status_code
        except Exception as exc:  # noqa: BLE001
            return (time.perf_counter() - t) * 1000, exc.__class__.__name__

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as pool:
        results = list(pool.map(one, range(total)))
    wall = time.perf_counter() - started

    lat = sorted(ms for ms, _ in results)
    codes = Counter(code for _, code in results)
    errors = sum(n for code, n in codes.items() if not isinstance(code, int) or code >= 400)

    def pct(p):
        return round(lat[min(len(lat) - 1, int(round(p / 100 * (len(lat) - 1))))], 1)

    return {
        "path": path, "method": method.upper(), "requests": total, "concurrency": conc,
        "throughput_rps": round(total / wall, 2),
        "latency_ms": {"min": round(lat[0], 1), "avg": round(statistics.mean(lat), 1), "p50": pct(50),
                       "p90": pct(90), "p95": pct(95), "p99": pct(99), "max": round(lat[-1], 1)},
        "error_rate_pct": round(errors / total * 100, 2),
        "status_counts": {str(k): v for k, v in codes.items()},
        "caps": f"max {MAX_REQUESTS} requests / {MAX_CONCURRENCY} concurrency per run",
    }
