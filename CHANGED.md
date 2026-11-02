# Change Log

Every change to this project is recorded here, newest first, with date and time (IST).

---

## 2026-10-22 15:55 IST — Test case sheet for one execution report (360 tests)

**Why:** The user asked for test cases matching the 21-Oct 15:44 report (360 tests), in the same format, as a separate file.

**Added**
- `tools/report_test_cases.py <run>` → `reports/Report_Test_Cases_<run>__<timestamp>.xlsx`. It has one row per test executed in that run, including data-set variants (IDs numbered `.1`, `.2` …).
  - Each row shows its own data set in Test Data.
  - Actual Result and Status are exactly as in that report.
  - For a failure that passed on a later re-run, Notes give the re-run time.
  - It reuses `build_rows_for_run()` and `write_xlsx()` from `tools/test_case_sheet.py`.

**Result** (`Report_Test_Cases_20261021-154453_6-modules__20261022-155320.xlsx`): 360 tests, 334 Pass, 21 Fail, 5 Skipped. This matches the HTML report.
- 12 of the 21 failures passed on a later re-run. The test was corrected in each case: SES-010, SES-011, AUTH-API-012 ×3, AUTH-API-036, AUTH-API-041 ×4, BEN-UI-014 and API-017.
- The other 9 are the open Beneficiary defects: BEN-UI-042 ×3, BEN-UI-061, API-BEN-013 ×2, API-BEN-020, API-BEN-038 and API-BEN-046.

---

## 2026-10-22 11:05 IST — Test case sheet (Excel) built from the run reports

**Why:** The user asked for a test case sheet with these columns: Test Case ID, Feature / Sub-Module, Test Scenario, Test Type, Priority, Severity, Preconditions, Test Steps, Test Data, Expected Result, Actual Result, Status and Notes. It had to follow the reports, and the module had to be named in easy English.

**Added**
- `docs/test_case_details/<test file>.json`: plain-English sub-module, scenario, type, priority, severity, preconditions, steps, test data and expected result for every test case ID (197 IDs over 12 test files). These were written from the real test code and page objects.
- `tools/test_case_sheet.py` → `reports/Test_Cases_<timestamp>.xlsx`: one row per test case ID with an easy-English **Module** column. The Actual Result and Status come from the **latest real result** of each test in `reports/runs/*/json/results.json`.
  - If any data set fails, the whole case is Fail, and the failing ones are named with the real "Actual" line.
  - Notes carry the last run time, the QA verdict and the hint.
  - Dashboard and User Management cases are marked **Pending**, not defects.
  - A Summary sheet gives the counts per module. Every run writes a new file.

**Result** (`Test_Cases_20261022-110317.xlsx`): 197 cases. 171 Pass, 10 Fail, 9 Skipped, 7 Pending.
- Fails: BEN-UI-042, BEN-UI-061, API-BEN-013, API-BEN-020, API-BEN-038, API-BEN-046, WSEC-001, WTRN-004/005, WTRN-014, WAUD-004.
- The last four were last run in the 2026-10-21 15:05 full run.

---

## 2026-10-21 16:20 IST — Authentication & Session suite (UI + API), test case IDs everywhere, failure messages for dev/QA

**Why:** The user asked for complete Authentication & Session, Login and Add Beneficiary test cases with test case IDs, plus API and security testing, with error messages that developers and QA can both understand.

**Learned from the live app (UAT)**
- `/api/v1/auth/*`: login (`{email,password,clientGeo}`; location is mandatory) returns `otpRequired` + `challengeReference` and **no token**. After that come `verify-otp` and `resend-otp`, then `me`, `logout`, `change-password`, `forgot-password` and `reset-password[/verify]`.
- Wrong credentials and an unknown email both get 401 "Invalid email or password." (identical, so there is no enumeration).
- The token is HS-signed, lives 30 minutes, and sits in sessionStorage only. Logout revokes it on the server.
- The server checks the current password before the new-password rule.

**Added**
- `tests/test_login.py` (rewritten, AUTH-UI-001…072, 55 runs): layout, password masking and URL, mandatory fields, email format, wrong password, enumeration, SQLi and XSS. Location denied and granted. OTP step: masked destination, 6 boxes, Verify only at 6 digits, digits only, paste, wrong code, resend countdown, "Use a different account", refresh, skipping the OTP by URL. Full sign-in, the `next` redirect, open-redirect (3 payloads), protected pages (6), tab-scoped session, forged sessions (3), token storage, cookies, and the forgot password page, validation and generic answer.
- `tests/test_auth_api.py` (new, AUTH-API-001…061, 71 runs): login validation, location, malformed JSON, invalid location values, SQLi, oversized input, content type, verbs, OTP-not-token, verify/resend OTP, `/auth/me`, 401 without a token, forged, alg=none and tampered-claims tokens, JWT claims, logout revoking the token (own sign-in), change-password refusals, forgot/reset password including enumeration, headers, CORS and request id. **Opt-in** (`RUN_LOCKOUT_TESTS=1`): OTP guessing, login rate limit and reset-mail flood.
- `tests/test_change_password_signout.py` (rewritten, SES-001…012): layout, empty form, 6 password-rule cases, 8/12-character limits (request faked), mismatch, new = current, wrong current, back. Sign out ends the session, revokes the token, and the Back button and URLs lead to sign-in. Sign-out tests use their **own** session (`own_session_page`).
- `utils/checks.py`: `check()` / `expect_api()` give every failure the same layout: **[TEST-ID] title / Request / Expected / Actual / Field errors / Request-ID / Hint**. The test ID is filled in automatically by an autouse fixture in conftest.
- `tools/test_catalogue.py` writes `docs/TEST_CASES.md`: 198 test cases and 415 runs, each with its ID, title, type and variants.
- BEN-UI-016: a bank error on Check status is shown to the user (simulated).

**Changed**
- `config/settings.py`: every auth endpoint is now `/api/v1/…` (confirmed). Added `resend_otp`, `reset_password[_verify]` and `navigation`. Guesses for modules not yet live also use `/api/v1`.
- `conftest.py`: `admin_api` uses the UI-session token, because API login needs the OTP; the 19 API-security tests that always skipped now run. `admin_token` validates the saved token with `/auth/me` and signs in again in a clean context when it has expired or been revoked. `logged_in_page` also signs in again in a clean context. New fixture: `own_session_page`.
- `api/api_client.py`: `login()` sends `clientGeo` and explains the OTP requirement.
- `pages/login_page.py`: real ids and texts (`#email`, `#password`, "Verify and sign in", OTP alert, location notice, resend, "Use a different account"). The Gmail OTP sign-in retries with the next newer code when the app says "That code is not valid". The previous full run lost tests to a late OTP mail from an earlier OTP-step test.
- `utils/gmail_web.py`: `wait_for_new_code(exclude=…)`.
- `pages/change_password_page.py`: real ids. Sign out is a button.
- Beneficiary API/UI checks now use the standard messages. A wrongly created record is named with its code and reference.
- `tests/test_api_security.py`: API-015 moved to AUTH-API-060 (opt-in). API-017 checks account fields only. Old auto-generated IDs replaced: AUTH-UI-080, API-002, WSEC-002, WSEC-009, WDSH-004.

**Results (headed)**
- Full suite `20261021-150529` (code before this change): 213 passed, 18 failed, 37 skipped, 11 xfail, 19 xpass.
- 6 modules `20261021-154453`: 334 passed, 21 failed, 5 skipped. Ten failures were test assumptions, fixed and re-run green (`20261021-161001`, `…161339`): the `user.reset_password` permission name, 401-not-405 for verbs, server rule order, a mobile matched as an account, sign-out restore, a navigation race, and enquiry on a QA payee.
- **No Authentication & Session defect found.** Notes: other verbs on `/auth/login` return 401 rather than 405, and there is no session cookie (the token is in sessionStorage by design).
- **Open defects (all Beneficiary)**, unchanged: non-digits silently stripped from the account number (3), duplicate code answered with BUSINESS_RULE_VIOLATION instead of DUPLICATE_REFERENCE, server accepts `abc@x`, server accepts an account number with a space, a `<script>` name reaches the bank and gives 502, security headers sent twice.

---

## 2026-10-21 13:10 IST — Beneficiary module: full UI + API suite on the real screen; User Management marked pending

**Why:** The user asked for complete beneficiary testing: positive, negative, security and API. That covers mandatory and optional fields, Account number vs Confirm account number, duplicate beneficiary code, and the full screen. The old beneficiary tests used guessed locators (Business Name, Branch…) that do not exist, so every one of them failed in the 11:44 headed run. User Management is still with the developers.

**Learned from the live app (UAT)**
- The form fields are Beneficiary code (system-issued, read-only, new on every opening), name, account number, confirm account number (paste blocked), IFSC (typed in upper case), mobile **(optional)** and email **(mandatory)**. The submit button is "Register with bank". The form shows one validation message at a time.
- The API is under **`/api/v1/`**: `GET/POST /beneficiaries`, `POST /beneficiaries/code`, `GET /beneficiaries/{ref}`, `POST …/enquiry`, `PATCH …/toggle-status`. API login needs the email OTP, which is why the old `admin_api` tests skip.
- The access token lasts about 30 minutes.
- Re-sending the same body is an idempotent retry: the server returns the same beneficiary.

**Added**
- `tests/test_beneficiary.py` (rewritten, 85 cases) covers the full screen: layout, columns, masking, search, reset, injection in search, details panel, Block/Unblock, Check status, close. It also covers form layout, mandatory and optional markers, the read-only code, each mandatory field, whitespace-only values, optional mobile, payload, mobile, email, account length 9/18, non-digits, five confirm-account mismatch variants, paste block, autocomplete, IFSC, one real end-to-end registration, the duplicate code (request code swapped for an existing one) and XSS.
- `tests/test_beneficiary_api.py` (new, 106 cases) covers list, detail, search, code issue, 404s, malformed references, the empty body naming all mandatory fields, each mandatory field missing or blank, 23 invalid field values, wrong JSON types, malformed JSON, create plus idempotent retry plus duplicate code, the duplicate of an existing code, code case/space variants, and the same account+IFSC twice. Security cases: 401 on every endpoint, bad, forged and alg=none tokens, masking, sensitive keys, SQLi, markup/SQL in name, mass assignment, verbs, headers, duplicated headers, CORS, page-size cap, paging and code-issue volume.
- `conftest.py`: `admin_token` (the UI-session token, renewed by a fresh sign-in when it is near expiry) and `ui_token_api`.
- `config/settings.py`: `beneficiaries` → `/api/v1/beneficiaries`, plus `beneficiary_code` and `auth_me`.
- `utils/data_factory.py`: `new_beneficiary()` matches the real form and `beneficiary_payload()` builds the API body. Real branch IFSCs are used, and names start with "QA Auto".

**Changed**
- `pages/beneficiary_page.py` was rebuilt on the real ids and texts. It adds `capture_create()`, which fakes the create call so most form checks create nothing, and `rewrite_create_code()` for the duplicate-code test.
- `utils/assertions.py`: a comma-joined `nosniff, nosniff` now counts as present. Duplication is reported by its own test.
- `tests/test_user_management.py`: `pending_dev("User Management is still under development…")`.

**Results (headed)**
- Run `20261021-123918`: 175 passed, 15 failed. Five of the failures were test assumptions (now fixed): the idempotent retry, mobiles matching the account regex, a 403 from the firewall, numeric JSON coercion, and search matching a stored payload.
- Re-run `20261021-130222`: **10 failures remain, all application defects**:
  1. The UI silently strips non-digits from the account number (`5010abc0123456` → `50100123456`, dashes, `@`). 3 cases.
  2. A duplicate beneficiary code returns 422 `BUSINESS_RULE_VIOLATION` "…bank details are incomplete. Contact support". It should be `DUPLICATE_REFERENCE`, so the form never shows the duplicate message or issues a fresh code. 3 cases (UI, API new code, API existing code).
  3. The server accepts email `abc@x` (the UI rejects it).
  4. The server accepts an account number with a space.
  5. The server does not validate the name: `<script>…` is stored and forwarded to the bank (Axis 400), and the API returns 502.
  6. Security headers are sent twice (`X-Frame-Options: DENY, DENY`, `nosniff, nosniff`, two CSPs).
- Observation: mobile numbers are returned in full in the list API.

**Test data created on UAT:** about 10 "QA Auto" beneficiaries (PENDING) and 1 named `<script>alert(1)</script>` (REJECTED by the bank). The server-validation tests create a record only when the server wrongly accepts the input.

---

## 2026-10-19 19:00 IST — Session reuse fixed, Dashboard marked pending, every report kept

**Why:** In the first full run, 64 tests failed. Most of them opened on the Sign-in page, so they were not real defects. The Dashboard is still under development. Earlier reports had to be kept, not replaced.

**Root cause of the mass failures:** the app keeps its login in **sessionStorage** (`sprintexcrow.session`). That storage belongs to one tab: Playwright's `storage_state` doesn't save it, and every new tab opens `/login`. The saved `.auth/admin_state.json` was empty, so every `logged_in_page` test ran logged out.

**Added**
- `utils/app_session.py` — saves sessionStorage next to the storage state (`.auth/admin_state_session.json`) and injects it into new contexts before the app loads. Also has `is_signed_in()`.
- `pending_dev(reason)` marker (`reporting/plugin.py`). The test still runs. A failure is reported as **Pending development** with the gap it found, and it does not fail the run. The failure summary lists these as their own group.

**Changed**
- `conftest.py` — the admin session is saved with sessionStorage and reused only while the app still accepts it. `logged_in_page` opens the dashboard and waits for the side menu, signing in again if the session expired.
- `pages/dashboard_page.py` — `is_menu_enabled()` waits up to 15 s for the menu, which renders after the dashboard data loads.
- `tests/test_dashboard.py` — `pending_dev("Dashboard is still under development…")`.
- `reporting/writers.py` / `config.py` / `plugin.py` — each run writes **`reports/Test_Report_<run_id>.html`**, never overwritten. `REPORT_KEEP_RUNS` now defaults to `0` (keep everything). The terminal prints the new report's path.
- `reporting/qa.py` — "Pending development" verdict. A test that needs a signed-in admin and failed on `/login` is reported as "session was not active", not as a module defect. Records now hold the open page URLs at failure (`page_urls`).
- `utils/data_factory.py` — beneficiary / user emails are `qa.*@example.com` (reserved domain), so UAT invitations never reach a real person. Faker's `fake.email()` could produce real-looking `@gmail.com` addresses.
- Docs: `README.md`, `reporting/README.md`, `.env.example`, `pytest.ini`.

**Migration**
- Built a dated report page for every earlier run that had results (14 pages, `reports/Test_Report_20261019-*.html`). Removed the duplicate undated `Test_Report.html` and the copies inside run folders. Run folders and older `runs/*/html/report.html` pages are kept.

**Status / open items**
- Dashboard re-run headed: 17 passed, 5 pending (Sign out not a menu link; Approvals / Deposits / Master Escrow / QR Settlements reachable by direct URL), 1 skipped. The run finished green.
- 19 API tests skip: `Admin API login failed … 401` at `/api/auth/…`. The API login path or flow (OTP) needs confirming.
- Full headed suite re-run in progress.

---

## 2026-10-19 17:55 IST — OTP read from Gmail in the browser (only the 2-step code is manual)

**Why:** The tester should not type the SprintEXcrow OTP. The automation signs in to Gmail, the tester enters only Google's 2-step verification code, and the newest OTP is copied into the login. Report errors had to be clearer.

**Added**
- `utils/gmail_web.py` — opens Gmail in a separate tab of the test browser. Types MAIL_USER, and MAIL_PASSWORD if set. Waits for the tester to complete 2-step verification (banner plus terminal message, `GMAIL_LOGIN_TIMEOUT_S`, default 300 s). Saves the Google session to `GMAIL_STATE` (`.auth/gmail_state.json`, git-ignored) so later runs skip it. Notes the newest "Your SprintEXcrow sign-in code" mail before Sign in, waits for a newer one, opens it and returns the 6-digit code. `python -m utils.gmail_web login` signs in once with the installed Chrome if Google blocks the automation browser.
- Settings `MAIL_PASSWORD`, `GMAIL_STATE`, `GMAIL_LOGIN_TIMEOUT_S`. New strategy `OTP_STRATEGY=gmail_web` (now the default in `.env`).

**Changed**
- `pages/login_page.py` — `login()` prepares Gmail before clicking Sign in; `complete_otp()` enters the code read from Gmail. New `LoginError` with plain messages: OTP screen did not appear, OTP entered but the app stayed on login, manual OTP not entered.
- `reporting/qa.py` — rules for Gmail and login errors (2-step not completed, Google blocked sign-in, wrong Gmail password, no new OTP mail, mail without a code, OTP rejected) and for a browser closed during a test.
- `conftest.py` — clearer skip text when the shared admin or non-admin login fails.
- `utils/otp.py` — `gmail_web` through `get_otp()` (MCP) gives a clear error.
- `.env`, `.env.example` — new keys.

**Fix (18:05 IST)** — the run sat on Google's "Email or phone" screen because the email was never typed. Google's page has more than one email input, so the fill failed and the error was swallowed. `utils/gmail_web.py` now reacts to whichever screen Google shows: email → password → account chooser → "Not now" / "Skip" prompts, logging each action to the terminal. Error checks (account not found, wrong password, browser blocked) run before each action. The OTP-mail search now uses only rows whose subject is the OTP subject. Before this, the inbox list was read before the search loaded, and a "Reset your SprintEXcrow password" mail was picked.

**Status / open items**
- `MAIL_PASSWORD` set in `.env`; it had been placed in `MAIL_APP_PASSWORD`, which only IMAP uses.
- Gmail sign-in checked live: email and password typed automatically, 2-step code entered by the tester, session saved to `.auth/gmail_state.json`.
- Full headed suite run (`pytest --headed`) in progress.

---

## 2026-10-19 17:35 IST — Single-page report, QA-style failures, manual OTP in headed mode

**Why:** One report page holding every test case (no hopping between links). Errors written so QA can act on them. OTP typed by hand in a headed browser until the Gmail App Password exists.

**Added**
- `reporting/qa.py` — turns each non-passing result into Issue type (Application defect / Needs review / Test script issue / Environment / configuration / Not executed), What went wrong, Stopped at, Expected, Actual, Probable cause, Next action. Reads Playwright call logs (disabled, hidden, missing or covered elements, navigation timeouts), `expect()` failures, assertions, HTTP status codes, network errors and missing `.env` settings.
- `utils/console.py` — prints to the terminal while pytest captures output (used for the manual OTP prompt).
- `OTP_MANUAL_TIMEOUT_S` (default 180) in `config/settings.py`, `.env`, `.env.example`.

**Changed**
- `reporting/writers.py` — the only page is `reports/Test_Report.html`, with screenshots and failure videos embedded as data URIs (`REPORT_EMBED_MAX_MB`, default 60). A copy is archived in `runs/<id>/`. Removed `index.html`, `latest-report.html`, `latest/` and the run's `html/` folder. CSV and log now include the QA columns.
- `reporting/templates/report.js|css|html` — QA box on every failed, blocked or skipped test; raw error and stack trace moved into a collapsed "Technical details (for developers)". The failure summary is grouped by issue type, with "What went wrong" and "Next action" columns. The dashboard chart shows issue types. Steps are in plain words, with the code underneath.
- `reporting/metadata.py` — auto-steps are described in plain English (`Click the "Sign in" button`, `Enter "a@b.com" in the Email field`, `Verify: <assert message>`), and `try` / `with` bodies are expanded into steps.
- `reporting/plugin.py` — the terminal prints one line: `Report: …\Test_Report.html`. The header records headed / headless from `--headed`.
- `pytest.ini` — removed pytest-html (`--html=reports/report.html`), so there is one report.
- `pages/login_page.py` — `OTP_STRATEGY=manual` waits for the tester to type the OTP in the browser and click Verify (orange banner plus a terminal message), then continues.
- `utils/otp.py` — `manual` no longer calls `input()` when there is no terminal (pytest / MCP); it raises a clear error.
- `.env` — `OTP_STRATEGY=manual`.
- `tests/test_login.py` — `test_deny_location_blocks_signin` has no early `return`, so its steps are reported correctly.
- `README.md`, `reporting/README.md`, `conftest.py`, `examples/test_reporting_demo.py` — docs for the single page and manual OTP.

**Status / open items**
- Demo suite checked: one page (0.27 MB, 4 screenshots embedded), QA wording for assertion, timeout, blocked and skipped results, no page errors.
- Full-suite run not done yet: `test_beneficiary`, `test_user_management` and others create data in shared UAT and need approval.

---

## 2026-10-19 16:45 IST — Fix deny-location login test

**Why:** Without location the app disables the Sign in button. The test clicked that disabled button and timed out after 30s.

**Changed**
- `tests/test_login.py` — `test_deny_location_blocks_signin` passes when Sign in is disabled. It clicks and checks that the dashboard is not reached only if the button is enabled.

**Status / open items**
- Headed run of `tests/test_login.py`: 18 passed, 2 failed, 3 skipped. Now passing: deny location. Still failing: valid admin login, because `MAIL_APP_PASSWORD` is not set.

---

## 2026-10-19 16:34 IST — Execution HTML report after every run

**Why:** Each module run needs a detailed, shareable report: the 25 fields per test case, a dashboard, charts, a failure summary, retry analysis, trends, screenshots, video and trace on failure, API, console and network logs, and PDF/HTML/CSV/JSON export.

**Added**
- `reporting/` — pytest plugin (`plugin.py`), per-test recorder plus the `report` fixture (`recorder.py`), Playwright capture for console, page errors, network failures, XHR, screenshots, tracing and video (`browser.py`), API logging with redaction (`api_log.py`), metadata inference and failure classification (`metadata.py`), outputs, history, `latest/` and retention (`writers.py`), and the report UI (`templates/report.html|css|js`, SVG charts with no CDN, so it works offline and in CI).
- Output per run: `reports/runs/<YYYYMMDD-HHMMSS>_<scope>/{html,json,csv,logs,screenshots,videos,traces}`, plus `reports/latest/`, `reports/latest-report.html`, `reports/index.html` and `reports/history/history.json`.
- `reporting/README.md` — what the report contains, the folder layout, an integration guide, `REPORT_*` settings and CI examples.
- `examples/test_reporting_demo.py` — demo against a local app (never touches UAT). It covers pass, fail, blocked, skip, flaky with retry, parametrised tests, API, console and network capture.
- New markers: `meta(...)`, `validation`, `integration` (registered by the plugin).

**Changed**
- `conftest.py` — loads the plugin (`pytest_plugins`) and merges video recording into every browser context.
- `api/api_client.py` — a `requests` response hook logs every API call into the running test's report.
- `.gitignore` — ignores `reports/runs/`, `reports/latest/` and `reports/history/`.
- `README.md` — points to the report.

**Status / open items**
- Checked with the demo, in-process and with `-n 2` plus `--reruns 1`. Results were correct, with screenshots, video and trace per failed attempt, flaky detection, redacted password and token, and steps that mark the failing line. The page was also checked in light and dark mode, with the modal, and at phone width.
- Not yet run against the UAT suite. Existing tests work without edits (ID, module, feature, type and preconditions are inferred). Add `report.step()` / `@pytest.mark.meta` where richer detail is wanted.
- Video and trace default to `retain-on-failure`. Set `REPORT_VIDEO=off` / `REPORT_TRACE=off` for faster local runs.

---

## 2026-10-19 16:05 IST — Gmail OTP login + one-time forgot-password flow

**Why:** Log in with the real OTP from the Gmail inbox (always the latest "Your SprintEXcrow sign-in code" mail). Run forgot password once, save the new password, and on later runs just log in and continue to the next modules.

**Added**
- `utils/mailbox.py` — reads the Gmail inbox over IMAP. Picks the newest matching mail received after the Sign-in / reset click and pulls out the 6-digit code or the reset link.
- `utils/credential_store.py` — saves the password set by forgot password to `.auth/credentials.json` (git-ignored), with a `reset_done` flag.
- `tests/test_00_forgot_password.py` — forgot password → mailed code/link → new password → sign in. Runs first; skips once the reset is done (`FORCE_PASSWORD_RESET=1` to run it again).
- `.env` — local credentials and `OTP_STRATEGY=imap` (git-ignored).
- `CHANGED.md` — this file.

**Changed**
- `pages/login_page.py` — OTP boxes now match the live UI (`aria-label` "Digit 1"–"Digit 6"); login records the click time so only a newer code is used; waits to leave `/login` after verify; new `reset_password_via_mail()`.
- `utils/otp.py` — new `imap` strategy (alias `gmail`); `get_otp()` takes `since` and `subject`.
- `config/settings.py` — `admin_password` is now a property that prefers the saved password over `ADMIN_PASSWORD`; new mailbox settings (`MAIL_IMAP_HOST`, `MAIL_USER`, `MAIL_APP_PASSWORD`, `OTP_MAIL_SUBJECT`, `RESET_MAIL_SUBJECT`, `OTP_MAIL_TIMEOUT_S`, `CREDENTIALS_STORE`, `RESET_NEW_PASSWORD`).
- `mcp_server/server.py` — `ui_login` passes the Sign-in click time to `get_otp()`.
- `.env.example` — documents the new keys.

**Status / open items**
- Live UI checked: `Patna@12` is accepted and the 6-box OTP screen appears.
- Gmail IMAP rejects the normal account password. `MAIL_APP_PASSWORD` needs a Google App Password before the OTP and reset flows can run end to end.
- The forgot-password page says it sends a reset *link*; the code handles a link or an OTP. Confirm the real reset mail subject and set `RESET_MAIL_SUBJECT` if needed.
