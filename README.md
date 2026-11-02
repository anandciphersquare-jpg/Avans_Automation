# SprintEXcrow / Awanse Console — Playwright + pytest automation

Automation for the **currently-live** modules of the SprintEXcrow (Awanse)
console, driven by the test cases in the QA workbooks. Starts at **login** and
is split **one file per module**, covering positive, negative, functional,
boundary, **API** and **security** testing.

## Layout

```
sprintexcrow_automation/
├── config/settings.py          # all config from env (URLs, creds, OTP, endpoints)
├── api/api_client.py           # requests-based API client (auth + verbs)
├── pages/                      # Page Object Model (one per screen)
│   ├── base_page.py
│   ├── login_page.py           # login, location gate, OTP, forgot password
│   ├── dashboard_page.py       # sidebar + live/hidden menu map
│   ├── beneficiary_page.py     # Add Beneficiary (Workflow 4)
│   ├── transfers_page.py       # approver journey (Workflows 1 & 2)
│   ├── user_management_page.py # Roles + Users (Workflow 6)
│   ├── audit_trail_page.py
│   └── change_password_page.py
├── utils/                      # otp provider, data factory, security helpers
├── conftest.py                 # fixtures: browser/context, auth session, api
├── tests/                      # one test module per feature
│   ├── test_login.py
│   ├── test_dashboard.py
│   ├── test_beneficiary.py
│   ├── test_transfers.py
│   ├── test_user_management.py
│   ├── test_audit_trail.py
│   ├── test_change_password_signout.py
│   ├── test_security.py        # UI lockdown / storage / console / masking
│   └── test_api_security.py    # API auth, IDOR, mass-assignment, headers, injection
├── reporting/                  # execution report plugin (see reporting/README.md)
├── examples/                   # report demo against a local app (not part of `pytest`)
├── pytest.ini                  # markers + html report
├── requirements.txt
└── .env.example
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # one-time browser download

cp .env.example .env               # then fill it in (see below)
```

### `.env` essentials
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — **rotate the exposed UAT password first**, then put the new one here.
- `USER_EMAIL` / `USER_PASSWORD` — a limited-role user (needed for access-control tests).
- `OTP_STRATEGY` — `imap` (read from Gmail), `static` (UAT test OTP in `OTP_STATIC`), `api` (mailbox hook in `OTP_API_URL`),
  or `manual`: run with `--headed`, then type the mailed code into the browser and click Verify. An orange banner
  shows when it is waiting, for up to `OTP_MANUAL_TIMEOUT_S` (default 180 s).
- `GEO_LAT` / `GEO_LNG` — geolocation is granted automatically so the Allow-Location gate passes.

## Run

```bash
pytest                               # everything, all test cases in reports/Test_Report_<run_id>.html
pytest tests/test_login.py           # just login
pytest tests/test_login.py --headed  # watch it run (needed for OTP_STRATEGY=manual)
pytest -m "security"                 # only security checks
pytest -m "api"                      # only API tests (no browser)
pytest -m "smoke"                    # critical path
pytest -n auto                       # parallel (pytest-xdist)
HEADLESS=false pytest tests/test_login.py   # watch it run
```

Markers: `smoke functional positive negative boundary security authorization api ui auth regression`
(plus `validation`, `integration` and `meta(...)` from the report plugin).

### Execution report
Every run writes its own page, `reports/Test_Report_<run_id>.html`, with every test case of the run.
Earlier reports are never replaced. Screenshots and videos are embedded, so each file is a complete report.
Modules the developers haven't finished (currently the Dashboard) are marked `pending_dev`
and reported as *Pending development*, not as defects.
Failures are written for QA: issue type (application defect, needs review, script, environment),
what went wrong, the step where it stopped, probable cause and next action. The raw error is
kept under "Technical details". The page also has a dashboard, charts, retry analysis, plain-English
steps, API, console and network logs, and PDF/HTML/CSV/JSON export.
To see it without UAT, run `pytest examples/test_reporting_demo.py --reruns 1`.
Setup, configuration and CI usage are in [reporting/README.md](reporting/README.md).

## What to confirm against the live app
This framework was written from the **Focused Workflow Guide** and the sidebar
screenshot, not the live DOM. Two things are centralised so they are quick to
adjust:
- **Selectors** — all in the `pages/*.py` objects (role/label/text based). Fix a
  locator there once and every test follows.
- **API endpoints** — all in `config/settings.py` (`Endpoints`). Override any via
  env (`EP_LOGIN`, `EP_BENEFICIARIES`, …). API tests **skip** (not fail) when a
  path returns 404, so an unconfigured endpoint never produces a false negative.

## MCP testing server (`mcp_server/`)

An MCP server that exposes this framework as tools, so Claude Code / Claude
Desktop (or any MCP client) can run and explore tests conversationally. It
reuses `config/`, `api/`, `pages/` and `utils/`, so `.env` settings, endpoint
overrides, selectors and payload lists apply to both pytest and the server.

```bash
python mcp_server/server.py          # stdio (what .mcp.json uses)
python mcp_server/server.py --http   # streamable HTTP on 127.0.0.1:8000/mcp
```

Claude Code picks it up automatically from `.mcp.json` in this folder (approve
it on first use, check with `/mcp`). For Claude Desktop add the same `command`
and `args` with an absolute path to `server.py`.

| Area | Tools |
|---|---|
| Suites | `list_tests`, `run_tests` (marker / file / -k, parallel, reruns), `get_last_test_report` |
| API | `api_login`, `api_request` (status / body / JSON-Schema contract asserts), `api_probe_endpoints` |
| API security | `api_security_scan` (authn, tampered token, headers, CORS, TRACE, SQLi, XSS reflection, stack traces, data leakage), `api_rate_limit_check` |
| API performance | `api_performance_test` (p50–p99, rps, error rate; capped at 500 req / 20 concurrent) |
| Functional UI | `ui_start`, `ui_login`, `ui_submit_otp`, `ui_navigate`, `ui_snapshot`, `ui_click`, `ui_fill`, `ui_select`, `ui_press`, `ui_assert`, `ui_screenshot`, `ui_get_logs`, `ui_check_menu_access`, `ui_close` |
| UI / UX | `ux_accessibility_audit` (axe-core, WCAG 2.x), `ux_responsive_check`, `ux_performance_metrics` (TTFB/FCP/LCP/CLS), `ux_broken_links`, `ux_visual_regression` (baselines in `reports/baselines/`) |
| UI security | `ui_security_scan` (cookies, storage, console, mixed content), `ui_input_probe` (XSS / SQLi / invalid / boundary presets) |
| Data | `get_test_config`, `generate_test_data` |

Prompts: `full_test_pass` (runs every test type and reports) and `exploratory_ui_test`.

UI element targets accept `label=`, `placeholder=`, `button=`, `link=`, `text=`,
`field=`, `testid=` or any Playwright/CSS selector. With `OTP_STRATEGY=manual`,
`ui_login` stops at the OTP step; give the code to `ui_submit_otp`. A
successful admin UI login refreshes `.auth/admin_state.json`, which pytest
reuses. Responses are scrubbed of tokens/passwords/OTPs before they reach the model.

## Notes
- Credentials are **never** hardcoded — env only.
- Injection payloads are **non-destructive** (boolean/format based); tests assert
  the app *rejects* them. Do not add destructive DDL against shared UAT data.
- The authenticated session is established once (full login incl. OTP) and reused
  across modules via Playwright `storage_state` for speed.
