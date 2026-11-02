# Execution report

Every pytest run builds **one HTML page of its own**, `reports/Test_Report_<run_id>.html`
(for example `Test_Report_20261019-180333_full.html`). It covers every test case of
the run, with screenshots and failure videos embedded, so the single file is all
you open or share. **Earlier reports are never replaced or deleted.** Each run adds a
new file next to them. You don't run anything extra: run the tests and open the report.

```bash
pytest tests/test_login.py            # one module
pytest                                # everything (all test cases on one page)
pytest -n auto --reruns 2             # parallel + retries (retry analysis)
```

```
-------------------------- test report --------------------------
Report: C:\Excrow_Avanse_automation\reports\Test_Report_20261019-180333_full.html
(earlier reports are kept in C:\Excrow_Avanse_automation\reports)
```

The run folder `reports/runs/<run_id>/` holds the JSON, CSV, log and raw evidence.

### Features still in development

Mark tests of a module the developers have not finished with `pending_dev`:

```python
pytestmark = [pytest.mark.pending_dev(reason="Dashboard is still under development")]
```

The tests still run. A failure is shown as **Pending development** ("known gap, not a new
defect"), with what it found, and it does not fail the run. A pass is shown as passed.
Remove the marker once the feature is handed over for testing.

### Failures written for QA

Every failed, blocked or skipped test shows a QA box in place of the raw exception:

| Field | Example |
|---|---|
| Issue type | **Application defect** · **Needs review** · **Test script issue** · **Environment / configuration** · Not executed |
| What went wrong | *The "Sign in" button stayed disabled, so the test could not click it (30 s wait).* |
| Stopped at | *Step 3: Enter credentials — admin email, admin password* |
| Expected / Actual | the requirement (from the docstring) vs what happened, in plain words |
| Probable cause | e.g. *a required field, permission such as location, or consent is missing* |
| Next action | e.g. *Look at the screenshot: confirm whether the button should be enabled with this data.* |

The failure summary is grouped by issue type, so defects to raise are listed apart from
script or environment problems. The original error and stack trace are under
**Technical details (for developers)**. Steps are also written in plain words
(`Click the "Sign in" button`), with the code underneath. The rules live in `qa.py`.

Try it without UAT: `pytest examples/test_reporting_demo.py --reruns 1`. A
local demo app is used and some tests fail on purpose.

---

## What's in the report

| Area | Contents |
|---|---|
| Dashboard | Total / Passed / Failed / Blocked / Skipped, pass rate (of executed tests), duration, modules, browser, environment, build, executed by, CI link, host, stack |
| Charts | Result distribution (donut), results by module (stacked bars), failure categories, pass-rate trend over recent runs. Hover for details, click to filter |
| Failure summary | Failed and blocked tests grouped by category (Assertion, Timeout, Locator / Element, Network, API / HTTP, Setup / Fixture, Script Error…), with reason, thumbnail and trend (*new failure*, *still failing*, *fixed*) |
| Retry analysis | Retried tests, outcome of each attempt, flaky (passed on retry) vs consistent failure, tests unstable across recent runs |
| Test cases | Search, status chips, module / type filters, sorting, grouping by module, expand / collapse, paging for large suites |
| Test detail | **Overview** (failure box, stack trace, expected vs actual, preconditions, test data, execution facts, history) · **Steps** · **Evidence** (screenshots with full-screen viewer, video, Playwright trace) · **API calls** · **Console** · **Network** · **Logs** |
| Export | PDF (prints the dashboard and the filtered tests, fully expanded), HTML, CSV (filtered rows), JSON (everything) |
| Theme | Light and dark (follows the OS; the toggle is remembered) |

### The 25 fields per test case

| # | Field | Where it comes from |
|---|---|---|
| 1 | Test Case ID | docstring prefix `AUTH-001 — …`, or `@pytest.mark.meta(id=…)`. Otherwise a stable auto ID (shown in italics) |
| 2 | Name | function name + parametrize id, or `meta(name=…)` |
| 3 | Module | file name (`test_login.py` → *Login*), or `REPORT_MODULE = "…"` in the file |
| 4 | Feature / flow | nearest `# ----- section` comment above the test, or `meta(feature=…)`, or the module docstring |
| 5 | Type | markers (`security`, `api`, `boundary`, `negative`, `smoke`, `regression`, `ui`, `functional`, `validation`, `integration`…) or `meta(type=…)` |
| 6 | Preconditions | fixtures used (`logged_in_page` → "Admin user is signed in…"), `skipif` reasons, `meta(preconditions=[…])`, `report.precondition()` |
| 7 | Test data | parametrize values + `report.data(…)` (passwords, tokens and OTPs are redacted) |
| 8 | Steps | `report.step()` / `step()` blocks with timing. Without them, the statements of the test body are used, and the failing statement is marked |
| 9 | Expected result | docstring text after the ID, or `meta(expected=…)` / `report.expected()` |
| 10 | Actual result | failure message / skip reason / "Behaved as expected", or `report.actual()` |
| 11 | Status | PASS · FAIL · **BLOCKED** (setup / fixture / collection error) · SKIPPED |
| 12 | Failure reason | first line of the error + category |
| 13 | Stack trace | full pytest traceback (with assertion diff) |
| 14 | Screenshot | automatic on every failure (each open page, each attempt) |
| 15 | Video | kept for failed tests (`REPORT_VIDEO`) |
| 16–18 | Start / end / duration | setup start → teardown end |
| 19 | Browser | name + real version from the running browser |
| 20 | Environment | `REPORT_ENV`, otherwise worked out from `BASE_URL` (`uat-…` → UAT) |
| 21 | Executed by | `REPORT_EXECUTED_BY`, the CI user, or the OS user |
| 22 | Build / release | `BUILD_VERSION` / `APP_VERSION` / `RELEASE_VERSION`, or the CI build number |
| 23 | API logs | every `ApiClient` call (headers + bodies, redacted) and the browser's XHR / fetch calls |
| 24 | Console errors | `console.error` / `console.warn` and uncaught page errors |
| 25 | Network failures | failed requests and HTTP ≥ 400 responses |

---

## Folder structure

```
reports/
├── Test_Report_<run_id>.html     one page per run (all test cases, evidence embedded), all kept
├── history/history.json          run summaries + per-test statuses (trends)
└── runs/<YYYYMMDD-HHMMSS>_<scope>/   one folder per execution, e.g. 20261019-170512_login
    ├── json/results.json         everything (meta, summary, trend, tests)
    ├── json/summary.json         totals only (CI quality gates)
    ├── csv/results.csv           one row per test, opens in Excel
    ├── logs/execution.log        plain-text log of the run
    ├── screenshots/              <test>_a<attempt>_failure.png
    ├── videos/                   <test>_a<attempt>_page1.webm
    └── traces/                   <test>_a<attempt>_trace1.zip
```

The scope in the folder name shows what ran: a module name (`login`), up to
three modules joined with `+`, `N-modules`, or `full`. Every run is kept by default.
Set `REPORT_KEEP_RUNS=N` only if you want older runs and reports deleted. Screenshots and videos are embedded in
the page up to `REPORT_EMBED_MAX_MB` (screenshots first). Playwright traces are
zip files, so they stay in the run folder and the page links to them.

---

## Code layout

```
reporting/
├── __init__.py        public helpers: step, current, media_context_kwargs, requests_hook
├── plugin.py          pytest hooks + the `report` fixture (lifecycle, xdist, reruns)
├── recorder.py        TestRecorder - per-test state and the API used by tests
├── browser.py         PageWatcher - console / network / XHR listeners, screenshots, tracing, video
├── api_log.py         requests hook + log-entry builders (redacted)
├── metadata.py        infers ID / module / feature / type / preconditions / plain-English steps, classifies failures
├── qa.py              QA view of each result: issue type, what went wrong, cause, next action
├── models.py          TestRecord (the shape of one test in results.json)
├── config.py          REPORT_* settings + run metadata (env, build, CI, user)
├── writers.py         JSON / CSV / log / the single HTML page (evidence embedded) / history / retention
└── templates/         report.html, report.css, report.js (charts are hand-written SVG, no CDN)
```

### How it runs

| Phase | What happens |
|---|---|
| `pytest_configure` | creates `reports/runs/<run_id>/`, registers the plugin, passes the folder to xdist workers through an env var |
| setup | creates (or resets, on a rerun) the test's `TestRecorder` |
| call (before) | attaches listeners and starts tracing on every `Page` / `BrowserContext` fixture. Popups are followed |
| call (after) | on failure: screenshots of every open page, keeps the trace. Notes the video path |
| teardown | contexts are closed by now: keeps or deletes the video and builds the record on the report (`report.exec_record`) |
| `pytest_runtest_logreport` | the controller collects records. This works under xdist because report attributes are serialised |
| `pytest_sessionfinish` | adds the QA analysis, writes `Test_Report.html` and the run archive, updates history, prunes old runs |

A failure inside the reporter only produces a warning. It never fails a test or the run.

---

## Integration guide (already done in this repo)

1. **Register the plugin** in the root `conftest.py`:
   ```python
   pytest_plugins = ["reporting.plugin"]
   ```
2. **Video recording**: merge the media args into every browser context:
   ```python
   def _context_kwargs() -> dict:
       from reporting.plugin import media_context_kwargs
       return {**media_context_kwargs(), "locale": "en-IN", ...}
   ```
   (Use this rather than pytest-playwright's `--video`, so videos land in the run folder.)
3. **API logging**: add the hook to any `requests.Session`:
   ```python
   from reporting.api_log import requests_hook
   self.session.hooks["response"].append(requests_hook)
   ```
4. Nothing else is needed. Existing tests get a full report as they are.

### Enriching a test (optional)

```python
import pytest
from reporting import step

@pytest.mark.smoke
@pytest.mark.meta(id="WBEN-004", feature="Add Beneficiary", type="Functional",
                  preconditions=["Beneficiary module enabled for the admin role"],
                  expected="Beneficiary is saved and listed")
def test_add_valid_beneficiary(logged_in_page, report):
    data = new_beneficiary()
    report.data(beneficiary=data)                 # shown under Test data (secrets redacted)
    bp = BeneficiaryPage(logged_in_page)
    with report.step("Open Add Beneficiary form"):
        bp.open().open_add_form()
    with report.step("Fill and submit"):
        bp.fill_form(data); bp.submit_add()
    report.actual(bp.toast_text())                # overrides the default actual result
    report.screenshot("after submit")             # extra screenshot, not only on failure
```

| `report.` method | Purpose |
|---|---|
| `step(title)` | timed, nestable step. A failing step is marked with its error |
| `meta(id=, name=, module=, feature=, type=, expected=)` | override inferred metadata at runtime |
| `precondition(text)` / `data(**kv)` / `expected(text)` / `actual(text)` | design fields |
| `attach_page(page_or_context)` | capture a page the test created itself (e.g. `browser.new_context()` inside the test) |
| `screenshot(title, page=None)` / `attach_file(path, title)` | extra evidence |
| `log_api(response_or_dict)` | log a call made outside `ApiClient` |

From page objects or helpers, `from reporting import step`. It does nothing outside a test.

### Reusing it in another project

Copy `reporting/` and do steps 1–3. Then change the two project-specific
imports: `config.settings` (base URL and browser, in `config.py` / `plugin.py`)
and `mcp_server.redact` (the redaction helper). Adjust
`PRECONDITION_BY_FIXTURE` and `TYPE_BY_MARKER` in `metadata.py` to match your
fixtures and markers.

---

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `REPORT_ENABLED` | `1` | `0` disables the report (or pass `--no-exec-report`) |
| `REPORT_DIR` | `reports` | output root |
| `REPORT_TITLE` | SprintEXcrow Test Execution Report | header title (or `--report-title`) |
| `REPORT_SCREENSHOTS` | `only-on-failure` | `on` = also at the end of passing tests, `off` |
| `REPORT_FULL_PAGE` | `1` | full-page screenshots (falls back to viewport) |
| `REPORT_VIDEO` | `retain-on-failure` | `on`, `off` |
| `REPORT_TRACE` | `retain-on-failure` | `on`, `off` |
| `REPORT_KEEP_RUNS` | `0` | 0 = keep every run and report; N = keep only the newest N |
| `REPORT_HISTORY_SIZE` | `50` | runs kept in history for trends |
| `REPORT_EMBED_MAX_MB` | `60` | screenshots / videos embedded in the page (the rest are linked) |
| `REPORT_ENV` | from `BASE_URL` | environment label |
| `BUILD_VERSION` | CI build no. / `not set` | build or release under test |
| `REPORT_EXECUTED_BY` | CI user / OS user | who ran it |

Turning video and trace `off` speeds up large local runs. Screenshots on failure
always stay on unless `REPORT_SCREENSHOTS=off`.

---

## CI/CD

The report needs no server or CDN. Publish `reports/Test_Report_*.html` as an artifact.
Each is a single file.

**GitHub Actions**
```yaml
- name: Run tests
  run: pytest -n auto --reruns 2
  env:
    BUILD_VERSION: ${{ github.ref_name }}-${{ github.run_number }}
    REPORT_ENV: UAT
- name: Upload execution report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: test-report
    path: reports/Test_Report_*.html
```

**Jenkins**: `archiveArtifacts artifacts: 'reports/Test_Report_*.html'`, or publish it with the
HTML Publisher plugin (`reportDir: 'reports'`, `reportFiles: 'Test_Report_*.html'`).
The plugin's default CSP blocks inline scripts, so allow them or use the artifact link.

**Azure DevOps / GitLab**: publish `reports/Test_Report_*.html` as a pipeline or job artifact.

**Quality gate**: read the newest run's `json/summary.json`:
```bash
python -c "import glob,json,sys; f=sorted(glob.glob('reports/runs/*/json/summary.json'))[-1]; s=json.load(open(f))['summary']; sys.exit(0 if s['pass_pct']>=95 else 1)"
```

To keep trends across CI runs, cache or restore `reports/history/` between builds.

---

## Notes and limits

- Browser XHR / fetch calls are logged with method, URL, status and request body. Response
  bodies are captured only for `ApiClient` (`requests`) calls, because reading a body inside a
  Playwright event handler can block the test.
- Console, network and trace capture start when the test body starts. Problems inside
  fixtures (for example, the cached admin login) are reported as **BLOCKED**, with a screenshot.
- Pages a test creates itself with `browser.new_context()` are captured once you call
  `report.attach_page(page)`.
- **Export → HTML** saves the page with its embedded screenshots and videos. Only traces
  (and videos above `REPORT_EMBED_MAX_MB`) stay in the run folder.
- The pytest-html report was removed from `pytest.ini`, so `Test_Report_<run_id>.html` is the only report page per run.
