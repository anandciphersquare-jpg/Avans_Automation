"""Run / list the pytest suites in tests/ and summarise the JUnit result."""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUNIT = ROOT / "reports" / "mcp_junit.xml"
HTML = ROOT / "reports" / "mcp_report.html"

MARKERS = ["smoke", "functional", "positive", "negative", "boundary", "security",
           "authorization", "api", "ui", "auth", "regression"]


def _selection(marker: str | None, file: str | None, keyword: str | None) -> list[str]:
    args: list[str] = []
    if file:
        target = (ROOT / file).resolve()
        if ROOT not in target.parents and target != ROOT:
            raise ValueError("file must be inside the project")
        args.append(str(target.relative_to(ROOT)))
    if marker:
        args += ["-m", marker]
    if keyword:
        args += ["-k", keyword]
    return args


def list_tests(marker: str | None = None, file: str | None = None, keyword: str | None = None) -> dict:
    # pytest.ini already adds -q; a second -q would hide the test ids.
    # stdin=DEVNULL: never let pytest inherit the MCP stdio pipe.
    proc = subprocess.run([sys.executable, "-m", "pytest", "--collect-only",
                           *_selection(marker, file, keyword)],
                          cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    ids = [line for line in proc.stdout.splitlines() if "::" in line]
    by_file = Counter(i.split("::", 1)[0] for i in ids)
    return {"count": len(ids), "by_file": dict(by_file), "tests": ids[:300],
            "errors": proc.stderr[-2000:] if proc.returncode not in (0, 5) else None}


def run_tests(marker: str | None = None, file: str | None = None, keyword: str | None = None,
              workers: int = 0, headed: bool = False, max_failures: int = 0,
              reruns: int = 0, timeout_s: int = 1800) -> dict:
    JUNIT.parent.mkdir(parents=True, exist_ok=True)
    JUNIT.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "pytest", *_selection(marker, file, keyword),
           f"--junitxml={JUNIT}", f"--html={HTML}", "--self-contained-html", "--no-header"]
    if workers:
        cmd += ["-n", str(workers)]
    if max_failures:
        cmd += [f"--maxfail={max_failures}"]
    if reruns:
        cmd += ["--reruns", str(reruns)]
    env = {**os.environ, "HEADLESS": "false" if headed else os.environ.get("HEADLESS", "true"),
           "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return {"error": f"pytest exceeded {timeout_s}s and was stopped", "command": " ".join(cmd[2:])}
    summary = parse_junit() if JUNIT.exists() else {"error": "no JUnit output",
                                                     "output_tail": proc.stdout[-3000:] + proc.stderr[-2000:]}
    summary["exit_code"] = proc.returncode
    summary["command"] = "pytest " + " ".join(cmd[3:])
    summary["html_report"] = str(HTML)
    return summary


def parse_junit(path: Path = JUNIT) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = Counter()
    failures, skips = [], Counter()
    for s in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(s.get(key, 0))
        totals["time_s"] += float(s.get("time", 0))
        for case in s.iter("testcase"):
            test_id = f"{case.get('classname', '')}::{case.get('name')}"
            for kind in ("failure", "error"):
                node = case.find(kind)
                if node is not None:
                    failures.append({"test": test_id, "kind": kind,
                                     "message": (node.get("message") or "")[:400],
                                     "detail": (node.text or "")[-800:]})
            sk = case.find("skipped")
            if sk is not None:
                skips[(sk.get("message") or "")[:160]] += 1
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return {
        "totals": {"total": totals["tests"], "passed": passed, "failed": totals["failures"],
                   "errors": totals["errors"], "skipped": totals["skipped"],
                   "duration_s": round(totals["time_s"], 1)},
        "failures": failures[:50],
        "skip_reasons": [{"reason": r, "count": n} for r, n in skips.most_common(15)],
    }
