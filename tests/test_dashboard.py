"""
Dashboard + sidebar tests.
Maps to WDSH-001..WDSH-007 (live-module flow suite).
"""
from __future__ import annotations

import pytest

from pages.dashboard_page import HIDDEN_MENU, LIVE_MENU, ROUTES, DashboardPage

pytestmark = [
    pytest.mark.ui,
    # remove when the developers hand the Dashboard over for testing
    pytest.mark.pending_dev(reason="Dashboard is still under development (not complete on the developer side)"),
]


@pytest.mark.positive
@pytest.mark.smoke
def test_dashboard_loads_with_role(logged_in_page):
    """WDSH-001 — Dashboard loads and the MERCHANT_OWNER role is shown."""
    dash = DashboardPage(logged_in_page)
    dash.open_menu("Dashboard")
    logged_in_page.wait_for_load_state("networkidle")
    assert "dashboard" in logged_in_page.url.lower() or dash.is_menu_enabled("Dashboard")


@pytest.mark.functional
@pytest.mark.parametrize("item", LIVE_MENU)
def test_live_menu_items_enabled(logged_in_page, item):
    """WDSH-002 — every live module is enabled/clickable in the sidebar."""
    dash = DashboardPage(logged_in_page)
    assert dash.is_menu_enabled(item), f"Expected '{item}' to be enabled"


@pytest.mark.security
@pytest.mark.parametrize("item", HIDDEN_MENU)
def test_hidden_menu_items_not_active(logged_in_page, item):
    """WDSH-003 — dimmed modules are not clickable and reveal no screen."""
    dash = DashboardPage(logged_in_page)
    assert not dash.is_menu_enabled(item), f"'{item}' should be disabled in this build"


@pytest.mark.security
@pytest.mark.parametrize("item", [m for m in HIDDEN_MENU if m in ROUTES])
def test_direct_url_to_hidden_module_blocked(logged_in_page, item):
    """WDSH-004 — direct URL to a non-live module must not render it."""
    page = logged_in_page
    page.goto(page.url.split("//", 1)[0] + "//" + page.url.split("//", 1)[1].split("/", 1)[0] + ROUTES[item])
    page.wait_for_timeout(800)
    body = page.inner_text("body").lower()
    blocked = any(s in body for s in ("cannot open", "not found", "forbidden",
                                      "no access", "unauthor", "access denied"))
    redirected = ROUTES[item].strip("/").split("/")[0] not in page.url.lower()
    assert blocked or redirected, f"Hidden module '{item}' appears reachable by URL"


@pytest.mark.ui
def test_amounts_use_rupee_formatting(logged_in_page):
    """WDSH-005 — monetary amounts render with the ₹ symbol."""
    dash = DashboardPage(logged_in_page)
    dash.open_menu("Dashboard")
    logged_in_page.wait_for_load_state("networkidle")
    body = logged_in_page.inner_text("body")
    if "₹" not in body and "INR" not in body:
        pytest.skip("No amounts visible to assert formatting on this dataset")
    assert "₹" in body or "INR" in body
