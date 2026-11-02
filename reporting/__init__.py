"""
Execution reporting for the pytest + Playwright suite.

    pytest_plugins = ["reporting.plugin"]       # root conftest.py

Public helpers:

    report            fixture - steps, data, expected/actual, extra pages
    step(title)       context manager usable from page objects / helpers
    current()         the running test's recorder (or None)
    media_context_kwargs()   video args to merge into browser.new_context()
    requests_hook     requests response hook that logs API calls

``reporting.plugin`` is imported lazily: pytest must be the first to import it
(via ``pytest_plugins``), otherwise it warns that it cannot rewrite the module.
"""
from reporting.api_log import requests_hook
from reporting.recorder import current, step

__all__ = ["current", "media_context_kwargs", "requests_hook", "step"]


def __getattr__(name: str):
    if name == "media_context_kwargs":
        from reporting.plugin import media_context_kwargs
        return media_context_kwargs
    raise AttributeError(name)
