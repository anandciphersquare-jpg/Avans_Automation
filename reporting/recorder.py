"""
Per-test recorder - the object behind the ``report`` fixture.

One TestRecorder exists per test item. The plugin creates it at setup, the
test (optionally) enriches it, capture hooks feed it, and at teardown it is
turned into a TestRecord.

Inside a test:

    def test_add_beneficiary(logged_in_page, report):
        report.meta(id="WBEN-004", feature="Add Beneficiary", type="Functional")
        report.precondition("Beneficiary module is enabled for the admin role")
        data = new_beneficiary()
        report.data(beneficiary=data)
        with report.step("Open Add Beneficiary form"):
            ...
        with report.step("Submit the form"):
            ...
        report.actual(bp.toast_text())

Anywhere else (page objects, helpers) - a no-op outside a test:

    from reporting import step
    with step("Fill bank details"):
        ...
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from reporting import metadata as md
from reporting.api_log import entry_from_requests
from reporting.browser import PageWatcher
from reporting.config import ReportConfig
from reporting.models import BLOCKED, FAIL, PASS, SKIPPED, TestRecord

_current: "TestRecorder | None" = None


def current() -> "TestRecorder | None":
    """The recorder of the test that is running right now (None outside tests)."""
    return _current


def set_current(rec: "TestRecorder | None") -> None:
    global _current
    _current = rec


@contextmanager
def step(title: str) -> Iterator[None]:
    """Report a step from anywhere; does nothing when no test is running."""
    rec = current()
    if rec is None:
        yield
        return
    with rec.step(title):
        yield


def _slug(nodeid: str) -> str:
    name = nodeid.split("::")[-1]
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:60]
    digest = hashlib.sha1(nodeid.encode()).hexdigest()[:6]
    return f"{clean}_{digest}"


class TestRecorder:
    __test__ = False  # not a test class, despite the name

    def __init__(self, item: pytest.Item, cfg: ReportConfig, run_dir: Path, worker: str):
        self.item = item
        self.cfg = cfg
        self.run_dir = run_dir
        self.worker = worker
        self.slug = _slug(item.nodeid)
        self.attempt = 0
        self.attempt_outcomes: list[str] = []
        self.attachments: list[dict] = []
        self.browser_name = ""
        self.browser_version = ""
        self._overrides: dict[str, Any] = {}
        self.new_attempt()

    # ------------------------------------------------------------------ lifecycle
    def new_attempt(self) -> None:
        """Reset per-attempt state (pytest-rerunfailures reruns reuse the item)."""
        self.attempt += 1
        self.steps: list[dict] = []
        self._depth = 0
        self.extra_preconditions: list[str] = []
        self.data_used: dict = {}
        self.api_logs: list[dict] = []
        self.console_errors: list[dict] = []
        self.network_failures: list[dict] = []
        self.dropped = {"api": 0, "console": 0, "network": 0}
        self.watcher = PageWatcher(self)
        # outcome (filled by the plugin)
        self.status = PASS
        self.failure_reason = ""
        self.failure_category = ""
        self.error_type = ""
        self.stack_trace = ""
        self.skip_reason = ""
        self.fail_line: int | None = None
        self.failed_phase = ""
        self.call_reached = False
        self.start_epoch = time.time()
        self.end_epoch = self.start_epoch
        self.captured_log = ""
        self.page_urls: list[str] = []

    # ------------------------------------------------------------------ test API
    def meta(self, **fields: Any) -> None:
        """Override inferred metadata: id, name, module, feature, type, expected."""
        self._overrides.update(fields)

    def precondition(self, text: str) -> None:
        self.extra_preconditions.append(text)

    def data(self, mapping: dict | None = None, **values: Any) -> None:
        """Record test data used (secrets are redacted in the report)."""
        if mapping:
            self.data_used.update(mapping)
        self.data_used.update(values)

    def expected(self, text: str) -> None:
        self._overrides["expected"] = text

    def actual(self, text: str) -> None:
        self._overrides["actual"] = str(text)

    @contextmanager
    def step(self, title: str) -> Iterator[None]:
        entry = {"title": title, "status": "passed", "duration_ms": 0, "source": "explicit",
                 "line": None, "error": "", "depth": self._depth}
        self.steps.append(entry)
        self._depth += 1
        started = time.perf_counter()
        try:
            yield
        except pytest.skip.Exception as exc:
            entry["status"] = "skipped"
            entry["error"] = str(exc)[:500]
            raise
        except BaseException as exc:
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"[:1000]
            raise
        finally:
            self._depth -= 1
            entry["duration_ms"] = int((time.perf_counter() - started) * 1000)

    def attach_page(self, page_or_context: Any) -> None:
        """Capture console/network/screenshots for a page the test created itself."""
        self.watcher.watch(page_or_context)

    def screenshot(self, title: str = "manual", page: Any = None) -> str | None:
        """Take a screenshot now (in addition to the automatic failure one)."""
        target = page or next(iter(self.watcher.open_pages()), None)
        return self.take_screenshot(target, title) if target is not None else None

    def attach_file(self, path: str | Path, title: str = "") -> None:
        src = Path(path)
        if not src.exists():
            return
        dest = self.artifact_path("logs", src.stem, src.suffix)
        shutil.copy2(src, dest)
        self.attach(dest, "file", title or src.name)

    def log_api(self, response_or_entry: Any) -> None:
        """Log an API call: a requests.Response or a ready-made dict."""
        if isinstance(response_or_entry, dict):
            entry = {"source": "manual", **response_or_entry}
        else:
            entry = entry_from_requests(response_or_entry, self.cfg.max_body_chars)
        self.add_api(entry)

    # ------------------------------------------------------------------ capture sinks
    def _bounded(self, bucket: list, key: str, limit: int, entry: dict) -> None:
        if len(bucket) < limit:
            bucket.append(md.jsonable(entry, self.cfg.max_body_chars))
        else:
            self.dropped[key] += 1

    def add_api(self, entry: dict) -> None:
        self._bounded(self.api_logs, "api", self.cfg.max_api_logs, entry)

    def add_console(self, entry: dict) -> None:
        self._bounded(self.console_errors, "console", self.cfg.max_console, entry)

    def add_network(self, entry: dict) -> None:
        self._bounded(self.network_failures, "network", self.cfg.max_network, entry)

    # ------------------------------------------------------------------ artifacts
    def artifact_path(self, folder: str, label: str, ext: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:40]
        path = self.run_dir / folder / f"{self.slug}_a{self.attempt}_{safe}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def attach(self, path: Path, kind: str, title: str) -> None:
        rel = Path(path).resolve().relative_to(self.run_dir.resolve()).as_posix()
        self.attachments.append({"kind": kind, "path": rel, "title": title, "attempt": self.attempt})

    def take_screenshot(self, page: Any, label: str) -> str | None:
        path = self.artifact_path("screenshots", label, ".png")
        for full_page in ((True, False) if self.cfg.full_page else (False,)):
            try:
                page.screenshot(path=str(path), full_page=full_page, timeout=10_000)
                self.attach(path, "screenshot", label.replace("_", " ").replace("-", " ").title())
                return str(path)
            except Exception:  # noqa: BLE001 - very tall pages / closed pages
                continue
        return None

    # ------------------------------------------------------------------ record
    def _steps(self) -> list[dict]:
        if self.steps:
            return self.steps
        statements = md.auto_steps(self.item)
        out = []
        for start, end, text, code in statements:
            if not self.call_reached:
                state = "not run"
            elif self.fail_line is None:
                # passed, or the failure happened outside the body (teardown)
                state = "passed" if self.status == PASS or self.failed_phase == "teardown" else "unknown"
            elif start <= self.fail_line <= end:
                state = "skipped" if self.status == SKIPPED else "failed"
            elif end < self.fail_line:
                state = "passed"
            else:
                state = "not run"
            out.append({"title": text, "code": code if code != text else "", "status": state,
                        "duration_ms": 0, "source": "auto", "line": start, "error": "", "depth": 0})
        return out

    def _actual(self) -> str:
        if "actual" in self._overrides:
            return self._overrides["actual"]
        if self.status == PASS:
            return "Behaved as expected - all assertions passed."
        if self.status == SKIPPED:
            return f"Not executed: {self.skip_reason}"
        if self.status == BLOCKED:
            return f"Could not run: {self.failure_reason}"
        return self.failure_reason

    def to_record(self) -> dict:
        item = self.item
        ov = self._overrides
        file, line = md.definition_location(item)
        primary, types = md.test_types(item)
        if ov.get("type"):
            primary = ov["type"]
            types = [primary] + [t for t in types if t != primary]
        tid, auto = (str(ov["id"]), False) if ov.get("id") else md.test_id(item)

        data = md.test_data(item)
        if self.data_used:
            from mcp_server.redact import redact
            data.update(md.jsonable(redact(self.data_used)))

        api_logs = list(self.api_logs)
        if self.dropped["api"]:
            api_logs.append({"source": "note", "url": f"… {self.dropped['api']} more calls not shown"})

        browser_label = self.browser_name or item.config.stash.get(BROWSER_KEY, "")

        record = TestRecord(
            nodeid=item.nodeid,
            test_id=tid,
            test_id_auto=auto,
            name=str(ov.get("name") or md.test_name(item)),
            function=getattr(item, "originalname", item.name),
            file=file,
            line=line,
            module=str(ov.get("module") or md.module_name(item)),
            feature=str(ov.get("feature") or md.feature_name(item)),
            test_type=primary,
            test_types=types,
            markers=sorted({m.name for m in item.iter_markers()} - {"parametrize", "usefixtures", "meta"}),
            preconditions=md.preconditions(item) + self.extra_preconditions,
            test_data=data,
            steps=self._steps(),
            expected=str(ov.get("expected") or md.expected_result(item)),
            actual=self._actual(),
            status=self.status,
            failure_reason=self.failure_reason,
            failure_category=self.failure_category,
            error_type=self.error_type,
            stack_trace=self.stack_trace,
            skip_reason=self.skip_reason,
            attachments=self.attachments,
            api_logs=api_logs,
            console_errors=self.console_errors,
            network_failures=self.network_failures,
            captured_log=self.captured_log,
            page_urls=list(self.page_urls),
            start=_iso(self.start_epoch),
            end=_iso(self.end_epoch),
            duration_s=round(max(self.end_epoch - self.start_epoch, 0.0), 3),
            attempts=self.attempt,
            attempt_outcomes=list(self.attempt_outcomes),
            flaky=self.status == PASS and any(o in (FAIL, BLOCKED) for o in self.attempt_outcomes[:-1]),
            browser=browser_label,
            browser_version=self.browser_version,
            worker=self.worker,
        )
        return record.to_dict()


def _iso(epoch: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(epoch).isoformat(timespec="milliseconds")


# set by the plugin: browser name selected for the run
BROWSER_KEY = pytest.StashKey[str]()
