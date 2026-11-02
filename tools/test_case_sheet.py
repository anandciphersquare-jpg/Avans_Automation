"""
Write the manual-style test case sheet (Excel) from the test code, the plain
English details in docs/test_case_details/*.json, and the latest real result of
every test in reports/runs/*/json/results.json.

    python tools/test_case_sheet.py

Columns: Test Case ID | Module | Feature / Sub-Module | Test Scenario | Test Type |
Priority | Severity | Preconditions | Test Steps | Test Data | Expected Result |
Actual Result | Status | Notes

One row per test case ID. A case that runs with several data sets (variants)
is Fail when any variant failed, and the Actual Result names the failed ones.
Each run writes a new timestamped file; earlier sheets are never overwritten.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
DETAILS_DIR = ROOT / "docs" / "test_case_details"
RUNS_DIR = ROOT / "reports" / "runs"

# test file -> module name in plain English
MODULES = OrderedDict([
    ("test_login.py", "Login (Sign-in, OTP & Session)"),
    ("test_00_forgot_password.py", "Forgot Password"),
    ("test_change_password_signout.py", "Change Password & Sign Out"),
    ("test_auth_api.py", "Login API (Back-end)"),
    ("test_beneficiary.py", "Beneficiary (Add & List screen)"),
    ("test_beneficiary_api.py", "Beneficiary API (Back-end)"),
    ("test_api_security.py", "API Security (all modules)"),
    ("test_security.py", "Screen Security (all modules)"),
    ("test_dashboard.py", "Dashboard"),
    ("test_user_management.py", "User Management"),
    ("test_transfers.py", "Transfers"),
    ("test_audit_trail.py", "Audit Trail"),
])
PENDING_DEV = {"test_dashboard.py", "test_user_management.py"}

COLUMNS = ["Test Case ID", "Module", "Feature / Sub-Module", "Test Scenario", "Test Type",
           "Priority", "Severity", "Preconditions", "Test Steps", "Test Data",
           "Expected Result", "Actual Result", "Status", "Notes"]
WIDTHS = [14, 22, 28, 40, 13, 10, 11, 32, 55, 34, 42, 46, 12, 46]

GENERIC_PASS = "Behaved as expected - all assertions passed."

# primary test type -> default priority / severity when the details file has none
DEFAULTS = {"Security": ("High", "Critical"), "Smoke": ("High", "Critical"),
            "Negative": ("Medium", "Major"), "Boundary": ("Medium", "Major"),
            "API": ("High", "Major"), "Positive": ("High", "Major"),
            "Functional": ("Medium", "Major"), "UI/UX": ("Low", "Minor")}


class _Collector:
    def __init__(self):
        self.items: list[dict] = []

    def pytest_collection_modifyitems(self, items):
        from reporting import metadata as md
        for item in items:
            doc = " ".join((item.function.__doc__ or "").split())
            title = doc.split("—", 1)[-1].strip() if "—" in doc else doc
            self.items.append({
                "nodeid": item.nodeid, "file": Path(str(item.fspath)).name,
                "id": md.test_id(item)[0], "func": item.originalname, "title": title,
                "types": md.test_types(item)[1], "variant": md._param_id(item) or "",
            })


def _latest_results() -> dict[str, dict]:
    """nodeid -> latest result record (runs are named by start time, so sorted = oldest first)."""
    latest: dict[str, dict] = {}
    for f in sorted(glob.glob(str(RUNS_DIR / "*" / "json" / "results.json"))):
        run = os.path.basename(os.path.dirname(os.path.dirname(f)))
        try:
            tests = json.load(open(f, encoding="utf-8"))["tests"]
        except (OSError, ValueError, KeyError):
            continue
        for t in tests:
            t["_run"] = run
            latest[t["nodeid"]] = t
    return latest


def _details() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(DETAILS_DIR.glob("*.json")):
        for key, val in json.load(open(f, encoding="utf-8")).items():
            out[f"{f.stem}.py::{key}"] = val
    return out


def _run_time(run: str) -> str:
    try:
        return datetime.strptime(run[:15], "%Y%m%d-%H%M%S").strftime("%d-%b-%Y %H:%M")
    except ValueError:
        return run


def _status(results: list[dict], pending: bool) -> str:
    states = [r["status"] if r else "NOT RUN" for r in results]
    if "FAIL" in states:
        return "Fail"
    if "BLOCKED" in states:
        return "Blocked"
    if "PASS" in states:
        return "Pass"
    if "NOT RUN" in states:
        return "Not Run"
    return "Pending" if pending else "Skipped"


def _short(text: str, limit: int = 400) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


_CHECK_LINE = re.compile(r"^E\s+(Actual|Hint)\s*:\s*(.+)$", re.M)


def _failure_actual(r: dict) -> tuple[str, str]:
    """(actual, hint) of a failed test. check()/expect_api() failures keep the real
    'Actual :' line only in the stack trace; the 'actual' field holds just the title."""
    found = dict(_CHECK_LINE.findall(r.get("stack_trace") or ""))
    actual = found.get("Actual") or r.get("actual") or r.get("failure_reason") or "Check failed"
    return actual.strip(), found.get("Hint", "").strip()


def _actual_and_notes(runs: list[tuple[str, dict | None]], status: str, pending: bool) -> tuple[str, str]:
    notes: list[str] = []
    done = [r for _, r in runs if r]
    if done:
        last = max(r["_run"] for r in done)
        notes.append(f"Last run: {_run_time(last)} (run {last})")
    multi = len(runs) > 1
    if status == "Fail":
        lines, verdicts, hints = [], set(), []
        for variant, r in runs:
            if r and r["status"] == "FAIL":
                actual, hint = _failure_actual(r)
                msg = _short(actual, 300)
                lines.append(f"[{variant}] {msg}" if multi else msg)
                verdicts.add((r.get("qa") or {}).get("verdict", ""))
                if hint and hint not in hints:
                    hints.append(hint)
        passed = sum(1 for _, r in runs if r and r["status"] == "PASS")
        if multi:
            lines.insert(0, f"{len(lines)} of {len(runs)} data sets failed ({passed} passed):")
        if pending:
            notes.append("Module is still under development, so this is pending, not a defect.")
        elif verdicts - {""}:
            notes.append("QA verdict: " + ", ".join(sorted(verdicts - {""})))
        notes += [f"Hint: {_short(h, 300)}" for h in hints]
        return "\n".join(lines), "\n".join(notes)
    if status == "Pass":
        skipped = [v for v, r in runs if r and r["status"] == "SKIPPED"]
        if multi:
            actual = f"All {len(runs) - len(skipped)} data sets behaved as expected."
        else:
            a = done[0].get("actual", "")
            actual = "Behaved as expected." if not a or a == GENERIC_PASS else _short(a)
        if skipped:
            notes.append(f"Skipped data sets: {', '.join(skipped)}")
        return actual, "\n".join(notes)
    if status in ("Skipped", "Pending"):
        reasons = {_short(r.get("skip_reason", ""), 200) for r in done if r.get("skip_reason")}
        actual = "Not executed - " + ("; ".join(sorted(reasons)) if reasons else "skipped")
        if pending:
            notes.append("Module is still under development (pending, not a defect).")
        return actual, "\n".join(notes)
    if status == "Blocked":
        reasons = {_short(r.get("failure_reason", ""), 200) for r in done}
        return "Blocked - " + "; ".join(sorted(reasons)), "\n".join(notes)
    return "Not executed yet.", "\n".join(notes)


def build_rows() -> list[dict]:
    col = _Collector()
    code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", str(ROOT / "tests")], plugins=[col])
    if code not in (0, 5):
        raise SystemExit(code)
    latest, details = _latest_results(), _details()

    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for it in col.items:
        groups.setdefault((it["file"], it["id"]), []).append(it)

    order = {f: i for i, f in enumerate(MODULES)}
    keys = sorted(groups, key=lambda k: order.get(k[0], len(order)))
    rows = []
    for file, tid in keys:
        items = groups[(file, tid)]
        first = items[0]
        func = first["func"]
        # two functions sharing one ID: label their runs by function so the Actual Result stays clear
        if len({it["func"] for it in items}) > 1:
            for it in items:
                it["variant"] = "/".join(filter(None, [it["func"], it["variant"]]))
        stem = Path(file).stem
        d = details.get(f"{stem}.py::{tid}") or details.get(f"{stem}.py::FUNC:{func}") or {}
        ttype = d.get("test_type") or (first["types"][0] if first["types"] else "Functional")
        prio, sev = DEFAULTS.get(ttype, ("Medium", "Major"))
        runs = [(it["variant"] or "-", latest.get(it["nodeid"])) for it in items]
        pending = file in PENDING_DEV
        status = _status([r for _, r in runs], pending)
        actual, notes = _actual_and_notes(runs, status, pending)
        steps = d.get("steps") or [first["title"]]
        variants = [it["variant"] for it in items if it["variant"]]
        test_data = d.get("test_data") or (("Variants: " + "; ".join(variants)) if variants else "N/A")
        rows.append({
            "Test Case ID": tid,
            "Module": MODULES.get(file, file),
            "Feature / Sub-Module": d.get("sub_module") or (latest.get(first["nodeid"]) or {}).get("feature", ""),
            "Test Scenario": d.get("scenario") or first["title"],
            "Test Type": ttype,
            "Priority": d.get("priority") or prio,
            "Severity": d.get("severity") or sev,
            "Preconditions": d.get("preconditions", ""),
            "Test Steps": "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)),
            "Test Data": test_data,
            "Expected Result": d.get("expected") or first["title"],
            "Actual Result": actual,
            "Status": status,
            "Notes": notes,
            "_detailed": bool(d),
        })
    return rows


def _fmt_value(v) -> str:
    if v is None or v == "":
        return "(empty)"
    if isinstance(v, str) and not v.strip():
        return f"(spaces only, {len(v)})"
    if isinstance(v, str) and len(v) > 80:
        return f"{v[:60]}… ({len(v)} characters)"
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _variant(nodeid: str) -> str:
    if not nodeid.endswith("]") or "[" not in nodeid:
        return ""
    parts = nodeid[nodeid.index("[") + 1:-1].split("-")
    return "-".join(p for p in parts if p not in ("chromium", "firefox", "webkit"))


def build_rows_for_run(run: str) -> list[dict]:
    """One row per test executed in one report run, with that run's result."""
    f = RUNS_DIR / run / "json" / "results.json"
    tests = json.load(open(f, encoding="utf-8"))["tests"]
    details = _details()
    later = {}  # nodeid -> latest result from a run after this one
    for g in sorted(glob.glob(str(RUNS_DIR / "*" / "json" / "results.json"))):
        r_id = os.path.basename(os.path.dirname(os.path.dirname(g)))
        if r_id > run:
            for t in json.load(open(g, encoding="utf-8"))["tests"]:
                t["_run"] = r_id
                later[t["nodeid"]] = t

    order = {name: i for i, name in enumerate(MODULES)}
    tests.sort(key=lambda t: (order.get(Path(t["file"]).name, len(order)), t.get("line", 0), t["nodeid"]))
    count: dict[str, int] = {}
    totals: dict[str, int] = {}
    for t in tests:
        totals[t["test_id"]] = totals.get(t["test_id"], 0) + 1

    rows = []
    for t in tests:
        t["_run"] = run
        file = Path(t["file"]).name
        stem = Path(file).stem
        tid = t["test_id"]
        d = details.get(f"{stem}.py::{tid}") or details.get(f"{stem}.py::FUNC:{t['function']}") or {}
        variant = _variant(t["nodeid"])
        row_id = tid
        if totals[tid] > 1:
            count[tid] = count.get(tid, 0) + 1
            row_id = f"{tid}.{count[tid]}"

        pending = file in PENDING_DEV
        status = _status([t], pending)
        actual, notes = _actual_and_notes([(variant or "-", t)], status, pending)

        data_lines = [f"Data set: {variant}"] if variant else []
        data_lines += [f"{k}: {_fmt_value(v)}" for k, v in (t.get("test_data") or {}).items()]
        test_data = "\n".join(data_lines) if data_lines else (d.get("test_data") or "N/A")

        if status == "Fail":
            nxt = later.get(t["nodeid"])
            if nxt and nxt["status"] != "FAIL":
                notes += (f"\nRe-run {_run_time(nxt['_run'])} (run {nxt['_run']}): "
                          f"{'Pass' if nxt['status'] == 'PASS' else nxt['status'].title()} "
                          "- the failure was in the test, which was corrected.")
        ttype = d.get("test_type") or t.get("test_type") or "Functional"
        prio, sev = DEFAULTS.get(ttype, ("Medium", "Major"))
        scenario = d.get("scenario") or t.get("name", "")
        steps = d.get("steps") or [t.get("expected", "")]
        rows.append({
            "Test Case ID": row_id,
            "Module": MODULES.get(file, file),
            "Feature / Sub-Module": d.get("sub_module") or t.get("feature", ""),
            "Test Scenario": f"{scenario} (data set: {variant})" if variant else scenario,
            "Test Type": ttype,
            "Priority": d.get("priority") or prio,
            "Severity": d.get("severity") or sev,
            "Preconditions": d.get("preconditions") or "; ".join(t.get("preconditions") or []),
            "Test Steps": "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)),
            "Test Data": test_data,
            "Expected Result": d.get("expected") or t.get("expected", ""),
            "Actual Result": actual,
            "Status": status,
            "Notes": notes,
            "_detailed": bool(d),
        })
    return rows


STATUS_FILL = {"Pass": "C6EFCE", "Fail": "FFC7CE", "Skipped": "FFEB9C", "Pending": "DDEBF7",
               "Blocked": "F4B084", "Not Run": "E7E6E6"}
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def _header(ws, cols, widths):
    ws.append(cols)
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill, c.border = Font(bold=True, color="FFFFFF"), HEADER_FILL, BORDER
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B2"


def write_xlsx(rows: list[dict], out: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    _header(ws, COLUMNS, WIDTHS)
    status_col = COLUMNS.index("Status") + 1
    for r in rows:
        ws.append([r[c] for c in COLUMNS])
        for cell in ws[ws.max_row]:
            cell.alignment, cell.border = WRAP, BORDER
        sc = ws.cell(row=ws.max_row, column=status_col)
        sc.fill = PatternFill("solid", fgColor=STATUS_FILL.get(r["Status"], "FFFFFF"))
        sc.font = Font(bold=True)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{ws.max_row}"

    # summary per module
    sm = wb.create_sheet("Summary")
    states = ["Pass", "Fail", "Skipped", "Pending", "Blocked", "Not Run"]
    _header(sm, ["Module", "Total", *states], [34, 9] + [10] * len(states))
    per: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        per.setdefault(r["Module"], {s: 0 for s in states})[r["Status"]] += 1
    for mod, counts in per.items():
        sm.append([mod, sum(counts.values()), *[counts[s] for s in states]])
    sm.append(["Total", len(rows), *[sum(c[s] for c in per.values()) for s in states]])
    for row in sm.iter_rows(min_row=2):
        for cell in row:
            cell.border = BORDER
    for cell in sm[sm.max_row]:
        cell.font = Font(bold=True)
    sm.append([])
    sm.append([f"Generated {datetime.now():%d-%b-%Y %H:%M} from the latest result of each test in reports/runs."])
    sm.append(["Fail = at least one data set failed. Pending = module still under development."])
    wb.move_sheet("Summary", offset=-1)
    wb.active = 0
    wb.save(out)


def main() -> int:
    rows = build_rows()
    out = ROOT / "reports" / f"Test_Cases_{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    write_xlsx(rows, out)
    missing = [r["Test Case ID"] for r in rows if not r["_detailed"]]
    counts = {s: sum(1 for r in rows if r["Status"] == s) for s in STATUS_FILL}
    print(f"Wrote {out}: {len(rows)} test cases {counts}")
    if missing:
        print(f"{len(missing)} cases have no plain-English details yet: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
