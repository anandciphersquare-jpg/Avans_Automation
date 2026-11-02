"""
Execution-report demo - shows every report feature without touching UAT.

A tiny local HTTP server plays the application, so this runs anywhere
(laptop or CI) in a few seconds. Some tests FAIL ON PURPOSE so the report
has screenshots, traces, videos, console errors and retries to show.

    pytest examples/test_reporting_demo.py --reruns 1
    # then open the newest reports/Test_Report_<run_id>.html

It is outside tests/, so the normal `pytest` run never picks it up.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from api.api_client import ApiClient
from reporting import step

REPORT_MODULE = "Reporting Demo"

_PAGE = """<!doctype html><html><head><title>Demo Shop</title>
<style>body{font:16px system-ui;margin:40px} .total{font-weight:700}</style></head>
<body>
  <h1>Demo Shop</h1>
  <form id="login"><label>Email <input name="email" aria-label="Email"></label>
  <label>Password <input name="password" type="password" aria-label="Password"></label>
  <button type="submit">Sign in</button></form>
  <p>Cart total: <span class="total" id="total">₹ 1,180.00</span></p>
  <img src="/missing-logo.png" alt="logo">
  <script>
    fetch('/api/items').then(r => r.json()).then(d => document.title = 'Demo Shop (' + d.items.length + ')');
    fetch('/api/broken');
    console.error('PaymentWidget: failed to initialise (demo console error)');
    document.getElementById('login').addEventListener('submit', e => {
      e.preventDefault();
      fetch('/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: e.target.email.value, password: e.target.password.value})});
    });
  </script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/":
            self._send(200, _PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/items":
            self._send(200, json.dumps({"items": [{"id": 1, "name": "Pen"}, {"id": 2, "name": "Ink"}]}))
        elif self.path == "/api/broken":
            self._send(500, json.dumps({"error": "upstream timeout"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/api/login":
            self._send(200, json.dumps({"token": "demo-token-123", "user": {"role": "admin"}}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture(scope="module")
def app_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


# --------------------------------------------------------------------- login
@pytest.mark.smoke
@pytest.mark.meta(id="DEMO-001", feature="Login", preconditions=["Demo app is running"],
                  expected="Login form shows Email, Password and Sign in")
def test_login_form_is_displayed(page, app_url, report):
    """DEMO-001 — the login form renders with all fields."""
    with report.step("Open the home page"):
        page.goto(app_url)
    with report.step("Check the login form fields"):
        assert page.get_by_label("Email").is_visible()
        assert page.get_by_label("Password").is_visible()
        assert page.get_by_role("button", name="Sign in").is_visible()
    report.actual("Email, Password and Sign in are visible")


@pytest.mark.functional
@pytest.mark.meta(feature="Login")
def test_sign_in_posts_credentials(page, app_url, report):
    """DEMO-002 — Sign in sends the credentials to /api/login (password redacted in the report)."""
    report.data(email="qa.user@example.com", password="Secret@123")
    with report.step("Open the home page"):
        page.goto(app_url)
    with report.step("Fill credentials and submit"):
        page.get_by_label("Email").fill("qa.user@example.com")
        page.get_by_label("Password").fill("Secret@123")
        with page.expect_response("**/api/login") as resp:
            page.get_by_role("button", name="Sign in").click()
    assert resp.value.status == 200


# --------------------------------------------------------------------- cart
@pytest.mark.functional
@pytest.mark.regression
@pytest.mark.meta(feature="Cart", expected="Cart total is ₹ 1,200.00 (2 items incl. tax)")
def test_cart_total_matches_order(page, app_url, report):
    """DEMO-003 — the cart total matches the order value. FAILS ON PURPOSE (screenshot, trace, video)."""
    with report.step("Open the cart"):
        page.goto(app_url)
    with report.step("Read the displayed total"):
        total = page.locator("#total").inner_text()
    with report.step("Compare with the expected order value"):
        assert total == "₹ 1,200.00", f"Cart total is {total}, expected ₹ 1,200.00"


@pytest.mark.ui
def test_promo_banner_visible(page, app_url):
    """DEMO-004 — the promo banner is shown on the home page.
    FAILS ON PURPOSE with a timeout; no report.step() calls, so steps come from the source."""
    page.goto(app_url)
    heading = page.locator("h1").inner_text()
    assert heading == "Demo Shop"
    page.click("#promo-banner", timeout=1500)
    assert page.locator("#promo-banner").is_visible()


@pytest.mark.boundary
@pytest.mark.meta(feature="Cart")
@pytest.mark.parametrize("qty,accepted", [(1, True), (99, True), (0, False), (100, False)])
def test_quantity_limits(qty, accepted):
    """DEMO-005 — quantity must be between 1 and 99."""
    assert (1 <= qty <= 99) is accepted


# --------------------------------------------------------------------- API
@pytest.mark.api
@pytest.mark.meta(feature="Catalogue API")
def test_items_api_contract(app_url, report):
    """DEMO-006 — GET /api/items returns a list of items with id + name."""
    api = ApiClient(base_url=app_url)
    with report.step("GET /api/items"):
        r = api.get("/api/items")
    with report.step("Validate the response schema"):
        assert r.status_code == 200
        items = r.json()["items"]
        assert items and all({"id", "name"} <= set(i) for i in items)


@pytest.mark.api
@pytest.mark.security
@pytest.mark.meta(feature="Auth API")
def test_login_api_token_is_redacted_in_logs(app_url):
    """DEMO-007 — the login API returns a token; the report shows it redacted."""
    r = ApiClient(base_url=app_url).post("/api/login", json={"email": "a@b.co", "password": "x"}, auth=False)
    assert r.json().get("token")


# --------------------------------------------------------------------- skip / blocked / flaky
@pytest.mark.functional
@pytest.mark.skip(reason="Refunds module is not live in this build")
def test_refund_flow():
    """DEMO-008 — refund an order."""


@pytest.fixture
def payment_gateway():
    raise ConnectionError("Payment sandbox unreachable: getaddrinfo failed for sandbox.pay.example")


@pytest.mark.integration
@pytest.mark.meta(feature="Payments")
def test_pay_by_upi(payment_gateway):
    """DEMO-009 — pay by UPI. BLOCKED ON PURPOSE: its fixture cannot reach the sandbox."""


_attempts = {"n": 0}


@pytest.mark.functional
@pytest.mark.flaky(reruns=2)
@pytest.mark.meta(feature="Search")
def test_search_suggestions_flaky():
    """DEMO-010 — search suggestions appear. Fails on the first attempt, passes on the retry (flaky)."""
    _attempts["n"] += 1
    with step("Wait for suggestions"):
        assert _attempts["n"] > 1, "Suggestions did not load in time (simulated flake)"
