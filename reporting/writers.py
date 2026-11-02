"""
Output writers - everything the controller produces at session end.

    reports/
    ├── Test_Report_<run_id>.html      one page per run (never replaced): every
    │                                  test case, screenshots and videos embedded
    ├── history/history.json           run summaries + per-test statuses (trends)
    └── runs/<run_id>/                 raw outputs of each run
        ├── json/results.json          full machine-readable results
        ├── json/summary.json          totals only (CI gates, dashboards)
        ├── csv/results.csv            one row per test (Excel-friendly)
        ├── logs/execution.log         plain-text execution log
        ├── screenshots/  videos/  traces/
"""
from __future__ import annotations

import base64
import copy
import csv
import html
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from reporting.config import ReportConfig
from reporting.models import BLOCKED, FAIL, PASS, SKIPPED
from reporting.qa import qa_analysis

REPORT_NAME = "Test_Report.html"  # old single name; kept only to migrate it


def report_name(run_id: str) -> str:
    """Every run gets its own page, so earlier reports are never replaced."""
    return f"Test_Report_{run_id}.html"
# old multi-file outputs, removed so only one report page remains
_LEGACY = ("index.html", "latest-report.html", "report.html", "latest")
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webm": "video/webm",
         ".mp4": "video/mp4"}

TEMPLATES = Path(__file__).parent / "templates"
TREND_POINTS = 20
TEST_HISTORY_POINTS = 10


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def summarize(records: list[dict]) -> dict:
    counts = Counter(r["status"] for r in records)
    total = len(records)
    executed = counts[PASS] + counts[FAIL] + counts[BLOCKED]
    modules: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        modules[r["module"]][r["status"]] += 1
        modules[r["module"]]["duration_s"] += r.get("duration_s") or 0
    categories = Counter(r["failure_category"] or "Uncategorised"
                         for r in records if r["status"] in (FAIL, BLOCKED))
    verdicts = Counter(r["qa"]["verdict"] for r in records
                       if r.get("qa") and r["status"] in (FAIL, BLOCKED))
    types = Counter(r["test_type"] for r in records)
    return {
        "total": total,
        "passed": counts[PASS],
        "failed": counts[FAIL],
        "blocked": counts[BLOCKED],
        "skipped": counts[SKIPPED],
        "executed": executed,
        "pass_pct": round(100 * counts[PASS] / executed, 1) if executed else 0.0,
        "test_time_s": round(sum(r.get("duration_s") or 0 for r in records), 2),
        "retried": sum(1 for r in records if r.get("attempts", 1) > 1),
        "flaky": sum(1 for r in records if r.get("flaky")),
        "modules": {
            name: {"total": sum(c[s] for s in (PASS, FAIL, BLOCKED, SKIPPED)),
                   "passed": c[PASS], "failed": c[FAIL], "blocked": c[BLOCKED],
                   "skipped": c[SKIPPED], "duration_s": round(c["duration_s"], 2)}
            for name, c in sorted(modules.items())
        },
        "failure_categories": dict(categories.most_common()),
        "verdicts": dict(verdicts.most_common()),
        "types": dict(types.most_common()),
    }


# --------------------------------------------------------------------------- #
# history / trends
# --------------------------------------------------------------------------- #
def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    """Atomic write so a crash never leaves half a history file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def apply_history(cfg: ReportConfig, records: list[dict]) -> tuple[dict, list[dict]]:
    """Annotate records with their recent statuses; return (history, trend)."""
    history = _read_json(cfg.history_dir / "history.json", {"runs": []})
    runs = history.get("runs", [])
    for r in records:
        past = [run["tests"][r["nodeid"]] for run in runs[-TEST_HISTORY_POINTS:]
                if r["nodeid"] in run.get("tests", {})]
        r["history"] = past
        prev = past[-1] if past else None
        bad = (FAIL, BLOCKED)
        if prev is None:
            r["trend"] = "new test" if runs else ""
        elif r["status"] in bad and prev not in bad:
            r["trend"] = "new failure"
        elif r["status"] in bad and prev in bad:
            r["trend"] = "still failing"
        elif r["status"] == PASS and prev in bad:
            r["trend"] = "fixed"
        else:
            r["trend"] = ""
    trend = [{k: run.get(k) for k in ("run_id", "started", "pass_pct", "total", "passed",
                                       "failed", "blocked", "skipped", "duration_s")}
             for run in runs[-(TREND_POINTS - 1):]]
    return history, trend


def save_history(cfg: ReportConfig, history: dict, meta: dict, summary: dict,
                 records: list[dict]) -> None:
    runs = history.setdefault("runs", [])
    runs.append({
        "run_id": meta["run_id"], "started": meta["started"], "duration_s": meta["duration_s"],
        "environment": meta["environment"], "build_version": meta["build_version"],
        "browser": meta["browser"], "executed_by": meta["executed_by"],
        "modules": sorted(summary["modules"]),
        **{k: summary[k] for k in ("total", "passed", "failed", "blocked", "skipped", "pass_pct")},
        "report": report_name(meta["run_id"]),
        "tests": {r["nodeid"]: r["status"] for r in records},
    })
    history["runs"] = runs[-cfg.history_size:]
    _write_json(cfg.history_dir / "history.json", history)


# --------------------------------------------------------------------------- #
# data files
# --------------------------------------------------------------------------- #
CSV_COLUMNS = [
    ("Test Case ID", lambda r, m: r["test_id"]),
    ("Test Case Name", lambda r, m: r["name"]),
    ("Module", lambda r, m: r["module"]),
    ("Feature", lambda r, m: r["feature"]),
    ("Type", lambda r, m: ", ".join(r["test_types"])),
    ("Preconditions", lambda r, m: " | ".join(r["preconditions"])),
    ("Test Data", lambda r, m: json.dumps(r["test_data"], ensure_ascii=False) if r["test_data"] else ""),
    ("Steps", lambda r, m: "\n".join(f"{i}. [{s['status']}] {s['title']}" for i, s in enumerate(r["steps"], 1))),
    ("Expected Result", lambda r, m: r["expected"]),
    ("Actual Result", lambda r, m: r["actual"]),
    ("Status", lambda r, m: r["status"]),
    ("QA Summary", lambda r, m: r["qa"]["summary"] if r["status"] != PASS else ""),
    ("Issue Type", lambda r, m: r["qa"]["verdict"] if r["status"] != PASS else ""),
    ("Failed At", lambda r, m: r["qa"]["failed_at"]),
    ("Probable Cause", lambda r, m: r["qa"]["cause"]),
    ("Suggested Action", lambda r, m: r["qa"]["action"]),
    ("Technical Error", lambda r, m: r["failure_reason"] or r["skip_reason"]),
    ("Failure Category", lambda r, m: r["failure_category"]),
    ("Error / Stack Trace", lambda r, m: r["stack_trace"][-3000:]),
    ("Screenshots", lambda r, m: "; ".join(a["path"] for a in r["attachments"] if a["kind"] == "screenshot")),
    ("Video", lambda r, m: "; ".join(a["path"] for a in r["attachments"] if a["kind"] == "video")),
    ("Trace", lambda r, m: "; ".join(a["path"] for a in r["attachments"] if a["kind"] == "trace")),
    ("Start", lambda r, m: r["start"]),
    ("End", lambda r, m: r["end"]),
    ("Duration (s)", lambda r, m: r["duration_s"]),
    ("Browser", lambda r, m: f"{r['browser']} {r['browser_version']}".strip()),
    ("Environment", lambda r, m: m["environment"]),
    ("Executed By", lambda r, m: m["executed_by"]),
    ("Build Version", lambda r, m: m["build_version"]),
    ("API Calls", lambda r, m: len(r["api_logs"])),
    ("Console Errors", lambda r, m: len(r["console_errors"])),
    ("Network Failures", lambda r, m: len(r["network_failures"])),
    ("Attempts", lambda r, m: r["attempts"]),
    ("Flaky", lambda r, m: "yes" if r["flaky"] else ""),
    ("Node ID", lambda r, m: r["nodeid"]),
]


def write_csv(path: Path, records: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel opens it with the right encoding
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow([name for name, _ in CSV_COLUMNS])
        for r in records:
            writer.writerow([fn(r, meta) for _, fn in CSV_COLUMNS])


def write_log(path: Path, records: list[dict], meta: dict, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Run        : {meta['run_id']}",
        f"Started    : {meta['started']}   Finished: {meta['finished']}   ({meta['duration_s']}s)",
        f"Environment: {meta['environment']} ({meta['base_url']})   Build: {meta['build_version']}",
        f"Browser    : {meta['browser']} {meta['browser_version']}   Executed by: {meta['executed_by']}",
        f"Command    : {meta['command']}",
        f"Result     : {summary['passed']} passed, {summary['failed']} failed, {summary['blocked']} blocked, "
        f"{summary['skipped']} skipped of {summary['total']} ({summary['pass_pct']}% of executed)",
        "-" * 100,
    ]
    for r in sorted(records, key=lambda x: x["start"] or ""):
        lines.append(f"{r['start'][11:23]:<12} {r['status']:<8} {r['duration_s']:>8.2f}s  "
                     f"{r['test_id']:<18} {r['nodeid']}")
        if r["status"] != PASS:
            qa = r["qa"]
            lines.append(f"{'':<31}-> [{qa['verdict']}] {qa['summary']}")
            if qa["action"]:
                lines.append(f"{'':<31}   Next: {qa['action']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _safe_json(data) -> str:
    """JSON that can sit inside a <script> element."""
    return (json.dumps(data, ensure_ascii=False, default=str)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_html(payload: dict) -> str:
    page = (TEMPLATES / "report.html").read_text(encoding="utf-8")
    css = (TEMPLATES / "report.css").read_text(encoding="utf-8")
    js = (TEMPLATES / "report.js").read_text(encoding="utf-8")
    title = html.escape(payload["meta"]["title"])
    return (page.replace("{{TITLE}}", title)
                .replace("/*{{CSS}}*/", css)
                .replace("/*{{JS}}*/", js)
                .replace("{{DATA}}", _safe_json(payload)))


def embed_evidence(cfg: ReportConfig, records: list[dict], run_dir: Path, page_dir: Path) -> list[dict]:
    """Copy of the records for the HTML page: screenshots (and videos, within
    REPORT_EMBED_MAX_MB) inlined as data: URIs so the page needs no other file.
    Anything not inlined (traces, large videos) gets a link relative to the page."""
    out = copy.deepcopy(records)
    budget = cfg.embed_max_mb * 1024 * 1024
    rel_base = os.path.relpath(run_dir, page_dir).replace("\\", "/")
    rel_base = "" if rel_base == "." else rel_base + "/"
    # screenshots first (small and the most useful), then videos of failed tests
    order = sorted(((r, a) for r in out for a in r["attachments"]),
                   key=lambda ra: {"screenshot": 0, "video": 1}.get(ra[1]["kind"], 2))
    for _, a in order:
        a["href"] = rel_base + a["path"]
        src = run_dir / a["path"]
        mime = _MIME.get(src.suffix.lower())
        if a["kind"] not in ("screenshot", "video") or not mime or not src.exists():
            continue
        size = src.stat().st_size
        if size > budget:
            continue
        budget -= size
        a["src"] = f"data:{mime};base64," + base64.b64encode(src.read_bytes()).decode("ascii")
    return out


def _remove_legacy(cfg: ReportConfig) -> None:
    for name in _LEGACY:
        target = cfg.root / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink(missing_ok=True)
    pytest_html_assets = cfg.root / "assets"
    if (pytest_html_assets / "style.css").exists():
        shutil.rmtree(pytest_html_assets, ignore_errors=True)


def prune_runs(cfg: ReportConfig, keep_run: Path) -> None:
    """Only when REPORT_KEEP_RUNS > 0 (default 0 = keep every run and its report)."""
    if cfg.keep_runs <= 0 or not cfg.runs_dir.exists():
        return
    runs = sorted((p for p in cfg.runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in runs[:-cfg.keep_runs]:
        if old != keep_run:
            shutil.rmtree(old, ignore_errors=True)
            (cfg.root / report_name(old.name)).unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def write_all(cfg: ReportConfig, run_dir: Path, meta: dict, records: list[dict]) -> Path:
    records.sort(key=lambda r: (r["module"], r["file"], r["line"], r["nodeid"]))
    for r in records:
        r["qa"] = qa_analysis(r)
        # the derived "actual" was the raw exception; the QA wording reads better
        if r["status"] != PASS and r["actual"] in (r["failure_reason"], f"Could not run: {r['failure_reason']}",
                                                   f"Not executed: {r['skip_reason']}"):
            r["actual"] = r["qa"]["actual"]
    summary = summarize(records)
    history, trend = apply_history(cfg, records)

    trend_point = {"run_id": meta["run_id"], "started": meta["started"], "duration_s": meta["duration_s"],
                   **{k: summary[k] for k in ("pass_pct", "total", "passed", "failed", "blocked", "skipped")}}
    payload = {"meta": meta, "summary": summary, "trend": trend + [trend_point], "tests": records}

    _write_json(run_dir / "json" / "results.json", payload)
    _write_json(run_dir / "json" / "summary.json", {"meta": meta, "summary": summary})
    write_csv(run_dir / "csv" / "results.csv", records, meta)
    write_log(run_dir / "logs" / "execution.log", records, meta, summary)

    shutil.rmtree(run_dir / "videos" / "_raw", ignore_errors=True)  # unclaimed recordings
    shutil.rmtree(run_dir / "html", ignore_errors=True)  # old layout
    _remove_legacy(cfg)

    # one page per run, never overwritten: reports/Test_Report_<run_id>.html
    html_path = cfg.root / report_name(meta["run_id"])
    page = {**payload, "tests": embed_evidence(cfg, records, run_dir, cfg.root)}
    html_path.write_text(render_html(page), encoding="utf-8")

    save_history(cfg, history, meta, summary, records)
    prune_runs(cfg, run_dir)
    return html_path
