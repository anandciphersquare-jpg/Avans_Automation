"""
pytest plugin: builds the execution report automatically after every run.

Enable it from the root conftest.py:

    pytest_plugins = ["reporting.plugin"]

Lifecycle per test (and per rerun attempt):

    setup     create/reset the TestRecorder, mark it current
    call      attach console/network/API listeners + tracing to every Page /
              BrowserContext fixture, run the test, then on failure take
              screenshots, keep the trace and note the video
    teardown  contexts are closed by now - keep/delete the video, finish the
              record and hang it on the teardown report (``exec_record``)

The record travels on the report object, so it works the same in-process and
under pytest-xdist (reports are serialised with their attributes). The
controller collects records in ``pytest_runtest_logreport`` and writes the
HTML / JSON / CSV / log / history outputs in ``pytest_sessionfinish``.
"""
from __future__ import annotations

import os
import time
import warnings
from pathlib import Path

import pytest

from config.settings import settings
from reporting import metadata as md
from reporting.config import ENV_RUN_DIR, ENV_RUN_ID, ReportConfig, make_run_id, run_metadata
from reporting.models import BLOCKED, FAIL, PASS, SKIPPED
from reporting.recorder import BROWSER_KEY, TestRecorder, set_current

RECORDER_KEY = pytest.StashKey[TestRecorder]()
PLUGIN_NAME = "execution-report"

# run folder of the active plugin, read by media_context_kwargs()
_active_run_dir: Path | None = None
_active_cfg: ReportConfig | None = None


def media_context_kwargs() -> dict:
    """Extra ``browser.new_context()`` args for video recording.

    Merge into every context the suite creates (conftest does this), e.g.
    ``browser.new_context(**media_context_kwargs(), **other)``.
    """
    if _active_run_dir is None or _active_cfg is None or _active_cfg.video == "off":
        return {}
    raw = _active_run_dir / "videos" / "_raw"
    raw.mkdir(parents=True, exist_ok=True)
    return {"record_video_dir": str(raw)}


# --------------------------------------------------------------------------- #
# options / registration
# --------------------------------------------------------------------------- #
def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("execution-report", "Execution HTML report")
    group.addoption("--no-exec-report", action="store_true", default=False,
                    help="Do not build the execution report for this run.")
    group.addoption("--report-title", default=None, help="Title shown in the report header.")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "meta(id, name, module, feature, type, preconditions, expected, data): "
        "test-case metadata shown in the execution report")
    config.addinivalue_line(
        "markers",
        "pending_dev(reason): feature not finished by the developers; the test still runs, a failure "
        "is reported as 'Pending development' instead of a defect")
    config.addinivalue_line("markers", "validation: field / business-rule validation")
    config.addinivalue_line("markers", "integration: crosses module or system boundaries")

    cfg = ReportConfig()
    if not cfg.enabled or config.getoption("--no-exec-report") or config.option.collectonly:
        return

    is_worker = hasattr(config, "workerinput")
    if is_worker:
        if not os.getenv(ENV_RUN_DIR):
            return
        run_dir, run_id = Path(os.environ[ENV_RUN_DIR]), os.environ[ENV_RUN_ID]
    else:
        run_id = make_run_id(list(config.args))
        run_dir = cfg.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        # xdist workers are spawned after configure and inherit these
        os.environ[ENV_RUN_DIR] = str(run_dir)
        os.environ[ENV_RUN_ID] = run_id

    browsers = config.getoption("--browser", default=None) or []
    config.stash[BROWSER_KEY] = (browsers[0] if browsers else settings.browser)

    global _active_run_dir, _active_cfg
    _active_run_dir, _active_cfg = run_dir, cfg
    config.pluginmanager.register(ExecutionReport(config, cfg, run_dir, run_id, is_worker), PLUGIN_NAME)


PENDING_PREFIX = "PENDING DEVELOPMENT: "


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """pending_dev -> non-strict xfail: runs, never turns the run red, reported as pending."""
    for item in items:
        mark = item.get_closest_marker("pending_dev")
        if mark is not None:
            reason = mark.kwargs.get("reason") or (mark.args[0] if mark.args else "feature not finished")
            item.add_marker(pytest.mark.xfail(reason=PENDING_PREFIX + reason, strict=False))


# --------------------------------------------------------------------------- #
# fixture
# --------------------------------------------------------------------------- #
class _NullRecorder:
    """Stand-in used when reporting is disabled, so tests never need guards."""

    def step(self, title: str):
        from contextlib import nullcontext
        return nullcontext()

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def report(request: pytest.FixtureRequest):
    """Enrich the current test's report: steps, data, expected/actual, pages."""
    return request.node.stash.get(RECORDER_KEY, None) or _NullRecorder()


# --------------------------------------------------------------------------- #
# the plugin
# --------------------------------------------------------------------------- #
class ExecutionReport:
    def __init__(self, config: pytest.Config, cfg: ReportConfig, run_dir: Path, run_id: str,
                 is_worker: bool):
        self.config = config
        self.cfg = cfg
        self.run_dir = run_dir
        self.run_id = run_id
        self.is_worker = is_worker
        self.worker = os.getenv("PYTEST_XDIST_WORKER", "main")
        self.records: dict[str, dict] = {}
        self.started = time.time()
        self.html_path: Path | None = None

    # -- per test -----------------------------------------------------------
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        rec = item.stash.get(RECORDER_KEY, None)
        if rec is None:
            rec = TestRecorder(item, self.cfg, self.run_dir, self.worker)
            item.stash[RECORDER_KEY] = rec
        else:
            rec.new_attempt()  # rerun of the same item
        set_current(rec)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item: pytest.Item):
        rec = item.stash.get(RECORDER_KEY, None)
        if rec is not None:
            rec.call_reached = True
            for value in list(getattr(item, "funcargs", {}).values()):
                rec.watcher.watch(value)
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        rec = item.stash.get(RECORDER_KEY, None)
        if rec is not None:
            try:
                self._on_phase(item, call, report, rec)
            except Exception as exc:  # noqa: BLE001 - reporting must never fail a test
                warnings.warn(f"execution report: could not record {item.nodeid}: {exc!r}")
        return report

    def _on_phase(self, item, call, report, rec: TestRecorder) -> None:
        cfg = self.cfg
        if call.when == "setup":
            rec.start_epoch = call.start
            if report.failed:
                rec.status, rec.failed_phase = BLOCKED, "setup"
                self._error(item, rec, call, report, "setup")
                for value in list(getattr(item, "funcargs", {}).values()):
                    rec.watcher.watch(value)
                if cfg.screenshots != "off":
                    rec.watcher.screenshot_all("setup-failure")
            elif report.skipped:
                rec.status, rec.skip_reason = SKIPPED, _skip_reason(report)

        elif call.when == "call":
            failed = report.failed
            if failed:
                rec.status, rec.failed_phase = FAIL, "call"
                self._error(item, rec, call, report, "call")
            elif report.skipped:
                rec.status, rec.skip_reason = SKIPPED, _skip_reason(report)
                rec.fail_line = md.failing_line(item, call.excinfo)
                if hasattr(report, "wasxfail") and call.excinfo is not None:
                    # keep what the pending test found, so developers see the current gap
                    self._error(item, rec, call, report, "call")
                    failed = True  # screenshot + trace like a failure
            else:
                rec.status = PASS
            if cfg.screenshots == "on" or (cfg.screenshots == "only-on-failure" and failed):
                rec.watcher.screenshot_all("failure" if failed else "final")
            rec.watcher.stop_tracing(keep=cfg.trace == "on" or (cfg.trace == "retain-on-failure" and failed))
            rec.watcher.remember_videos()

        elif call.when == "teardown":
            if report.failed:
                if rec.status in (PASS, SKIPPED):
                    rec.status, rec.failed_phase = FAIL, "teardown"
                    self._error(item, rec, call, report, "teardown")
                else:
                    rec.stack_trace += "\n\n----- teardown error -----\n" + report.longreprtext
            rec.end_epoch = call.stop
            rec.watcher.stop_tracing(keep=False)  # setup failures never reached call
            rec.watcher.detach()
            bad = rec.status in (FAIL, BLOCKED)
            rec.watcher.collect_videos(keep=cfg.video == "on" or (cfg.video == "retain-on-failure" and bad))
            rec.captured_log = _captured(report, cfg.max_log_chars)
            rec.attempt_outcomes.append(rec.status)
            report.exec_record = rec.to_record()
            set_current(None)

    def _error(self, item, rec: TestRecorder, call, report, phase: str) -> None:
        excinfo = call.excinfo
        if excinfo is not None:
            etype, message = excinfo.typename, str(excinfo.value)
        else:
            lines = report.longreprtext.strip().splitlines()
            etype, message = "", (lines[-1] if lines else "")
        first = next((ln.strip() for ln in message.splitlines() if ln.strip()), "")
        if not first:
            crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
            first = getattr(crash, "message", "") or etype
        rec.error_type = etype
        rec.failure_reason = (f"{etype}: {first}" if etype and not first.startswith(etype) else first)[:600]
        if phase == "setup":
            rec.failure_reason = f"Setup failed - {rec.failure_reason}"
        elif phase == "teardown":
            rec.failure_reason = f"Teardown failed - {rec.failure_reason}"
        rec.failure_category = md.classify_failure(etype, message, phase)
        rec.stack_trace = report.longreprtext[-self.cfg.max_log_chars:]
        rec.fail_line = md.failing_line(item, excinfo)

    # -- collection --------------------------------------------------------------
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if not report.failed or self.is_worker:
            return
        path = report.nodeid or str(getattr(report, "fspath", "collection"))
        self.records[f"collect::{path}"] = {
            "nodeid": path, "test_id": "COLLECT-ERR", "test_id_auto": True,
            "name": f"Collection error in {path}", "function": "", "file": path, "line": 0,
            "module": md.humanize(Path(path).stem.replace("test_", "")) if path.endswith(".py") else "Collection",
            "feature": "Test collection", "test_type": "Functional", "test_types": ["Functional"],
            "markers": [], "preconditions": [], "test_data": {}, "steps": [],
            "expected": "Module imports and tests are collected", "actual": "Collection failed",
            "status": BLOCKED, "failure_reason": (report.longreprtext.strip().splitlines() or [""])[-1][:600],
            "failure_category": "Collection / Import", "error_type": "", "skip_reason": "",
            "stack_trace": report.longreprtext[-self.cfg.max_log_chars:],
            "attachments": [], "api_logs": [], "console_errors": [], "network_failures": [],
            "captured_log": "", "start": "", "end": "", "duration_s": 0.0, "attempts": 1,
            "attempt_outcomes": [BLOCKED], "flaky": False, "browser": "", "browser_version": "",
            "worker": "main",
        }

    # -- collect results (controller, or the only process without xdist) ----------
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        record = getattr(report, "exec_record", None)
        if record:
            self.records[report.nodeid] = record  # last attempt wins

    # -- write outputs -----------------------------------------------------------
    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.is_worker:
            return
        if not self.records:
            return
        from reporting.writers import write_all

        finished = time.time()
        workers = getattr(self.config.option, "numprocesses", None) or 0
        meta = run_metadata(self.run_id, self.config.stash.get(BROWSER_KEY, ""),
                            [str(a) for a in self.config.invocation_params.args], workers)
        meta.update({
            "title": self.config.getoption("--report-title") or self.cfg.title,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started)),
            "finished": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(finished)),
            "duration_s": round(finished - self.started, 2),
            "exit_status": int(exitstatus),
            "headless": not self.config.getoption("--headed", default=False),
            "browser_version": next((r["browser_version"] for r in self.records.values()
                                     if r.get("browser_version")), ""),
        })
        try:
            self.html_path = write_all(self.cfg, self.run_dir, meta, list(self.records.values()))
        except Exception as exc:  # noqa: BLE001 - never turn a green run red
            warnings.warn(f"execution report could not be written: {exc!r}")

    def pytest_terminal_summary(self, terminalreporter) -> None:
        if self.is_worker or self.html_path is None:
            return
        terminalreporter.write_sep("-", "test report")
        terminalreporter.write_line(f"Report: {self.html_path}")
        terminalreporter.write_line(f"(earlier reports are kept in {self.cfg.root})")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _skip_reason(report) -> str:
    if hasattr(report, "wasxfail"):
        if str(report.wasxfail).startswith(PENDING_PREFIX):
            return str(report.wasxfail)
        return f"Expected failure (xfail): {report.wasxfail}".rstrip(": ")
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix("Skipped: ")
    return str(longrepr or "")[:500]


def _captured(report, limit: int) -> str:
    parts = [f"===== {title} =====\n{content}" for title, content in report.sections if content.strip()]
    text = "\n".join(parts)
    return text if len(text) <= limit else "…[truncated]\n" + text[-limit:]
