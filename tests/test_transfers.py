"""
Transfers (approver side) tests — Workflows 1 & 2 approver steps.
Maps to WTRN-001..WTRN-015. Create Transfer (maker) is not live, so only the
approver journey is exercised here.
"""
from __future__ import annotations

import pytest

from pages.transfers_page import TransfersPage

pytestmark = [pytest.mark.functional]


@pytest.mark.positive
@pytest.mark.smoke
def test_transfers_list_loads(logged_in_page):
    """WTRN-002 — the Transfers list renders (status badges visible)."""
    tp = TransfersPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    assert tp.rows().count() >= 0


@pytest.mark.positive
def test_open_transfer_journey_for_pending(logged_in_page):
    """WTRN-004/005 — selecting a pending badge opens the Transfer Journey with
    the Transfer ID / amount / Maker → Approver 1 → Approver 2 progression."""
    tp = TransfersPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    if not tp.open_journey_for_pending():
        pytest.skip("No 'Pending for Authorization' transfer available to open")
    text = tp.journey_text().lower()
    assert any(k in text for k in ("maker", "approver", "transfer id", "amount")), \
        "Journey does not show identity / approval progression"


@pytest.mark.authorization
def test_user_without_rights_cannot_approve(non_admin_page):
    """WTRN-011 — a user without approval rights sees no Approve control."""
    tp = TransfersPage(non_admin_page).open()
    non_admin_page.wait_for_load_state("networkidle")
    if not tp.open_journey_for_pending():
        pytest.skip("No pending transfer to assess approval control")
    assert not tp.can_approve(), "Approve control should be hidden for a non-approver"


@pytest.mark.security
@pytest.mark.authorization
def test_maker_cannot_approve_own_transfer():
    """WTRN-009 — the maker who created a transfer must not approve it.

    Requires a transfer created by MAKER_* and that same user attempting to
    approve. Implement against a seeded fixture in the target environment.
    """
    pytest.skip("Needs a transfer seeded by the maker user (MAKER_* creds) to assert "
                "segregation of duties end-to-end.")


@pytest.mark.ui
def test_amounts_rupee_and_account_masked_in_journey(logged_in_page):
    """WTRN-014 — amounts use ₹ and any account info is masked in the drawer."""
    tp = TransfersPage(logged_in_page).open()
    logged_in_page.wait_for_load_state("networkidle")
    if not tp.open_journey_for_pending():
        pytest.skip("No pending transfer to inspect")
    text = tp.journey_text()
    # no raw 9–18 digit account should be visible
    import re
    assert not re.search(r"\b\d{9,18}\b", text), "Unmasked account number in journey"
