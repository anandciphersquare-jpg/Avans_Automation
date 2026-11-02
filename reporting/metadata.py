"""
Infer test-case metadata from what the suite already contains, so existing
tests produce a complete report without being edited:

    Test Case ID   docstring prefix      "AUTH-001 — valid admin login ..."
    Name           function name + parametrize id
    Module         file name             tests/test_login.py      -> "Login"
    Feature        nearest section       "# ------ forgot password" -> "Forgot Password"
                   comment above the test (falls back to the module docstring)
    Type           markers               @pytest.mark.security    -> "Security"
    Preconditions  fixtures used         logged_in_page           -> "Admin is signed in ..."
    Test data      parametrize values
    Expected       docstring text
    Steps          top-level statements of the test body (when no explicit
                   report.step() calls were made)

Any of these can be overridden per test with the ``meta`` marker:

    @pytest.mark.meta(id="AUTH-001", feature="Login", type="Smoke",
                      preconditions=["Admin account is active"],
                      expected="Dashboard is shown")

or per module with ``REPORT_MODULE`` / ``REPORT_FEATURE`` /
``REPORT_PRECONDITIONS`` globals.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from mcp_server.redact import redact

# marker -> report type, in priority order (the first match is the primary type)
TYPE_BY_MARKER: list[tuple[str, str]] = [
    ("security", "Security"),
    ("authorization", "Security"),
    ("api", "API"),
    ("integration", "Integration"),
    ("boundary", "Boundary"),
    ("validation", "Validation"),
    ("negative", "Negative"),
    ("smoke", "Smoke"),
    ("regression", "Regression"),
    ("ui", "UI/UX"),
    ("functional", "Functional"),
    ("positive", "Functional"),
    ("auth", "Functional"),
]

# fixture -> human precondition
PRECONDITION_BY_FIXTURE: dict[str, str] = {
    "logged_in_page": "Admin user is signed in (saved session reused)",
    "non_admin_page": "Limited-role (non-admin) user is signed in",
    "admin_api": "Admin API client authenticated with a bearer token",
    "api": "Unauthenticated API client",
    "page": "Fresh browser context with geolocation permission granted",
    "browser": "Browser launched",
    "tmp_cheque": "Sample cancelled-cheque image generated",
}

_ACRONYMS = {"api": "API", "ui": "UI", "ux": "UX", "otp": "OTP", "id": "ID", "url": "URL",
             "ifsc": "IFSC", "pan": "PAN", "sql": "SQL", "xss": "XSS", "idor": "IDOR",
             "upi": "UPI", "csv": "CSV", "pdf": "PDF", "kyc": "KYC"}
# section comments that name a test type, not a feature
_TYPE_SECTIONS = {"positive", "negative", "boundary", "security", "functional", "api", "ui", "smoke"}

_DOC_ID = re.compile(r"^\s*(?P<id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+[\w/.]*)\s*[—–:-]+\s*(?P<rest>.*)", re.S)
_DOC_PREFIX = re.compile(r"^\s*(?P<prefix>[A-Z][A-Z0-9]{1,})\s*[—–:-]+\s*(?P<rest>.*)", re.S)
_SECTION = re.compile(r"^\s*#\s*-{5,}\s*(?P<a>[^-].*?)\s*$|^\s*#\s*(?P<b>[^-].*?)\s*-{5,}\s*$")


def humanize(text: str) -> str:
    words = re.sub(r"[_\s]+", " ", text).strip().split(" ")
    return " ".join(_ACRONYMS.get(w.lower(), w.capitalize() if i == 0 or len(w) > 2 else w)
                    for i, w in enumerate(words) if w)


def _meta(item: pytest.Item) -> dict:
    merged: dict = {}
    # closest marker wins: iter_markers yields function-level first
    for mark in reversed(list(item.iter_markers("meta"))):
        merged.update(mark.kwargs)
    return merged


def _docstring(item: pytest.Item) -> str:
    doc = inspect.getdoc(getattr(item, "function", None)) or ""
    return " ".join(doc.split())


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
def module_name(item: pytest.Item) -> str:
    meta = _meta(item)
    if meta.get("module"):
        return str(meta["module"])
    mod = getattr(item, "module", None)
    if mod is not None and getattr(mod, "REPORT_MODULE", None):
        return mod.REPORT_MODULE
    stem = Path(str(item.path)).stem
    return humanize(re.sub(r"^test_(\d+_)?", "", stem))


@lru_cache(maxsize=256)
def _file_lines(path: str) -> tuple[str, ...]:
    try:
        return tuple(Path(path).read_text(encoding="utf-8").splitlines())
    except OSError:
        return ()


def _section_above(path: str, line: int) -> str:
    """Nearest ``# ------ name`` comment above a test definition."""
    lines = _file_lines(path)
    for idx in range(min(line, len(lines)) - 1, -1, -1):
        m = _SECTION.match(lines[idx])
        if m:
            return (m.group("a") or m.group("b") or "").strip()
    return ""


def feature_name(item: pytest.Item) -> str:
    meta = _meta(item)
    if meta.get("feature"):
        return str(meta["feature"])
    cls = getattr(item, "cls", None)
    if cls is not None:
        doc = inspect.getdoc(cls)
        return doc.splitlines()[0].rstrip(".") if doc else humanize(re.sub(r"^Test", "", cls.__name__))
    mod = getattr(item, "module", None)
    if mod is not None and getattr(mod, "REPORT_FEATURE", None):
        return mod.REPORT_FEATURE
    _, line = definition_location(item)
    section = _section_above(str(item.path), line)
    if section and section.lower() not in _TYPE_SECTIONS:
        return humanize(section)
    doc = inspect.getdoc(mod) if mod is not None else ""
    if doc:
        first = doc.strip().splitlines()[0].rstrip(".")
        return re.sub(r"\s+tests?$", "", first, flags=re.I)[:90]
    return module_name(item)


def definition_location(item: pytest.Item) -> tuple[str, int]:
    """(relative file, 1-based line of the ``def``)."""
    fspath, lineno, _ = item.location
    return fspath, (lineno or 0) + 1


def test_types(item: pytest.Item) -> tuple[str, list[str]]:
    meta = _meta(item)
    names = {m.name for m in item.iter_markers()}
    found: list[str] = []
    if meta.get("type"):
        explicit = meta["type"]
        found.extend([explicit] if isinstance(explicit, str) else list(explicit))
    for marker, label in TYPE_BY_MARKER:
        if marker in names and label not in found:
            found.append(label)
    if not found:
        found = ["Functional"]
    return found[0], found


def test_id(item: pytest.Item) -> tuple[str, bool]:
    """(id, auto_generated). Docstring id when present, else a stable hash id."""
    meta = _meta(item)
    if meta.get("id"):
        return str(meta["id"]), False
    doc = _docstring(item)
    m = _DOC_ID.match(doc)
    if m:
        return m.group("id"), False
    m = _DOC_PREFIX.match(doc)
    prefix = m.group("prefix") if m else re.sub(r"[^A-Z]", "", module_name(item).upper())[:6] or "TC"
    digest = hashlib.sha1(item.nodeid.split("[")[0].encode()).hexdigest()[:4].upper()
    return f"{prefix}-X{digest}", True


def test_name(item: pytest.Item) -> str:
    meta = _meta(item)
    if meta.get("name"):
        return str(meta["name"])
    base = getattr(item, "originalname", None) or item.name.split("[")[0]
    name = humanize(re.sub(r"^test_", "", base))
    param_id = _param_id(item)
    return f"{name} [{param_id}]" if param_id else name


def _param_id(item: pytest.Item) -> str:
    """Parametrize id without pytest-playwright's browser part (shown separately)."""
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return ""
    browser = callspec.params.get("browser_name")
    parts = callspec.id.split("-")
    if browser in parts:
        parts.remove(browser)
    return "-".join(parts)


def expected_result(item: pytest.Item) -> str:
    meta = _meta(item)
    if meta.get("expected"):
        return str(meta["expected"])
    doc = _docstring(item)
    for rx in (_DOC_ID, _DOC_PREFIX):
        m = rx.match(doc)
        if m:
            return m.group("rest").strip()
    return doc


def preconditions(item: pytest.Item) -> list[str]:
    out: list[str] = []
    meta = _meta(item)
    explicit = meta.get("preconditions")
    if explicit:
        out.extend([explicit] if isinstance(explicit, str) else list(explicit))
    mod = getattr(item, "module", None)
    out.extend(getattr(mod, "REPORT_PRECONDITIONS", []) or [])
    for fixture in getattr(item, "fixturenames", []):
        text = PRECONDITION_BY_FIXTURE.get(fixture)
        if text and text not in out:
            out.append(text)
    for mark in item.iter_markers("skipif"):
        reason = mark.kwargs.get("reason")
        if reason and f"Configured: {reason}" not in out:
            out.append(f"Configured: {reason}")
    return out


def jsonable(value: Any, limit: int = 500) -> Any:
    """Make a value safe for JSON / xdist transport."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + " …[truncated]"
    if isinstance(value, dict):
        return {str(k): jsonable(v, limit) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v, limit) for v in list(value)[:100]]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return jsonable(repr(value), limit)


def test_data(item: pytest.Item) -> dict:
    data: dict = {}
    meta = _meta(item)
    if isinstance(meta.get("data"), dict):
        data.update(meta["data"])
    callspec = getattr(item, "callspec", None)
    if callspec is not None:
        data.update({k: v for k, v in callspec.params.items() if k != "browser_name"})
    return jsonable(redact(data))


# --------------------------------------------------------------------------- #
# auto steps (from the test body)
# --------------------------------------------------------------------------- #
_ELEMENT_FNS = {"get_by_role", "get_by_label", "get_by_placeholder", "get_by_text",
                "get_by_test_id", "get_by_title", "locator", "field", "button"}
_STEP_VERBS = {"click": "Click", "dblclick": "Double-click", "fill": "Enter", "type": "Type",
               "press": "Press", "check": "Tick", "uncheck": "Untick", "hover": "Hover over",
               "select_option": "Select", "set_input_files": "Upload file to", "wait_for": "Wait for",
               "inner_text": "Read", "text_content": "Read", "is_visible": "Check visibility of",
               "is_enabled": "Check whether enabled:", "count": "Count"}
_RECEIVERS = {"page", "self", "lp", "dp", "bp", "api", "admin_api", "report", "context", "browser"}


def _arg_text(node: ast.AST) -> str:
    """Readable form of a call argument: settings.admin_email -> 'admin email'."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, str):
            return f'"{v[:40]}{"…" if len(v) > 40 else ""}"'
        return repr(v)
    if isinstance(node, ast.Attribute):
        return node.attr.replace("_", " ")
    if isinstance(node, ast.Name):
        return node.id.replace("_", " ")
    text = ast.unparse(node)
    return text if len(text) <= 40 else text[:39] + "…"


def _chain(node: ast.AST) -> list[tuple[str, ast.Call | None]]:
    """a.b(x).c(y) -> [('a', None), ('b', Call), ('c', Call)]."""
    out: list[tuple[str, ast.Call | None]] = []
    while True:
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                out.append((func.attr, node))
                node = func.value
            elif isinstance(func, ast.Name):
                out.append((func.id, node))
                break
            else:
                break
        elif isinstance(node, ast.Attribute):
            out.append((node.attr, None))
            node = node.value
        elif isinstance(node, ast.Name):
            out.append((node.id, None))
            break
        else:
            break
    return list(reversed(out))


def _call_text(node: ast.AST) -> str | None:
    chain = _chain(node)
    calls = [(n, c) for n, c in chain if c is not None]
    if not calls:
        return None
    final, call = calls[-1]
    # Playwright element actions: page.get_by_role("button", name="Sign in").click()
    elements = [(n, c) for n, c in calls if n in _ELEMENT_FNS]
    if elements and final not in _ELEMENT_FNS:
        from reporting.qa import describe_locator
        en, ec = elements[-1]
        if en in ("field", "button"):  # page-object helpers: field("Email")
            label = _arg_text(ec.args[0]) if ec.args else ""
            element = f"the {label} {'field' if en == 'field' else 'button'}".replace('"', "")
        else:
            element = describe_locator(ast.unparse(ec).replace("'", '"'))  # unparse uses '
        verb = _STEP_VERBS.get(final, humanize(final))
        args = ", ".join(_arg_text(a) for a in call.args)
        if final == "fill" and args:
            return f"Enter {args} in {element}"
        return f"{verb} {element}" + (f" ({args})" if args and final != "click" else "")
    if final in _STEP_VERBS and final not in ("count",) and call.args \
            and not any(n in ("keyboard", "mouse") for n, _ in chain) \
            and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        # page.click("#promo-banner") / page.fill("#email", "x")
        from reporting.qa import describe_locator
        element = describe_locator(f'locator("{call.args[0].value}")')
        if final == "fill" and len(call.args) > 1:
            return f"Enter {_arg_text(call.args[1])} in {element}"
        return f"{_STEP_VERBS[final]} {element}"
    if final == "wait_for_timeout" and call.args and isinstance(call.args[0], ast.Constant):
        return f"Wait {call.args[0].value / 1000:g} s"
    if final == "goto" and call.args:
        return f"Open {_arg_text(call.args[0])}"
    if final == "reload":
        return "Reload the page"
    if final == "wait_for_load_state":
        return "Wait for the page to finish loading"
    if final == "wait_for_url":
        return "Wait for the next page to open"
    # page objects: LoginPage(page).open() -> "Open Login page"
    def sentence(name: str) -> str:  # enter_credentials -> "Enter credentials"
        words_ = [(_ACRONYMS.get(w.lower(), w.lower())) for w in name.split()]
        return " ".join(words_)[:1].upper() + " ".join(words_)[1:]

    words = []
    for n, c in calls:
        if n[:1].isupper():
            words.append(sentence(re.sub(r"(?<!^)(?=[A-Z])", " ", n)))
        elif n not in _RECEIVERS:
            words.append(sentence(n.replace("_", " ")))
    if not words:
        return None
    args = [_arg_text(a) for a in call.args]
    args += [f"{k.arg.replace('_', ' ')}: {_arg_text(k.value)}" for k in call.keywords if k.arg]
    head = words[-1] + (f" ({words[0].lower()})" if len(words) > 1 else "")
    if len(words) > 1 and words[-1].lower() == "open":
        head = f"Open the {words[0].lower()}"
    return head + (f" — {', '.join(args)}" if args else "")


def describe_statement(stmt: ast.stmt, code: str) -> str:
    """Plain-English step title for one statement of a test body."""
    try:
        if isinstance(stmt, ast.Assert):
            if isinstance(stmt.msg, ast.Constant) and isinstance(stmt.msg.value, str):
                return f"Verify: {stmt.msg.value}"
            return f"Verify that {ast.unparse(stmt.test)[:120]}"
        if isinstance(stmt, ast.If):
            body = stmt.body[0] if stmt.body else None
            if body is not None and isinstance(body, ast.Expr) and _chain(body.value)[-1:] \
                    and _chain(body.value)[-1][0] == "skip":
                return f"Skip the test if {ast.unparse(stmt.test)[:100]}"
            return f"If {ast.unparse(stmt.test)[:100]}: …"
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            return f"For each {ast.unparse(stmt.target)} in {ast.unparse(stmt.iter)[:80]}: …"
        if isinstance(stmt, ast.Return):
            return "Finish the test here (condition already met)"
        value = getattr(stmt, "value", None)
        if isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)) and value is not None:
            text = _call_text(value)
            if text:
                return text[0].upper() + text[1:]
            if isinstance(stmt, ast.Assign):
                return f"Set {ast.unparse(stmt.targets[0])} = {ast.unparse(value)[:100]}"
    except Exception:  # noqa: BLE001 - fall back to the code itself
        pass
    return code


def _flatten(body: list[ast.stmt]) -> list[ast.stmt]:
    """Inline try / with bodies so their statements become steps of their own."""
    out: list[ast.stmt] = []
    for stmt in body:
        if isinstance(stmt, ast.Try):
            out.extend(_flatten(stmt.body))
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            out.extend(_flatten(stmt.body))
        else:
            out.append(stmt)
    return out


@lru_cache(maxsize=1024)
def _body_statements(func_key: str, source: str, first_line: int) -> tuple[tuple[int, int, str, str], ...]:
    """(start line, end line, plain-English title, code) per statement."""
    dedented = textwrap.dedent(source)
    try:
        tree = ast.parse(dedented)
    except SyntaxError:
        return ()
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None:
        return ()
    out = []
    for stmt in _flatten(fn.body):
        if isinstance(stmt, ast.Expr) and isinstance(getattr(stmt, "value", None), ast.Constant) \
                and isinstance(stmt.value.value, str):
            continue  # docstring
        segment = ast.get_source_segment(dedented, stmt) or ""
        code = " ".join(segment.split())
        if len(code) > 160:
            code = code[:157] + "..."
        start = first_line + stmt.lineno - 1
        end = first_line + (stmt.end_lineno or stmt.lineno) - 1
        out.append((start, end, describe_statement(stmt, code), code))
    return tuple(out)


def auto_steps(item: pytest.Item) -> list[tuple[int, int, str, str]]:
    func = getattr(item, "function", None)
    if func is None:
        return []
    try:
        lines, first = inspect.getsourcelines(func)
    except (OSError, TypeError):
        return []
    return list(_body_statements(f"{func.__module__}.{func.__qualname__}", "".join(lines), first))


def failing_line(item: pytest.Item, excinfo) -> int | None:
    """Line in the test function body where the exception surfaced."""
    if excinfo is None:
        return None
    code = getattr(getattr(item, "function", None), "__code__", None)
    try:
        for entry in reversed(excinfo.traceback):
            if code is not None and entry.frame.code.raw is code:
                return entry.lineno + 1
    except Exception:  # noqa: BLE001 - traceback shapes vary across plugins
        return None
    return None


# --------------------------------------------------------------------------- #
# failure classification
# --------------------------------------------------------------------------- #
def classify_failure(error_type: str, message: str, phase: str) -> str:
    text = f"{error_type} {message}".lower()
    if phase == "collect":
        return "Collection / Import"
    if "timeout" in text and ("exceeded" in text or "timeouterror" in text):
        return "Timeout"
    if "net::err" in text or "connectionerror" in text or "connection refused" in text \
            or "name or service not known" in text or "getaddrinfo" in text:
        return "Network / Connectivity"
    if "httperror" in text or "status code" in text or "jsondecodeerror" in text:
        return "API / HTTP"
    if "strict mode violation" in text or "waiting for locator" in text or "not visible" in text \
            or "element is not" in text or "no node found" in text:
        return "Locator / Element"
    if phase == "setup":
        return "Setup / Fixture"
    if phase == "teardown":
        return "Teardown"
    if "assertionerror" in text or error_type == "AssertionError":
        return "Assertion"
    return "Script Error"
