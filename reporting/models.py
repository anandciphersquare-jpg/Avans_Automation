"""
Data model for one executed test case.

Records hold only plain JSON types (str/int/float/bool/list/dict/None) so they
travel unchanged from pytest-xdist workers to the controller and straight into
results.json / the HTML report.

Nested shapes (kept as dicts for cheap serialisation):

    step         {title, status: passed|failed|skipped|not run|unknown,
                  duration_ms, source: explicit|auto, line, error, depth}
    attachment   {kind: screenshot|video|trace|file, path (relative to the
                  run folder), title, attempt}
    api log      {source: api|browser|manual, time, method, url, status, ok,
                  duration_ms, request_headers, request_body,
                  response_headers, response_body}
    console      {time, type: error|warning|pageerror, text, location}
    network      {time, kind: request failed|HTTP error, method, url, status,
                  resource_type, error}
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# final statuses
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"   # setup/fixture/collection error - the test could not run
SKIPPED = "SKIPPED"
STATUSES = (PASS, FAIL, BLOCKED, SKIPPED)


@dataclass
class TestRecord:
    __test__ = False  # keep pytest from collecting this class

    # identity
    nodeid: str
    test_id: str
    test_id_auto: bool
    name: str
    function: str
    file: str
    line: int
    module: str
    feature: str
    test_type: str
    test_types: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)

    # design
    preconditions: list[str] = field(default_factory=list)
    test_data: dict[str, Any] = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    expected: str = ""
    actual: str = ""

    # outcome
    status: str = PASS
    failure_reason: str = ""
    failure_category: str = ""
    error_type: str = ""
    stack_trace: str = ""
    skip_reason: str = ""

    # evidence
    attachments: list[dict] = field(default_factory=list)
    api_logs: list[dict] = field(default_factory=list)
    console_errors: list[dict] = field(default_factory=list)
    network_failures: list[dict] = field(default_factory=list)
    captured_log: str = ""
    page_urls: list[str] = field(default_factory=list)  # open pages when the test failed

    # timing / retries
    start: str = ""
    end: str = ""
    duration_s: float = 0.0
    attempts: int = 1
    attempt_outcomes: list[str] = field(default_factory=list)
    flaky: bool = False

    # environment seen by this test
    browser: str = ""
    browser_version: str = ""
    worker: str = "main"

    def to_dict(self) -> dict:
        return asdict(self)
