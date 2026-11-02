"""
Run-level configuration and metadata for the execution reporter.

Everything is read from the environment, so the same code works on a laptop
and in CI. Each knob also has a safe default.

    REPORT_ENABLED        1 / 0                         (default 1)
    REPORT_DIR            root folder for reports      (default reports)
    REPORT_TITLE          title shown in the header     (default "SprintEXcrow Test Execution Report")
    REPORT_SCREENSHOTS    only-on-failure | on | off    (default only-on-failure)
    REPORT_FULL_PAGE      1 / 0  full-page screenshots  (default 1)
    REPORT_VIDEO          retain-on-failure | on | off  (default retain-on-failure)
    REPORT_TRACE          retain-on-failure | on | off  (default retain-on-failure)
    REPORT_KEEP_RUNS      run folders + reports to keep (default 0 = keep all)
    REPORT_HISTORY_SIZE   runs kept for trends          (default 50)
    REPORT_EMBED_MAX_MB   screenshots/videos embedded in the page (default 60)
    REPORT_ENV            environment label             (default derived from BASE_URL)
    BUILD_VERSION         build / release under test    (also APP_VERSION, RELEASE_VERSION)
    REPORT_EXECUTED_BY    who ran it                    (default CI user or OS user)
"""
from __future__ import annotations

import getpass
import os
import platform
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from config.settings import settings

# Run folder handed from the xdist controller to its workers.
ENV_RUN_DIR = "REPORT_RUN_DIR"
ENV_RUN_ID = "REPORT_RUN_ID"

_MEDIA_MODES = {"on", "off", "retain-on-failure", "only-on-failure"}


def _mode(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in _MEDIA_MODES else default


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ReportConfig:
    enabled: bool = field(default_factory=lambda: _flag("REPORT_ENABLED", True))
    root: Path = field(default_factory=lambda: Path(os.getenv("REPORT_DIR", "reports")).resolve())
    title: str = field(default_factory=lambda: os.getenv("REPORT_TITLE", "SprintEXcrow Test Execution Report"))
    screenshots: str = field(default_factory=lambda: _mode("REPORT_SCREENSHOTS", "only-on-failure"))
    full_page: bool = field(default_factory=lambda: _flag("REPORT_FULL_PAGE", True))
    video: str = field(default_factory=lambda: _mode("REPORT_VIDEO", "retain-on-failure"))
    trace: str = field(default_factory=lambda: _mode("REPORT_TRACE", "retain-on-failure"))
    keep_runs: int = field(default_factory=lambda: _int("REPORT_KEEP_RUNS", 0))  # 0 = keep all
    history_size: int = field(default_factory=lambda: _int("REPORT_HISTORY_SIZE", 50))
    # screenshots + videos inlined into the single report page, in MB
    embed_max_mb: int = field(default_factory=lambda: _int("REPORT_EMBED_MAX_MB", 60))

    # caps that keep a single report small on large suites
    max_api_logs: int = 200
    max_console: int = 200
    max_network: int = 200
    max_body_chars: int = 4000
    max_log_chars: int = 20000

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def history_dir(self) -> Path:
        return self.root / "history"

    @property
    def latest_dir(self) -> Path:
        return self.root / "latest"


def make_run_id(args: list[str]) -> str:
    """Timestamp + scope, e.g. ``20261019-170512_login`` for a single-module run.

    The scope keeps module-wise runs easy to find in ``reports/runs``.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files = [Path(a.split("::")[0]).stem for a in args if a.split("::")[0].endswith(".py")]
    names = [re.sub(r"^test_(\d+_)?", "", f) for f in files]
    if not names:
        scope = "full"
    elif len(names) <= 3:
        scope = "+".join(names)
    else:
        scope = f"{len(names)}-modules"
    return f"{stamp}_{re.sub(r'[^A-Za-z0-9+_-]', '', scope)[:60]}"


def _environment_label() -> str:
    explicit = os.getenv("REPORT_ENV") or os.getenv("TEST_ENV")
    if explicit:
        return explicit
    host = (urlparse(settings.base_url).hostname or "").lower()
    for key, label in (("uat", "UAT"), ("stag", "Staging"), ("qa", "QA"), ("dev", "Dev"),
                       ("sandbox", "Sandbox"), ("localhost", "Local")):
        if key in host:
            return label
    return host or "unknown"


def _ci() -> dict:
    env = os.environ
    if env.get("GITHUB_ACTIONS"):
        url = f"{env.get('GITHUB_SERVER_URL', '')}/{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
        return {"name": "GitHub Actions", "url": url, "build": env.get("GITHUB_RUN_NUMBER", "")}
    if env.get("GITLAB_CI"):
        return {"name": "GitLab CI", "url": env.get("CI_PIPELINE_URL", ""), "build": env.get("CI_PIPELINE_IID", "")}
    if env.get("JENKINS_URL"):
        return {"name": "Jenkins", "url": env.get("BUILD_URL", ""), "build": env.get("BUILD_NUMBER", "")}
    if env.get("TF_BUILD"):
        return {"name": "Azure DevOps", "url": "", "build": env.get("BUILD_BUILDNUMBER", "")}
    return {"name": "Local", "url": "", "build": ""}


def _executed_by() -> str:
    for key in ("REPORT_EXECUTED_BY", "GITHUB_ACTOR", "GITLAB_USER_LOGIN", "BUILD_USER",
                "BUILD_REQUESTEDFOR"):
        if os.getenv(key):
            return os.environ[key]
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no login name in some containers
        return "unknown"


def _version(dist: str) -> str:
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:  # noqa: BLE001
        return ""


def run_metadata(run_id: str, browser: str, args: list[str], workers: int) -> dict:
    """Static facts about this execution (the dynamic ones are added at the end)."""
    ci = _ci()
    return {
        "run_id": run_id,
        "environment": _environment_label(),
        "base_url": settings.base_url,
        "browser": browser,
        "browser_version": "",
        "headless": settings.headless,
        "build_version": (os.getenv("BUILD_VERSION") or os.getenv("APP_VERSION")
                          or os.getenv("RELEASE_VERSION") or ci["build"] or "not set"),
        "executed_by": _executed_by(),
        "host": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "pytest": _version("pytest"),
        "playwright": _version("playwright"),
        "ci": ci,
        "command": "pytest " + " ".join(args),
        "workers": workers,
    }
