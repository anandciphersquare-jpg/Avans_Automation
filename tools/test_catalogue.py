"""
Write docs/TEST_CASES.md: every test case with its id, title, type and
variants, grouped by module — generated from the test code, so it never drifts.

    python tools/test_catalogue.py
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "TEST_CASES.md"

MODULES = OrderedDict([
    ("test_login.py", "Authentication & Session — UI (sign-in, location, OTP, session, forgot password)"),
    ("test_change_password_signout.py", "Authentication & Session — UI (change password, sign out)"),
    ("test_00_forgot_password.py", "Authentication & Session — UI (password reset by mail)"),
    ("test_auth_api.py", "Authentication & Session — API"),
    ("test_beneficiary.py", "Add Beneficiary / Beneficiary List — UI"),
    ("test_beneficiary_api.py", "Beneficiary — API"),
    ("test_api_security.py", "API security — cross-module"),
    ("test_security.py", "UI security — cross-module"),
    ("test_dashboard.py", "Dashboard (pending development)"),
    ("test_user_management.py", "User Management (pending development)"),
    ("test_transfers.py", "Transfers"),
    ("test_audit_trail.py", "Audit Trail"),
])


class _Collector:
    def __init__(self):
        self.rows: "OrderedDict[tuple, dict]" = OrderedDict()

    def pytest_collection_modifyitems(self, items):
        from reporting import metadata as md
        for item in items:
            tid, auto = md.test_id(item)
            doc = (item.function.__doc__ or "").strip()
            title = doc.split("—", 1)[-1].strip() if "—" in doc else doc
            title = " ".join(title.split())
            key = (Path(str(item.fspath)).name, tid, item.originalname)
            row = self.rows.setdefault(key, {"id": tid, "auto": auto, "title": title,
                                             "types": md.test_types(item)[1], "variants": []})
            param = md._param_id(item)
            if param:
                row["variants"].append(param)


def main() -> int:
    col = _Collector()
    code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", str(ROOT / "tests")], plugins=[col])
    if code not in (0, 5):
        return code
    by_mod: dict[str, list] = {}
    for (mod, _, _), row in col.rows.items():
        by_mod.setdefault(mod, []).append(row)
    total_cases = sum(len(r["variants"]) or 1 for rows in by_mod.values() for r in rows)
    lines = ["# SprintEXcrow — Test case catalogue", "",
             f"Generated from the test code by `python tools/test_catalogue.py`. "
             f"{sum(len(v) for v in by_mod.values())} test cases, {total_cases} executions (variants included).",
             "", "The **ID** is what the execution report and every failure message show "
             "(`[AUTH-API-005] …`). *Variants* are the data sets one case runs with.", ""]
    for mod in list(MODULES) + sorted(set(by_mod) - set(MODULES)):
        rows = by_mod.get(mod)
        if not rows:
            continue
        lines += [f"## {MODULES.get(mod, mod)}", "", f"`tests/{mod}`", "",
                  "| ID | Test case | Type | Variants |", "|---|---|---|---|"]
        for r in rows:
            variants = ", ".join(r["variants"]) if r["variants"] else "—"
            title = r["title"].replace("|", "\\|")
            lines.append(f"| {r['id']} | {title} | {', '.join(r['types'])} | {variants.replace('|', '/')} |")
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({total_cases} executions)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
