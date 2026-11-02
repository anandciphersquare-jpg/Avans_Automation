"""Write a message to the tester's terminal, even while pytest captures output."""
from __future__ import annotations

import sys

_config = None  # set by conftest.pytest_configure


def bind(config) -> None:
    global _config
    _config = config


def say(message: str) -> None:
    capture = _config.pluginmanager.getplugin("capturemanager") if _config else None
    terminal = _config.pluginmanager.getplugin("terminalreporter") if _config else None
    if capture is not None and terminal is not None:
        with capture.global_and_fixture_disabled():
            terminal.write_line("")
            terminal.write_line(f">>> {message}", yellow=True, bold=True)
        return
    print(f">>> {message}", file=sys.__stderr__, flush=True)
