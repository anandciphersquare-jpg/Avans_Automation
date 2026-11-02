"""
Write the test case sheet (Excel) for ONE execution report: one row per test
executed in that run (data-set variants included), with that run's Actual
Result and Status. Same columns as tools/test_case_sheet.py.

    python tools/report_test_cases.py 20261021-154453_6-modules
    python tools/report_test_cases.py              # newest run in reports/runs

Output: reports/Report_Test_Cases_<run>__<timestamp>.xlsx (never overwritten).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.test_case_sheet import (RUNS_DIR, STATUS_FILL, _run_time,  # noqa: E402
                                   build_rows_for_run, write_xlsx)


def _set_summary_note(path: Path, run: str) -> None:
    """The shared writer's summary note describes the latest-result sheet; say which run this one is."""
    from openpyxl import load_workbook
    wb = load_workbook(path)
    for row in wb["Summary"].iter_rows():
        cell = row[0]
        if isinstance(cell.value, str) and cell.value.startswith("Generated "):
            cell.value = (f"Generated {datetime.now():%d-%b-%Y %H:%M} from execution report {run} "
                          f"({_run_time(run)}). Status = result in that run.")
        elif isinstance(cell.value, str) and cell.value.startswith("Fail = "):
            cell.value = "One row per executed test (data sets numbered .1, .2 …). Notes show a later re-run when it passed."
    wb.save(path)


def main() -> int:
    runs = sorted(p.parent.parent.name for p in RUNS_DIR.glob("*/json/results.json"))
    run = sys.argv[1] if len(sys.argv) > 1 else (runs[-1] if runs else "")
    if run not in runs:
        print(f"No results.json for run {run!r} in {RUNS_DIR}. Available: {', '.join(runs[-8:])}")
        return 2
    rows = build_rows_for_run(run)
    out = ROOT / "reports" / f"Report_Test_Cases_{run}__{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    write_xlsx(rows, out)
    _set_summary_note(out, run)
    counts = {s: sum(1 for r in rows if r["Status"] == s) for s in STATUS_FILL}
    print(f"Wrote {out}: {len(rows)} tests {counts}")
    missing = sorted({r["Test Case ID"].split(".")[0] for r in rows if not r["_detailed"]})
    if missing:
        print(f"{len(missing)} IDs have no plain-English details: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
