"""
SprintEXcrow testing MCP server.

Exposes the automation suite in this repo as MCP tools covering:
  * test-suite execution  (run / list the pytest suites by marker, file, keyword)
  * API testing           (requests + assertions + JSON-schema contract checks)
  * API security          (authn/z, headers, CORS, injection, leakage, rate limit)
  * API performance       (capped load test with latency percentiles)
  * functional UI testing (drive a live browser: navigate, click, fill, assert)
  * UI/UX                 (accessibility, responsive, web-vitals, links, visual diff)
  * UI security           (cookies, storage, console leaks, input/XSS probing)

Run:  python mcp_server/server.py            (stdio - for Claude Code / Desktop)
      python mcp_server/server.py --http     (streamable HTTP on 127.0.0.1:8000)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # .env, .auth/ and reports/ are all relative to the project root

import anyio  # noqa: E402
from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from config.settings import settings  # noqa: E402
from mcp_server import api_tools, runner, ux  # noqa: E402
from mcp_server.browser import locate, session  # noqa: E402
from pages.dashboard_page import HIDDEN_MENU, LIVE_MENU, ROUTES, DashboardPage  # noqa: E402
from pages.login_page import LoginPage  # noqa: E402
from utils import assertions, data_factory  # noqa: E402
from utils.otp import get_otp  # noqa: E402

mcp = FastMCP(
    "excrow-testing",
    instructions=(
        "Testing tools for the SprintEXcrow / Avanse console (target: BASE_URL in .env). "
        "Start with get_test_config. For API work call api_probe_endpoints first to confirm paths. "
        "For UI work call ui_start (optionally login_as='admin'), then ui_snapshot to see the page "
        "before clicking/filling. Element targets accept label=, placeholder=, button=, link=, text=, "
        "field=, testid= prefixes or any Playwright/CSS selector. Run whole suites with run_tests. "
        "This is a shared UAT environment: avoid creating data unless the test needs it."
    ),
)

Role = Literal["admin", "user", "maker"]
CallerRole = Literal["admin", "user", "maker", "anonymous"]


def _thread(fn, *args, **kwargs):
    return anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


def _goto(page, path: str | None) -> None:
    if path:
        page.goto(path if path.startswith("http") else settings.url(path), wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15000)


def _creds(role: str) -> tuple[str, str]:
    email, password = api_tools.ROLES[role]()
    if not (email and password):
        raise ValueError(f"No credentials for role '{role}' - set {role.upper()}_EMAIL / {role.upper()}_PASSWORD in .env")
    return email, password


# =============================================================== config & data
@mcp.tool()
async def get_test_config() -> dict:
    """Show the active test configuration (targets, endpoints, which credentials are set). Never returns secrets."""
    return {
        "base_url": settings.base_url,
        "api_base_url": settings.api_base_url,
        "credentials_configured": {"admin": settings.has_admin_creds, "user": settings.has_user_creds,
                                   "maker": bool(settings.maker_email and settings.maker_password)},
        "otp_strategy": settings.otp_strategy,
        "browser": settings.browser, "headless": settings.headless,
        "endpoints": vars(settings.endpoints),
        "pytest_markers": runner.MARKERS,
        "ui_menu": {"live": LIVE_MENU, "hidden": HIDDEN_MENU},
        "browser_session": {"running": session.running, "role": session.role},
    }


@mcp.tool()
async def generate_test_data(
    kind: Literal["beneficiary", "user", "role", "valid_password", "invalid_passwords", "ifsc",
                  "invalid_ifsc", "mobile", "invalid_emails", "xss_payloads", "sqli_payloads"],
    count: int = 1,
) -> dict:
    """Generate fresh, unique test data (Faker, en_IN) or the shared negative/attack payload lists."""
    fixed = {"invalid_passwords": [{"case": c, "value": v} for c, v in data_factory.INVALID_PASSWORDS],
             "invalid_ifsc": assertions.INVALID_IFSC, "invalid_emails": assertions.INVALID_EMAILS,
             "xss_payloads": assertions.XSS_PAYLOADS, "sqli_payloads": assertions.SQLI_PAYLOADS}
    if kind in fixed:
        return {"kind": kind, "items": fixed[kind]}
    make = {"beneficiary": data_factory.new_beneficiary, "user": data_factory.new_user,
            "role": data_factory.new_role, "valid_password": data_factory.valid_password,
            "ifsc": data_factory.valid_ifsc, "mobile": data_factory.mobile_10}[kind]
    return {"kind": kind, "items": [make() for _ in range(max(1, min(count, 50)))]}


# ================================================================== test suites
@mcp.tool()
async def list_tests(marker: str | None = None, file: str | None = None, keyword: str | None = None) -> dict:
    """List pytest test IDs. marker is a pytest -m expression (e.g. "smoke", "security and not api");
    file is a path like tests/test_login.py; keyword is a -k expression."""
    return await _thread(runner.list_tests, marker, file, keyword)


@mcp.tool()
async def run_tests(marker: str | None = None, file: str | None = None, keyword: str | None = None,
                    workers: int = 0, headed: bool = False, max_failures: int = 0,
                    reruns: int = 0, timeout_s: int = 1800) -> dict:
    """Run the pytest suites (functional, UI, API, security...) and return a pass/fail summary with
    failure messages and grouped skip reasons. Markers: smoke functional positive negative boundary
    security authorization api ui auth regression. workers>0 runs in parallel (pytest-xdist);
    reruns>0 retries flaky failures. Writes reports/mcp_report.html."""
    return await _thread(runner.run_tests, marker, file, keyword, workers, headed, max_failures,
                         reruns, timeout_s)


@mcp.tool()
async def get_last_test_report() -> dict:
    """Summary of the most recent run_tests execution (from reports/mcp_junit.xml)."""
    if not runner.JUNIT.exists():
        return {"error": "No run yet - call run_tests first."}
    return {**runner.parse_junit(), "html_report": str(runner.HTML)}


# ========================================================================== API
@mcp.tool()
async def api_login(role: Role = "admin") -> dict:
    """Log the API client in as a role using the credentials from .env. The token is kept server-side."""
    return await _thread(api_tools.login, role)


@mcp.tool()
async def api_request(method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], path: str,
                      role: CallerRole = "admin", json_body: dict | list | None = None,
                      params: dict | None = None, headers: dict | None = None,
                      expected_status: int | list[int] | None = None, json_schema: dict | None = None,
                      expect_contains: str | None = None, timeout_s: int = 20) -> dict:
    """Send an API request (path relative to API_BASE_URL, or a full URL) as a role and assert on it.
    Optional checks: expected_status, expect_contains (substring), json_schema (JSON-Schema contract test).
    Returns status, latency, headers and body with secrets redacted. role='anonymous' sends no token."""
    return await _thread(api_tools.request, method, path, role, json_body, params, headers,
                         expected_status, json_schema, expect_contains, timeout_s)


@mcp.tool()
async def api_probe_endpoints() -> dict:
    """GET every configured endpoint anonymously and as admin to see which paths are real (404 = wrong path)."""
    return await _thread(api_tools.probe_endpoints)


@mcp.tool()
async def api_security_scan(path: str, role: Role = "admin", query_param: str = "search") -> dict:
    """OWASP-style checks on one endpoint: unauthenticated + tampered-token rejection, security headers,
    version disclosure, CORS, TRACE, SQLi and reflected-XSS in query_param, stack-trace leakage on a
    malformed body, sensitive fields and unmasked account numbers. Non-destructive payloads only."""
    return await _thread(api_tools.security_scan, path, role, query_param)


@mcp.tool()
async def api_rate_limit_check(path: str | None = None, attempts: int = 25) -> dict:
    """Check that the login endpoint throttles brute force (expects 429). Uses a fake account only; max 50 attempts."""
    return await _thread(api_tools.rate_limit_check, path, attempts)


@mcp.tool()
async def api_performance_test(path: str, method: Literal["GET", "POST", "PUT"] = "GET", role: CallerRole = "admin",
                               total_requests: int = 50, concurrency: int = 5,
                               json_body: dict | list | None = None) -> dict:
    """Small load test: latency min/avg/p50/p90/p95/p99/max, throughput and error rate.
    Capped at 500 requests and 20 concurrent workers to protect the shared UAT server."""
    return await _thread(api_tools.performance_test, path, method, role, total_requests, concurrency, json_body)


# ============================================================= UI - functional
@mcp.tool()
async def ui_start(login_as: Literal["none", "admin", "user", "maker"] = "none", headless: bool | None = None,
                   reuse_saved_session: bool = True, path: str = "/") -> dict:
    """Launch a fresh browser (geolocation granted, en-IN). login_as logs in through the UI; for admin a
    saved session (.auth/admin_state.json, shared with pytest) is reused when still valid.
    headless defaults to HEADLESS from .env - pass false to watch."""
    def go():
        state = settings.storage_state_path if (login_as == "admin" and reuse_saved_session) else None
        session.start(headless=headless, storage_state=state)
        _goto(session.page, path)
        if login_as != "none":
            if state and "login" not in session.page.url.lower():
                session.role = login_as
                return {"status": "ok", "session": "reused saved admin session", **_page_info()}
            return _login(login_as, None)
        return {"status": "ok", **_page_info()}
    return await session.call(go)


def _page_info() -> dict:
    p = session.page
    return {"url": p.url, "title": p.title(), "message": LoginPage(p).error_text() or None}


def _login(role: str, otp: str | None) -> dict:
    email, password = _creds(role)
    page = session.page
    lp = LoginPage(page).open()
    lp.enter_credentials(email, password)
    sent_at = time.time()
    lp.submit()
    if otp is None and settings.otp_strategy.lower() != "manual":
        otp = get_otp(email=email, since=sent_at)
    if otp is None:
        page.wait_for_timeout(1500)
        session.role = f"{role} (pending OTP)"
        return {"status": "otp_required",
                "next": "OTP_STRATEGY=manual: ask the user for the OTP, then call ui_submit_otp(code).",
                **_page_info()}
    return _submit_otp(role, otp)


def _submit_otp(role: str, code: str) -> dict:
    page = session.page
    lp = LoginPage(page)
    try:
        lp.otp_inputs().first.wait_for(timeout=10000)
    except Exception:  # noqa: BLE001 - fall through; enter_otp has a keyboard fallback
        pass
    lp.enter_otp(code)
    lp.verify_button().click()
    page.wait_for_load_state("networkidle", timeout=20000)
    ok = "login" not in page.url.lower() and not lp.otp_inputs().count()
    if ok:
        session.role = role
        if role == "admin":
            Path(settings.storage_state_path).parent.mkdir(parents=True, exist_ok=True)
            session.context.storage_state(path=settings.storage_state_path)
    return {"status": "logged_in" if ok else "login_failed", "role": role, **_page_info()}


@mcp.tool()
async def ui_login(role: Role = "admin", otp: str | None = None) -> dict:
    """Log in through the UI (email + password + OTP) in the current browser. OTP comes from OTP_STRATEGY
    unless passed explicitly. A successful admin login refreshes the session file pytest reuses."""
    return await session.call(_login, role, otp)


@mcp.tool()
async def ui_submit_otp(code: str, role: Role = "admin") -> dict:
    """Complete a login that stopped at the OTP step (OTP_STRATEGY=manual)."""
    return await session.call(_submit_otp, role, code)


@mcp.tool()
async def ui_navigate(path: str) -> dict:
    """Open a path relative to BASE_URL (e.g. /beneficiaries) or a full URL, and wait for the network to settle."""
    def go():
        _goto(session.page, path)
        return _page_info()
    return await session.call(go)


@mcp.tool()
async def ui_snapshot() -> dict:
    """Describe the current page: URL, title, headings, visible interactive elements (with labels,
    disabled/required flags), any toast message and the visible text. Call before interacting."""
    return await session.call(lambda: ux.snapshot(session.page))


@mcp.tool()
async def ui_click(target: str, wait_ms: int = 800) -> dict:
    """Click an element. target: label=, placeholder=, button=, link=, text=, field=, testid= or a CSS/Playwright selector."""
    def go():
        locate(session.page, target).click()
        session.page.wait_for_timeout(wait_ms)
        return {"clicked": target, **_page_info()}
    return await session.call(go)


@mcp.tool()
async def ui_fill(target: str, value: str, press_enter: bool = False) -> dict:
    """Type a value into an input (clears it first). Values for password fields are not echoed back."""
    def go():
        el = locate(session.page, target)
        el.fill(value)
        if press_enter:
            el.press("Enter")
            session.page.wait_for_timeout(800)
        secret = (el.get_attribute("type") or "") == "password"
        return {"filled": target, "value": "***" if secret else value, "url": session.page.url}
    return await session.call(go)


@mcp.tool()
async def ui_select(target: str, option: str) -> dict:
    """Choose an option in a native <select> (by label or value) or a custom dropdown (click, then click option text)."""
    def go():
        page = session.page
        el = locate(page, target)
        if el.evaluate("e => e.tagName") == "SELECT":
            try:
                el.select_option(label=option)
            except Exception:  # noqa: BLE001
                el.select_option(value=option)
        else:
            el.click()
            page.get_by_text(option, exact=False).last.click()
        return {"selected": option, "in": target}
    return await session.call(go)


@mcp.tool()
async def ui_press(key: str, target: str | None = None) -> dict:
    """Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown), optionally focused on a target - useful for keyboard-navigation testing."""
    def go():
        page = session.page
        (locate(page, target).press(key) if target else page.keyboard.press(key))
        page.wait_for_timeout(300)
        focused = page.evaluate("() => { const e = document.activeElement; return e ? "
                                "(e.tagName.toLowerCase() + ' ' + (e.getAttribute('aria-label') || e.innerText || e.name || '')"
                                ".trim().slice(0, 60)) : null; }")
        return {"pressed": key, "focused_element": focused, "url": page.url}
    return await session.call(go)


@mcp.tool()
async def ui_assert(target: str, condition: Literal["visible", "hidden", "enabled", "disabled", "checked",
                                                    "text_contains", "value_equals", "count_at_least",
                                                    "url_contains", "page_contains"],
                    expected: str | None = None, timeout_ms: int = 5000) -> dict:
    """Functional assertion with auto-wait. For url_contains / page_contains the target is ignored
    (pass "page") and expected is the text to look for. count_at_least needs a CSS selector target
    (e.g. "table tbody tr") and expected = minimum count."""
    def go():
        page = session.page
        try:
            if condition == "url_contains":
                page.wait_for_url(lambda u: (expected or "") in u, timeout=timeout_ms)
                actual = page.url
            elif condition == "page_contains":
                page.get_by_text(expected or "", exact=False).first.wait_for(timeout=timeout_ms)
                actual = "found"
            else:
                el = locate(page, target)
                if condition == "hidden":
                    el.wait_for(state="hidden", timeout=timeout_ms)
                    actual = "hidden"
                elif condition == "count_at_least":  # target must be a CSS/Playwright selector here
                    actual = page.locator(target).count()
                    if actual < int(expected or 1):
                        raise AssertionError(f"count {actual} < {expected}")
                else:
                    el.wait_for(state="visible", timeout=timeout_ms)
                    actual = {
                        "visible": lambda: "visible",
                        "enabled": lambda: el.is_enabled(),
                        "disabled": lambda: el.is_disabled(),
                        "checked": lambda: el.is_checked(),
                        "text_contains": lambda: el.inner_text().strip()[:300],
                        "value_equals": lambda: el.input_value(),
                    }[condition]()
                    ok = {"enabled": actual is True, "disabled": actual is True, "checked": actual is True,
                          "text_contains": (expected or "") in str(actual),
                          "value_equals": actual == expected}.get(condition, True)
                    if not ok:
                        raise AssertionError(f"{condition} failed; actual={actual!r}")
            return {"passed": True, "condition": condition, "target": target, "actual": actual}
        except Exception as exc:  # noqa: BLE001
            return {"passed": False, "condition": condition, "target": target, "expected": expected,
                    "reason": str(exc).splitlines()[0][:300], "url": page.url}
    return await session.call(go)


@mcp.tool()
async def ui_screenshot(name: str = "screen", full_page: bool = False, target: str | None = None):
    """Screenshot the page (or one element) - saved under reports/screenshots and returned as an image."""
    def go():
        if target:
            ux.SHOTS.mkdir(parents=True, exist_ok=True)
            path = ux.SHOTS / f"{ux.slug(name)}.png"
            locate(session.page, target).screenshot(path=str(path))
            return path
        return ux.screenshot(session.page, name, full_page)
    path = await session.call(go)
    return [f"Saved {path}", Image(path=str(path))]


@mcp.tool()
async def ui_get_logs(clear: bool = True, errors_only: bool = True) -> dict:
    """Browser console messages/JS errors, failed or 4xx/5xx network calls, and JS dialogs since the last call."""
    def go():
        console = [m for m in session.console if not errors_only or m["type"] in ("error", "pageerror", "warning")]
        out = {"console": console[-100:], "network_errors": list(session.network)[-100:],
               "dialogs": list(session.dialogs)}
        if clear:
            session.console.clear(); session.network.clear(); session.dialogs.clear()
        return out
    return await session.call(go)


@mcp.tool()
async def ui_check_menu_access() -> dict:
    """Role/permission check for the logged-in user: live sidebar modules must be enabled, non-live ones
    disabled, and direct URLs to non-live modules must not render them."""
    def go():
        page = session.page
        _goto(page, "/dashboard")
        dash = DashboardPage(page)
        results = [{"item": i, "expect": "enabled", "passed": dash.is_menu_enabled(i)} for i in LIVE_MENU]
        results += [{"item": i, "expect": "disabled", "passed": not dash.is_menu_enabled(i)} for i in HIDDEN_MENU]
        for item in [m for m in HIDDEN_MENU if m in ROUTES]:
            _goto(page, ROUTES[item])
            body = page.inner_text("body").lower()
            blocked = any(s in body for s in ("cannot open", "not found", "forbidden", "no access",
                                              "unauthor", "access denied"))
            redirected = ROUTES[item].strip("/") not in page.url.lower()
            results.append({"item": item, "expect": f"direct URL {ROUTES[item]} blocked",
                            "passed": blocked or redirected, "landed_on": page.url})
        return {"role": session.role, "passed": sum(r["passed"] for r in results), "total": len(results),
                "failures": [r for r in results if not r["passed"]], "results": results}
    return await session.call(go)


@mcp.tool()
async def ui_close() -> dict:
    """Close the browser."""
    await session.call(session.stop)
    return {"closed": True}


# ====================================================================== UI / UX
@mcp.tool()
async def ux_accessibility_audit(path: str | None = None,
                                 standard: Literal["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] = "wcag21aa") -> dict:
    """WCAG accessibility audit of the current page (or path) with axe-core: violations grouped by impact,
    with the offending elements and fix guidance links."""
    def go():
        _goto(session.page, path)
        return ux.accessibility_audit(session.page, standard)
    return await session.call(go)


@mcp.tool()
async def ux_responsive_check(path: str | None = None, viewports: list[str] | None = None) -> dict:
    """Render the page at mobile/tablet/laptop/desktop (or custom 'WIDTHxHEIGHT') sizes and report horizontal
    overflow, tap targets under 24px and text under 12px. Saves a full-page screenshot per viewport."""
    def go():
        _goto(session.page, path)
        return ux.responsive_check(session.page, viewports)
    return await session.call(go)


@mcp.tool()
async def ux_performance_metrics(path: str | None = None, reload: bool = True) -> dict:
    """Front-end performance: TTFB, FCP, LCP, CLS, load time, page weight, DOM size, largest and slowest
    resources - compared against Core Web Vitals 'good' budgets."""
    def go():
        _goto(session.page, path)
        return ux.performance_metrics(session.page, reload and not path)
    return await session.call(go)


@mcp.tool()
async def ux_broken_links(path: str | None = None, same_origin_only: bool = True, limit: int = 80) -> dict:
    """Find broken links, images, scripts and stylesheets on the page (HTTP >= 400 or unreachable), using the browser's session cookies."""
    def go():
        _goto(session.page, path)
        return ux.broken_links(session.page, same_origin_only, min(limit, 200))
    return await session.call(go)


@mcp.tool()
async def ux_visual_regression(name: str, path: str | None = None, full_page: bool = True,
                               mask: list[str] | None = None, threshold_pct: float = 0.5,
                               update_baseline: bool = False):
    """Visual regression: compare a screenshot with the stored baseline (reports/baselines/<name>.png).
    First run saves the baseline. mask hides dynamic regions (targets, e.g. ['.timestamp']). Returns the
    pixel diff % and a highlighted diff image."""
    def go():
        _goto(session.page, path)
        return ux.visual_compare(session.page, name, full_page, mask, threshold_pct, update_baseline)
    result = await session.call(go)
    if "diff_image" in result:
        return [result, Image(path=result["diff_image"])]
    return result


# ================================================================ UI security
@mcp.tool()
async def ui_security_scan(path: str | None = None) -> dict:
    """Client-side security checks on the logged-in app: HTTPS, session-cookie flags, secrets/JWTs/account
    numbers in local/session storage, secrets in console output, mixed content, insecure password forms."""
    def go():
        _goto(session.page, path)
        return ux.ui_security_scan(session.page, list(session.console))
    return await session.call(go)


@mcp.tool()
async def ui_input_probe(field: str, preset: Literal["xss", "sqli", "invalid_email", "invalid_ifsc",
                                                     "invalid_mobile", "boundary_length", "custom"] = "custom",
                         values: list[str] | None = None, submit: str | None = None,
                         reload_between: bool = False) -> dict:
    """Negative / boundary / injection testing of one form field: enter each value, submit, and report whether
    the app showed a validation error, toast, navigated, or fired a script dialog (= XSS executed).
    Use preset lists or pass custom values. submit is the button target (default: press Enter)."""
    presets = {
        "xss": assertions.XSS_PAYLOADS, "sqli": assertions.SQLI_PAYLOADS,
        "invalid_email": assertions.INVALID_EMAILS, "invalid_ifsc": assertions.INVALID_IFSC,
        "invalid_mobile": ["98765", "98765432101", "abcd012345", "0000000000", "+91 98765"],
        "boundary_length": ["", " ", "a", "a" * 50, "a" * 255, "a" * 256, "a" * 1000],
    }
    vals = values if preset == "custom" else presets[preset] + (values or [])
    if not vals:
        raise ValueError("Pass values, or choose a preset.")
    return await session.call(lambda: ux.input_probe(session.page, field, vals, submit, session.dialogs,
                                                     reload_between))


# ===================================================================== prompts
@mcp.prompt()
def full_test_pass(module: str = "all live modules") -> str:
    """A complete multi-type test pass over the app."""
    return f"""Run a complete test pass of the SprintEXcrow console for: {module}.
1. get_test_config, then api_probe_endpoints - note which endpoints are real.
2. run_tests(marker="smoke") - stop and report if the critical path is broken.
3. API: for each real endpoint run api_security_scan; run api_performance_test on the main list endpoints
   (50 requests, concurrency 5); api_rate_limit_check once.
4. Functional UI: ui_start(login_as="admin"), ui_check_menu_access, then for each module page use ui_snapshot
   and ui_assert to verify it loads and its key controls exist.
5. UI/UX on each module page: ux_accessibility_audit, ux_responsive_check, ux_performance_metrics,
   ux_broken_links, ux_visual_regression (name = module).
6. Security: ui_security_scan; ui_input_probe with preset xss on free-text form fields.
7. run_tests(marker="regression or functional or security", workers=4).
Finish with a report table: area | checks run | passed | failed | key defects (with severity and evidence)."""


@mcp.prompt()
def exploratory_ui_test(path: str = "/dashboard") -> str:
    """Exploratory functional + UX session on one page."""
    return f"""Do an exploratory test of {path}. ui_start(login_as="admin", path="{path}"), then ui_snapshot.
For each form: try a valid submit, empty required fields, boundary lengths and invalid formats with
ui_input_probe; check keyboard-only navigation with ui_press("Tab"); check ui_get_logs for JS errors after
each action. Run ux_accessibility_audit and ux_responsive_check. Report each defect with steps to reproduce,
expected vs actual, severity, and a ui_screenshot."""


if __name__ == "__main__":
    mcp.run("streamable-http" if "--http" in sys.argv else "stdio")
