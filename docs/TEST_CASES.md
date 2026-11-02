# SprintEXcrow — Test case catalogue

Generated from the test code by `python tools/test_catalogue.py`. 198 test cases, 415 executions (variants included).

The **ID** is what the execution report and every failure message show (`[AUTH-API-005] …`). *Variants* are the data sets one case runs with.

## Authentication & Session — UI (sign-in, location, OTP, session, forgot password)

`tests/test_login.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| AUTH-UI-001 | Sign-in page shows heading, Email, Password, Forgot password? and Sign in. | Smoke, UI/UX, Functional | — |
| AUTH-UI-002 | submitting the form never puts the email/password in the URL. | Security, UI/UX, Functional | — |
| AUTH-UI-010 | Email and Password are mandatory; nothing is sent while one is empty. | Negative, UI/UX, Functional | both_empty, password_empty, email_empty, email_spaces |
| AUTH-UI-011 | malformed emails show the format message and are not sent. | Boundary, Negative, UI/UX, Functional | abc, abc@, abc@x, a b@x.com, @x.com, abc@@x.com |
| AUTH-UI-020 | a wrong password shows 'Invalid email or password.' and does not sign in. (The only wrong-password attempt on the real account per run.) | Negative, UI/UX, Functional | — |
| AUTH-UI-021 | an unknown email gets the SAME message as a wrong password (no 'user not found', so accounts cannot be discovered). | Security, UI/UX, Functional | — |
| AUTH-UI-022 | SQL in email/password never signs in and never shows a database error. | Security, UI/UX, Functional | ' OR '1'='1, admin'--, " OR ""=", ') OR ('1'='1, 1 OR 1=1 |
| AUTH-UI-023 | script payloads in the sign-in fields never execute. | Security, UI/UX, Functional | <script>alert(1)</script>, "><img src=x onerror=alert(1)>, <svg/onload=alert(1)> |
| AUTH-UI-030 | with location blocked, a clear notice shows and Sign in stays disabled. | UI/UX, Functional | — |
| AUTH-UI-031 | with location allowed, no notice is shown and Sign in is enabled. | UI/UX, Functional | — |
| AUTH-UI-040 | correct credentials open 'Enter the code' with a masked email and 6 boxes. | UI/UX, Functional | — |
| AUTH-UI-041 | 'Verify and sign in' stays disabled for 0-5 digits and enables at 6. | Boundary, UI/UX, Functional | — |
| AUTH-UI-042 | letters and symbols typed into the OTP boxes are ignored. | Negative, UI/UX, Functional | — |
| AUTH-UI-043 | pasting a 6-digit code fills all six boxes. | UI/UX, Functional | — |
| AUTH-UI-044 | a wrong code shows an error, clears the boxes and does not sign in. | Negative, UI/UX, Functional | — |
| AUTH-UI-045 | 'Send a new code' starts disabled with a seconds countdown. | UI/UX, Functional | — |
| AUTH-UI-046 | 'Use a different account' goes back to the sign-in form. | UI/UX, Functional | — |
| AUTH-UI-047 | refreshing on the OTP step returns to the sign-in form (no half session). | UI/UX, Functional | — |
| AUTH-UI-048 | after the password step, opening /dashboard directly still needs sign-in. | Security, UI/UX, Functional | — |
| AUTH-UI-050 | email + password + OTP signs in to the dashboard; the session is kept in this tab only (sessionStorage) and expires in about 30 minutes. | Smoke, UI/UX, Functional | — |
| AUTH-UI-051 | opening /beneficiaries signed-out goes to /login?next=… and, after sign-in, back to /beneficiaries. | UI/UX, Functional | — |
| AUTH-UI-052 | a `next` pointing to another site is ignored after sign-in (no open redirect). | Security, UI/UX, Functional | protocol_relative, absolute_url, backslash |
| AUTH-UI-060 | every console page sends a signed-out visitor to /login?next=… | Security, UI/UX, Functional | /dashboard, /beneficiaries, /transfers, /audit-trail, /users, /change-password |
| AUTH-UI-061 | the sign-in lives in the tab: a new tab with only the saved cookies and local storage (no tab session) is not signed in. | Security, UI/UX, Functional | — |
| AUTH-UI-062 | a forged token planted in sessionStorage does not open the console. | Security, UI/UX, Functional | garbage_token, unsigned_token, empty_token |
| AUTH-UI-063 | the access token is only in this tab's sessionStorage — not in cookies (no CSRF surface) or localStorage (survives browser close). | Security, UI/UX, Functional | — |
| AUTH-UI-064 | any session-like cookie is HttpOnly, Secure and SameSite. | Security, UI/UX, Functional | — |
| AUTH-UI-070 | 'Forgot password?' opens the reset page with Email, Send reset link and Back to sign in. | UI/UX, Functional | — |
| AUTH-UI-071 | the reset form checks the email before sending. | Negative, UI/UX, Functional | empty, no_at, no_domain |
| AUTH-UI-072 | an unknown email gets the same 'If an account exists for …' answer (no account discovery). Sends no mail. | Security, UI/UX, Functional | — |

## Authentication & Session — UI (change password, sign out)

`tests/test_change_password_signout.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| SES-001 | Change password shows Current / New / Confirm fields, the rule and both buttons. | UI/UX, Functional | — |
| SES-002 | submitting the empty form shows a message under each field and sends nothing. | Negative, UI/UX, Functional | — |
| SES-003 | a new password breaking the rule is refused with the matching message. | Boundary, Negative, UI/UX, Functional | 7_chars, 13_chars, no_lowercase, no_uppercase, no_digit, no_symbol |
| SES-004 | 8 and 12 characters pass the client rule (the request is faked, nothing changes). | Boundary, UI/UX, Functional | 8_chars, 12_chars |
| SES-005 | New and Confirm must match. | Negative, UI/UX, Functional | — |
| SES-006 | the new password cannot equal the current one. | Negative, UI/UX, Functional | — |
| SES-007 | a wrong current password (valid new one) is refused by the server and the user stays signed in. | Negative, UI/UX, Functional | — |
| SES-008 | 'Back to the console' leaves the form without changing anything. | UI/UX, Functional | — |
| SES-010 | Sign out returns to /login, clears the tab session and the old token is refused by the API (revoked on the server, not just forgotten by the browser). | Security, Smoke, UI/UX, Functional | — |
| SES-011 | after sign out, the browser Back button does not show console data. | Security, UI/UX, Functional | — |
| SES-012 | after sign out, typing a console URL leads to sign-in. | Security, UI/UX, Functional | — |

## Authentication & Session — UI (password reset by mail)

`tests/test_00_forgot_password.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| AUTH-UI-080 | reset the password via the mailed code, then sign in with it. | Functional | — |

## Authentication & Session — API

`tests/test_auth_api.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| AUTH-API-030 | /auth/me with a valid token returns the signed-in user, no secrets. | API, Functional | — |
| AUTH-API-033 | the real token with one signature character changed is refused. | Security, API, Functional | — |
| AUTH-API-034 | an unsigned (alg=none) copy of the real token is refused. | Security, API, Functional | — |
| AUTH-API-035 | changing the token's claims (e.g. a later expiry) invalidates it. | Security, API, Functional | — |
| AUTH-API-036 | the token is signed (not alg=none), expires within an hour and carries no password / OTP. | Security, API, Functional | — |
| AUTH-API-037 | after POST /auth/logout the same token is refused everywhere. Uses its own sign-in so the shared session is not touched. | Security, API, Functional | — |
| AUTH-API-040 | change-password with {} names every missing field (nothing changes). | API, Negative, Functional | — |
| AUTH-API-041 | a weak new password is refused by the server and nothing changes. The server checks the current password first ('Your current password is incorrect.'), so with a wrong current password the rule itself cannot be reached safely — sending the real current password would CHANGE it if the rule were missing. | API, Negative, Functional | 3_chars, no_upper_digit_symbol, no_lowercase, 13_chars |
| AUTH-API-042 | newPassword and confirmPassword must match on the server too. | API, Negative, Functional | — |
| AUTH-API-043 | a wrong current password is refused and the token stays valid. | API, Negative, Functional | — |
| AUTH-API-001 | {} is refused with VALIDATION_ERROR naming email and password. | API, Negative, Functional | — |
| AUTH-API-002 | a login without email or password is refused naming that field. | API, Negative, Functional | email, password |
| AUTH-API-003 | a malformed email is refused with 'Enter a valid email address'. | API, Negative, Functional | abc, abc@, a b@x.com, @x.com |
| AUTH-API-004 | sign-in without clientGeo is refused (location is mandatory). | API, Negative, Functional | — |
| AUTH-API-005 | an unknown email gets 401 'Invalid email or password.' | API, Negative, Functional | — |
| AUTH-API-006 | a wrong password for a REAL account answers exactly like an unknown email (status, code, message), so accounts cannot be discovered. One attempt per run. | Security, API, Functional | — |
| AUTH-API-007 | a broken JSON body is 400 MALFORMED_REQUEST, not 500. | API, Negative, Functional | — |
| AUTH-API-008 | impossible location values are refused cleanly (4xx, never 2xx/5xx). | API, Negative, Functional | latitude_999, text, nulls |
| AUTH-API-009 | SQL in email/password never signs in, never errors (403 from the firewall is fine). | Security, API, Functional | ' OR '1'='1, admin'--, " OR ""=", ') OR ('1'='1, 1 OR 1=1 |
| AUTH-API-010 | a 10 000-character email/password is refused cleanly (4xx). | API, Negative, Functional | email, password |
| AUTH-API-011 | a form-encoded body is refused cleanly (4xx), not 500. | API, Negative, Functional | — |
| AUTH-API-012 | only POST is accepted on /auth/login (other verbs are refused: the API answers 401 because its auth filter runs before method routing). | API, Negative, Functional | GET, PUT, DELETE |
| AUTH-API-013 | the right password alone gives NO token: it returns otpRequired, a challenge reference and a masked destination. (Sends one OTP mail.) | API, Functional | — |
| AUTH-API-020 | verify-otp without fields names challengeReference and code. | API, Negative, Functional | — |
| AUTH-API-021 | a code for an unknown/expired challenge says to sign in again. | API, Negative, Functional | — |
| AUTH-API-022 | a code that is not 6 digits is refused (4xx), never 2xx/5xx. | API, Negative, Functional | 5, 7, letters, space, empty |
| AUTH-API-023 | resending for an unknown challenge says to sign in again. | API, Negative, Functional | — |
| AUTH-API-024 | repeated wrong codes on one challenge are stopped (OTP_RESTART_REQUIRED or 429) within 6 tries. RUN_LOCKOUT_TESTS=1 only. | Security, API, Functional | — |
| AUTH-API-031 | session endpoints refuse an anonymous call with 401 UNAUTHORIZED. | Security, API, Functional | auth_me, logout, change_password, navigation, beneficiaries |
| AUTH-API-032 | garbage, empty or wrong-scheme Authorization headers get 401. | Security, API, Functional | garbage, empty, basic, wrong_scheme |
| AUTH-API-050 | an unknown email gets 200 and the generic 'If an account exists…' message. | Security, API, Functional | — |
| AUTH-API-051 | the real account gets the identical answer (no account discovery). Sends one reset mail to the admin (the password is not changed). | Security, API, Functional | — |
| AUTH-API-052 | forgot-password checks the email format. | API, Negative, Functional | empty, no_at, no_domain |
| AUTH-API-053 | a made-up reset token is reported as not usable (valid=false). | Security, API, Functional | word, zeros, sql |
| AUTH-API-054 | a password reset with a made-up token never succeeds. | Security, API, Functional | — |
| AUTH-API-055 | auth responses carry HSTS, nosniff, frame protection and no-store. | Security, API, Functional | — |
| AUTH-API-056 | the login API does not allow a foreign site to call it from a browser. | Security, API, Functional | — |
| AUTH-API-057 | every auth error carries a request id support can trace. | Security, API, Functional | — |
| AUTH-API-060 | repeated failed logins (unknown email) are throttled with 429 within 25 tries. RUN_LOCKOUT_TESTS=1 only (it can throttle this machine). | Security, API, Functional | — |
| AUTH-API-061 | repeated reset requests are throttled (429) within 15 tries. RUN_LOCKOUT_TESTS=1 only. | Security, API, Functional | — |

## Add Beneficiary / Beneficiary List — UI

`tests/test_beneficiary.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| BEN-UI-001 | heading, subtitle, search, Reset Filters, Add Beneficiary, all eight columns, and the 'Showing N' count all render. | Smoke, UI/UX, Functional | — |
| BEN-UI-002 | the Beneficiary List menu entry routes to /beneficiaries. | UI/UX, Functional | — |
| BEN-UI-003 | the Account column shows the last four digits only. | Security, UI/UX, Functional | — |
| BEN-UI-004 | Registration shows one of the documented labels for every row. | UI/UX, Functional | — |
| BEN-UI-005 | searching a code lists that beneficiary. | UI/UX, Functional | — |
| BEN-UI-006 | searching part of a name lists matching beneficiaries only. | UI/UX, Functional | — |
| BEN-UI-007 | a search with no match shows the empty state; Reset Filters brings the list back. | Negative, UI/UX, Functional | — |
| BEN-UI-008 | SQL / script payloads in search neither error nor execute. | Security, UI/UX, Functional | ' OR '1'='1, admin'--, " OR ""=", ') OR ('1'='1, 1 OR 1=1, <script>alert(1)</script>, "><img src=x onerror=alert(1)>, <svg/onload=alert(1)> |
| BEN-UI-009 | clicking a code opens the details with Payee and With-the-bank sections. | UI/UX, Functional | — |
| BEN-UI-010 | the details panel shows the account masked (last 4). | Security, UI/UX, Functional | — |
| BEN-UI-011 | Block/Unblock is offered only when Status is ACTIVE or BLOCKED. | UI/UX, Functional | — |
| BEN-UI-012 | cancelling the 'Block this beneficiary?' confirmation changes nothing. | Negative, UI/UX, Functional | — |
| BEN-UI-013 | Block (with confirmation) then Unblock; status returns to ACTIVE. Touches shared data briefly; always restores the original state. | UI/UX, Functional | — |
| BEN-UI-014 | Check status on a bank-confirmed (ACTIVE) payee asks the bank and updates 'Last checked'. | UI/UX, Functional | — |
| BEN-UI-016 | when the bank cannot answer (status check fails), the user sees a clear message instead of nothing. The bank error is simulated. | Negative, UI/UX, Functional | — |
| BEN-UI-015 | the details panel closes with the X button and with Escape. | UI/UX, Functional | close_button, escape |
| BEN-UI-020 | the form shows all seven fields, Cancel and Register with bank. | Smoke, UI/UX, Functional | — |
| BEN-UI-021 | only Mobile number is marked (optional); Email says Required. | UI/UX, Functional | — |
| BEN-UI-022 | the code is issued by the system, matches the code format and cannot be edited. | UI/UX, Functional | — |
| BEN-UI-023 | every form opening is issued a different code (no reuse). | UI/UX, Functional | — |
| BEN-UI-024 | a freshly issued code is not an existing beneficiary's code. | Negative, UI/UX, Functional | — |
| BEN-UI-025 | Cancel / X / Escape close the form without sending anything. | Negative, UI/UX, Functional | cancel, close_button, escape |
| BEN-UI-030 | submitting the empty form is refused with the first rule's message. | Negative, UI/UX, Functional | — |
| BEN-UI-031 | leaving one mandatory field empty (all others valid) blocks registration. | Negative, UI/UX, Functional | name, account_number, confirm_account_number, ifsc, email |
| BEN-UI-032 | spaces alone do not satisfy a mandatory field. | Negative, UI/UX, Functional | name-     , email-   , ifsc-    |
| BEN-UI-033 | all mandatory fields filled, Mobile blank: the form submits without beneMobileNo. | UI/UX, Functional | — |
| BEN-UI-034 | the submitted payload carries every field exactly as entered. | UI/UX, Functional | — |
| BEN-UI-035 | an optional mobile, once entered, must be exactly 10 digits. | Negative, UI/UX, Functional | 98765, 987654321, 98765432101, abcdefghij, +919876543210 |
| BEN-UI-036 | malformed email addresses are refused. | Negative, UI/UX, Functional | abc, abc@, abc@x, a b@x.com, @x.com, abc@@x.com |
| BEN-UI-040 | 9 and 18 digits (the limits) are accepted. | Boundary, UI/UX, Functional | 9, 18 |
| BEN-UI-041 | fewer than 9 / more than 18 digits, or no digits, are refused. | Boundary, Negative, UI/UX, Functional | 8_digits, 19_digits, 1_digit, letters_only |
| BEN-UI-042 | an account number with letters or symbols must be refused, not silently cleaned (cleaning hides a typo in the payee's account). | Negative, UI/UX, Functional | letters_inside, symbol, dashes |
| BEN-UI-043 | any difference between Account and Confirm account is refused. | Negative, UI/UX, Functional | last_digit, first_digit, one_digit_short, one_digit_extra, swapped |
| BEN-UI-044 | identical Account and Confirm account pass. | UI/UX, Functional | — |
| BEN-UI-045 | Confirm account number rejects paste (must be retyped). | Security, UI/UX, Functional | — |
| BEN-UI-046 | both account inputs have autocomplete=off and a numeric keypad. | Security, UI/UX, Functional | — |
| BEN-UI-050 | IFSC must be 4 letters + '0' + 6 letters/digits (11 characters). | Boundary, Negative, UI/UX, Functional | HDFC000123, HDFC00012345, HDFCX001234, HDFC1001234, HDF0001234, 1234567890A, HDFC0-01234, HDFC 001234 |
| BEN-UI-051 | a lower-case IFSC is shown and sent in upper case. | UI/UX, Functional | — |
| BEN-UI-060 | a fully valid beneficiary is registered, listed, masked and searchable. Creates one 'QA Auto' beneficiary on UAT (sent to the bank). | UI/UX, Functional | — |
| BEN-UI-061 | registering with a code that already exists is refused, and the form issues a fresh code. The request's code is swapped for an existing one. | Negative, UI/UX, Functional | — |
| BEN-UI-070 | script payloads typed into the name never execute in the form. | Security, UI/UX, Functional | <script>alert(1)</script>, "><img src=x onerror=alert(1)>, <svg/onload=alert(1)> |
| BEN-UI-071 | the typed account number is not kept in local/session storage. | Security, UI/UX, Functional | — |

## Beneficiary — API

`tests/test_beneficiary_api.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| API-BEN-001 | the list returns the envelope and paging fields. | API, Smoke, Functional | — |
| API-BEN-002 | each item carries the fields the screen needs. | API, Functional | — |
| API-BEN-003 | detail by reference returns the same beneficiary with bank fields. | API, Functional | — |
| API-BEN-004 | search by code returns that beneficiary. | API, Functional | — |
| API-BEN-005 | issued codes match the code format and are never repeated. | API, Functional | — |
| API-BEN-006 | a newly issued code does not belong to an existing beneficiary. | API, Negative, Functional | — |
| API-BEN-007 | an unknown reference is 404 NOT_FOUND. | API, Negative, Functional | — |
| API-BEN-008 | malformed references are refused cleanly (4xx, never 5xx). | API, Negative, Functional | abc, ..%2F..%2Fetc%2Fpasswd, ' OR 1=1--, 111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111, %00 |
| API-BEN-009 | Check status / Block on an unknown reference is 404. | API, Negative, Functional | enquiry, toggle-status |
| API-BEN-010 | {} is refused with VALIDATION_ERROR naming all five mandatory fields — and not the optional mobile. | API, Negative, Functional | — |
| API-BEN-011 | a valid body without one mandatory field is refused. | API, Negative, Functional | beneAccNum, beneCode, beneEmailAddr1, beneIfscCode, beneName |
| API-BEN-012 | empty, spaces-only or null in a mandatory field is refused. | API, Negative, Functional | empty-beneAccNum, empty-beneCode, empty-beneEmailAddr1, empty-beneIfscCode, empty-beneName, spaces-beneAccNum, spaces-beneCode, spaces-beneEmailAddr1, spaces-beneIfscCode, spaces-beneName, null-beneAccNum, null-beneCode, null-beneEmailAddr1, null-beneIfscCode, null-beneName |
| API-BEN-013 | the server enforces each field rule itself (not only the UI). | API, Boundary, Negative, Functional | 8_digits, 19_digits, letters, dashes, space, negative, ifsc_10, ifsc_12, ifsc_5th_not_0, ifsc_digits_first, ifsc_symbol, email_no_at, email_no_domain_dot, email_space, email_double_at, mobile_5, mobile_11, mobile_letters, mobile_country_code, name_300_chars, code_spaces, code_51_chars, code_symbols |
| API-BEN-014 | wrong JSON types are refused cleanly (4xx), not 5xx. (A JSON number for account/mobile is coerced to text by the server — accepted by design.) | API, Negative, Functional | name_array, email_object, acc_boolean, ifsc_array |
| API-BEN-015 | a malformed JSON body is 400, not 500. | API, Negative, Functional | — |
| API-BEN-020 | Creates. A body with only the mandatory fields (no mobile) is registered; the account is masked in the reply and the detail. Re-sending the SAME body is an idempotent retry (same beneficiary back, nothing new); the same code for a DIFFERENT payee is refused as a duplicate. | API, Functional | — |
| API-BEN-021 | an existing beneficiary's code cannot be registered again. | API, Negative, Functional | — |
| API-BEN-022 | a case or whitespace variant of an existing code must not create a second payee that looks the same (refused as duplicate or as invalid). | API, Negative, Functional | lower_case, leading_trailing_spaces |
| API-BEN-023 | Creates. Registering the same account + IFSC under a second code should be refused or flagged (the same payee twice). | API, Negative, Functional | — |
| API-BEN-032 | the real token with its signature changed is rejected. | Security, API, Functional | — |
| API-BEN-033 | an alg=none token with the real claims is rejected. | Security, API, Functional | — |
| API-BEN-034 | no full account number anywhere in the list response. | Security, API, Functional | — |
| API-BEN-035 | the detail response masks the account too. | Security, API, Functional | — |
| API-BEN-036 | no password / OTP / secret / token keys in list or detail. | Security, API, Functional | — |
| API-BEN-037 | SQL in the search parameter neither errors nor widens the result. | Security, API, Functional | ' OR '1'='1, admin'--, " OR ""=", ') OR ('1'='1, 1 OR 1=1 |
| API-BEN-038 | a name with markup or SQL is refused (bank names are plain text). Creates a beneficiary only if the server wrongly accepts it. | Security, API, Functional | script_tag, sql_in_name |
| API-BEN-039 | Creates. Status / registration / reference fields in the body are ignored: a new payee is never ACTIVE or SUCCESS before the bank confirms. | Security, API, Functional | — |
| API-BEN-040 | beneficiaries cannot be deleted / overwritten via other verbs. | Security, API, Functional | DELETE-/{ref}, PUT-/{ref}, PUT-, DELETE-, TRACE- |
| API-BEN-041 | security headers present and the response is not cached. | Security, API, Functional | — |
| API-BEN-046 | each security header is set once (proxy + app both setting it gives 'DENY, DENY', which some clients treat as invalid and ignore). | Security, API, Functional | — |
| API-BEN-042 | a foreign Origin is not echoed back as allowed. | Security, API, Functional | — |
| API-BEN-043 | a huge page size is capped or refused (no bulk dump in one call). | Security, API, Functional | 1000, 100000 |
| API-BEN-044 | invalid paging values are handled (4xx or clamped), never 5xx. | API, Negative, Functional | page_-1, size_0, size_-5, page_text |
| API-BEN-045 | issuing 20 codes quickly does not error (and may be rate-limited). | Security, API, Functional | — |
| API-BEN-030 | every beneficiary endpoint refuses an anonymous call with 401. | Security, API, Functional | list, detail, create, issue_code, enquiry, toggle_status |
| API-BEN-031 | tampered, empty or wrong-scheme credentials are 401. | Security, API, Functional | tampered, empty_bearer, basic, null |

## API security — cross-module

`tests/test_api_security.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| API-001 | protected endpoints reject unauthenticated requests (401/403). | Security, API | /api/v1/dashboard/summary, /api/v1/beneficiaries, /api/v1/transfers, /api/v1/users, /api/v1/roles, /api/v1/audit-trail |
| API-003 | a tampered/garbage bearer token is rejected. | Security, API | — |
| API-002 | a valid admin token is accepted on a protected endpoint. | Security, API | — |
| WSEC-002 | endpoints behind non-live modules must be locked (403/404). | Security, API | /api/v1/transfers/create, /api/v1/approvals, /api/v1/virtual-ids, /api/v1/master-escrow, /api/v1/deposits, /api/v1/qr-settlements |
| API-005 | requesting an object by an id outside the caller's scope is denied (no IDOR). Uses a clearly foreign id. | Security, API | — |
| API-006 | extra privileged fields on create-user are ignored. | Security, API | — |
| API-007 | SQLi in a query parameter does not error or dump data. | Security, API | ' OR '1'='1, admin'--, " OR ""=", ') OR ('1'='1, 1 OR 1=1 |
| API-018 | responses never contain password/OTP/secret fields. | Security, API | — |
| API-017 | account numbers in responses are masked (last 4 only). | Security, API | — |
| API-026 | recommended security headers are present on API responses. | Security, API | — |
| API-013 | unexpected HTTP verbs are rejected (405). | Security, API | — |
| API-014 | no 'Access-Control-Allow-Origin: *' together with credentials. | Security, API | — |

## UI security — cross-module

`tests/test_security.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| WSEC-001 | direct navigation to a non-live module must not render it. | Security | Create Transfer, Approvals, Master Escrow, Virtual ID, Deposits, QR Settlements |
| WSEC-006 | no passwords/OTPs/full account numbers in web storage. | Security | — |
| WSEC-006 | the console must not print passwords/OTPs/account numbers. | Security | — |
| WSEC-009 | the application is served over HTTPS. | Security | — |

## Dashboard (pending development)

`tests/test_dashboard.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| WDSH-001 | Dashboard loads and the MERCHANT_OWNER role is shown. | Smoke, UI/UX, Functional | — |
| WDSH-002 | every live module is enabled/clickable in the sidebar. | UI/UX, Functional | Dashboard, Beneficiary List, Transfers, Audit Trail, User Management, Change password, Sign out |
| WDSH-003 | dimmed modules are not clickable and reveal no screen. | Security, UI/UX | Create Transfer, Approvals, Master Escrow, Escrow Transfer, Escrow Deposit, Virtual ID, Deposits, QR Settlements |
| WDSH-004 | direct URL to a non-live module must not render it. | Security, UI/UX | Create Transfer, Approvals, Master Escrow, Virtual ID, Deposits, QR Settlements |
| WDSH-005 | monetary amounts render with the ₹ symbol. | UI/UX | — |

## User Management (pending development)

`tests/test_user_management.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| WUM-001 | base roles (Business/Operations/Admin/Customer) are listed. | Functional | — |
| WUM-002 | create a role and set module access via the matrix. | Functional | — |
| WUM-004 | Admin and Customer roles cannot be renamed/deleted. | Security, Functional | Admin, Customer |
| WUM-006 | the Invite New User form exposes identity + role + hierarchy. | Functional | — |
| WUM-007 | invite a user with role + hierarchy and Send Invitation. | Functional | — |
| WUM-008 | Contact Number must be exactly 10 digits. | Negative, Functional | 98765, abcdwinvalid, 98765432101 |
| WUM-009 | choosing Customer reveals a required Assigned Virtual ID field. | Functional | — |
| WUM-014 | a script payload in Full Name is not executed. | Security, Functional | <script>alert(1)</script>, "><img src=x onerror=alert(1)> |

## Transfers

`tests/test_transfers.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| WTRN-002 | the Transfers list renders (status badges visible). | Smoke, Functional | — |
| WTRN-004/005 | selecting a pending badge opens the Transfer Journey with the Transfer ID / amount / Maker → Approver 1 → Approver 2 progression. | Functional | — |
| WTRN-011 | a user without approval rights sees no Approve control. | Security, Functional | — |
| WTRN-014 | amounts use ₹ and any account info is masked in the drawer. | UI/UX, Functional | — |
| WTRN-009 | the maker who created a transfer must not approve it. Requires a transfer created by MAKER_* and that same user attempting to approve. Implement against a seeded fixture in the target environment. | Security, Functional | — |

## Audit Trail

`tests/test_audit_trail.py`

| ID | Test case | Type | Variants |
|---|---|---|---|
| WAUD-001 | the Audit Trail renders entries. | Smoke, Functional | — |
| WAUD-002 | entries carry user / time / IP (and location). | Functional | — |
| WAUD-004 | no passwords, OTPs or full account numbers in descriptions. | Security, Functional | — |
| WAUD-005 | a limited role cannot open the Audit Trail directly. | Security, Functional | — |
