# PART 27 - fresh-install fixes, one-step setup, the 39 test-report issues (2026-11-19)

Branch `KG-Development`. Inputs: `docs/ui/Hr_Inteligence_Portal_Issues_By_Pages.pdf` (E2E report, 5 Nov) and the
colleague's configuration notes. All mail went to Mailpit (`DEV_MAIL_CAPTURE=127.0.0.1:1025`).

## 27.0 One-step install + fresh-install fixes (code came in with `ed3efbf`)

| Check | Result |
|---|---|
| a. `pytest tests/test_install.py` | 20 passed |
| b. Throwaway install on this PC (`--answers %TEMP%\a.json --env %TEMP%\fi.env --delete-answers`, databases `t27_main` / `t27_cp`, login `t27_app`, app password with `@ #` and spaces) | all 9 steps "done" (PostgreSQL, login + databases, .env, tables, grants, company, base data, admin created, 11 modules on); answers file deleted. Run again: all 9 done, admin `created: false`, modules `switched_on: []` (re-run safe). `hr_automation` not touched. Then dropped `t27_main`, `t27_cp`, role `t27_app`. |
| c. `--check` with a line break in the admin password | "Please fix: - Admin password must not contain line breaks, tabs or other invisible characters." exit 2 |
| d. `backend/.env.example` | already `postgresql+psycopg2://`, `hr_app` login, "run `python -m app.platform.install` instead of editing this by hand" |
| e. `grant_app.py`, `dev_make_admin.py` | not in the repo or anywhere under it - nothing to delete |

## 27.1 High (cause quoted first; each has a test that fails on the old code)

| # | Cause | Fix | Test |
|---|---|---|---|
| H1 | `HomePage.tsx:102` built `modules` as a new array every render -> `load` (`useCallback([modules])`) changed -> the effect re-ran -> `setHome` re-rendered: GET /me/home in a loop | `modules` memoised on its joined value | `HomePage.test.tsx`: 1 call per mount (old code: 56 calls in 0.3 s) |
| S1 | `salary_auto.check()` adds reason `no_current` -> state `needs_approval` -> `apply_stage()` moves to `salary_above_band`; every label said "above (salary) band"; the approver message / history note said "N% above the band" (0%) | safety kept (a person approves); status label "Needs salary approval" (EN/HI/TA, StatusChip, stage chips); history note + approver message list the real reasons (`salary_auto.reasons_text`); the approval box names the reasons when none is "above band"; salary stage shows "Above range · n" counting only `reasons` with `above_band` | `test_salary_reasons.py` (3) |
| P1 | `pipeline_actions.compute_next_actions` had no branch for `salary_approved` -> `[]` -> `CandidateDetailPage.tsx:473` showed "reached its last step" | next step "Joining documents" (-> BGV -> joining date -> offer -> joined) | `test_applications.py::..._after_salary_approval_still_has_a_next_step` |
| I1 | `scheduling/router.py schedule_interview` accepted any `scheduled_at` (the only booking path that takes a time; proposed slots come from calendars, "propose a time" is free text) | 400 "That time is in the past..." (5 min grace); picker `min` = now (IST) + the same check before sending | `test_scheduling.py::test_interview_cannot_be_booked_in_the_past` |
| B1 | `DocumentsReviewDrawer` showed `docrev.done_send` "The upload link was sent." on any HTTP 200; `joining_docs.send_form` returned `sent: false` but the drawer ignored it; counter-offer said "emailed" regardless | drawer follows `sent` ("Email not sent - no mailbox is connected..."), [Copy link] always (new `GET /ui/documents/{id}/link`), "Upload for the candidate" per document (`POST /ui/documents/{id}/files/{code}`, same `save_upload` checks, HR's name in the history); salary form + joining dates always return the link -> shared `CopyLinkButton`; counter-offer returns `email_sent`; "Counter-offer ... sent" status line no longer claims the email went | `test_sent_messages.py` (4) |

Also done here because they sit on the same code: **P2** (salary action is a real button opening that candidate's
drawer: `/salary?application=<id>`, stage table filter `application_id`; label sentence case), **I2** (meeting link
must be http(s): 400 + field error), **S3** (approve says "No department budget is set - nothing was reserved" when
the department has no budget: `decide()` returns `budget_reserved`), **B3** ("Ask again for 0 documents" hidden
until one is ticked, with a hint). Tests: `test_scheduling.py::test_meeting_link_must_be_a_web_address`,
`test_applications.py::..._opens_the_candidates_salary_drawer`, `test_sent_messages.py`.
Affected test files: only baseline failures (3 test_intelligence, 1 test_applications, 1 test_scheduling, 2 test_salary).

## 27.2 Medium

| # | Cause | Fix | Test |
|---|---|---|---|
| L1 | no self-service reset; `iam.auth.password_history_count` / `_require_complexity` were never enforced (`password_history` table unused) | `/login` "Forgot password?" -> `/forgot-password`: same answer whether the email exists or not, one-time `set_password` link (action token, **30 min**, single use), rate limit 5 / 15 min per address (20 per IP) -> 429, audit `password_reset_requested` / `user_password_set`; without an active outgoing mailbox the page says "Ask your HR admin" (admins already have Settings > People & access > Reset password with the link to copy). `app/auth/password_policy.py`: length, complexity, history (incl. the current password) for every link-set password | `test_forgot_password.py` (5) |
| L2 | 423 said "Account is temporarily locked. Try again later." | "Too many attempts - try again in N minutes." (minutes from `locked_until`, rounded up; Retry-After) shown as such on /login | `test_forgot_password.py::test_locked_account_says_how_many_minutes` |
| L3 | `/register` + "No account yet? Create one" open to anyone | route -> /login, link replaced by "No account? Your HR team invites you."; `POST /auth/register` 404 unless `PUBLIC_SIGNUP_ENABLED` (off; only the test suite's user helpers turn it on); `RegisterPage.tsx` deleted | `test_public_sign_up_is_closed` (marker `signup_closed`) |
| H3 | `config_health._is_routed("llm.*")` and `system_health._ai` looked only for a routed AI connection; AI runs on the company key or the server's `ANTHROPIC_API_KEY` | one function `platform/ai/status.ai_status()` (ai.enabled + key / connection / Bedrock) used by config health, System health and the AI settings page (`configured`) | `test_ai_status.py` (2) |
| J1 | `CreateJobWizard` creates a draft job on step 1's Next; Cancel never removed it; "Start fresh" only dropped the autosaved form, so the next Next made another job | Cancel deletes the draft it created when nothing beyond the title was typed; "Start fresh" reuses the untouched draft; same title as an existing draft -> "A draft called ... already exists. Open it?" | browser check in 27.4 |
| C1 | `public/router.py` apply always created a new candidate + application (only flagged "possible duplicate" later) | same email (case-insensitive) + same job + application not terminal -> 409 "You have already applied for this job..."; another job is fine; agency/bulk import unchanged | `test_public.py::test_same_email_cannot_apply_twice_to_the_same_job` |
| A1 | `screening/service.py:86` `round(96.5)` = 96 (half-to-even) vs the list's `Math.round` = 97 | `recruitment.scoring.score_round` (half up) at every "Match score N" text (screening remarks, auto-shortlist, Autopilot) | `test_score_round.py` |
| A2 | only the eye icon opened a profile; Actions column off-screen at 1440 px | candidate name is a link to the profile; Actions column sticky on the right; Remarks fixed width with ellipsis + tooltip | browser check in 27.4 |
| P3 | `pipeline_actions` offered one-click "Interview Feedback: Selected / Rejected" from booking on | before the interview time: "Manage interview" only; after: "Record interview result" opens the scorecard (`/interviews?feedback=<id>`, confirm step); backend refuses a result before the interview time and a rejection without overall rating + note (also checked in the form) | `test_scheduling.py` (2 updated / new), `test_applications.py` (2) |
| S2 | the salary drawer kept the row it was opened with | after a decision the page re-reads that row (`?application_id=`); the drawer keeps the message and shows the new status / approved amount / history | browser check in 27.4 |
| R1 | "Report builder" (sub-menu) called `/api/v1/intelligence/*`, owned by the analytics module -> 404 when it is off | the sub-menu entry needs `analytics`; `/reports/builder` and `/analytics` show the "not switched on" card when it is off | X1 |
| ST1 | Settings pages for Performance / Helpdesk ignored the platform module switch | pages carry `registry` modules (performance, helpdesk, assets, separation); hidden when none is enabled - same `bootstrap.modules` as the menu | browser check in 27.4 |
| X1 | `/people /directory /performance(/team) /helpdesk(/queue) /analytics /assets /compensation /succession` loaded without their module and failed | `REGISTRY_MODULE_PAGES` (from `platform/modules.py`) -> the existing "not switched on for your company" card (admins: Settings > Modules); module names EN/HI/TA | browser check in 27.4 |
| X2 | no catch-all route -> blank page | `path="*"` inside the app shell -> "Page not found" with the menu and Go to Home | browser check in 27.4 |

P2 / I2 were done in 27.1. Affected backend test files: only baseline failures. Frontend unit tests: 3 failed / 40 passed - the same 3 fail on the committed code without these changes (UploadCandidateDialog, theme-from-bootstrap x2).

## 27.3 Low (one polish pass)

| # | Fix |
|---|---|
| L2 | done in 27.2 ("Too many attempts - try again in N minutes") |
| H2 | "Finish setting up": human step names (Company details, Companies and locations, Branding, Mailbox, ...), every word on the card through i18n (EN/HI/TA) |
| H4 | room under every page (`main` padding-bottom) so the floating assistant button never covers the last row's actions |
| J2 | one money format `utils/money.ts` (`₹14,00,000`, `8 L`); the wizard's pay line and review use it; the Salary drawer's `money` / `lakh` are the same functions |
| J3 | jobs without a location are listed as "Location not set" (was "Unspecified"); the map's "No open jobs yet" only when there are no open jobs; card title / filter labels translated |
| J4 | a rise from 0 shows "New this month" instead of "▲ 100%" (Jobs stats + StatCard) |
| C2 | "privacy policy" in the consent line links to `/careers/privacy` (the company's published notice for `recruitment.application`; plain words when none is published yet - never an invented notice) |
| C3 | apply form `noValidate` + the app's own messages (name, email, resume, salary, consent) in the company language |
| A3 | phone: the 12 filters fold behind one "Filters (n)" button; results first |
| P4 | `f_domain` capped at the resume's total experience (overlapping roles were added twice: "7.0 years" of 5) - test |
| P5 | next-step buttons in sentence case ("Schedule interview", "Check salary", "Create offer", ...); score chart legend items spaced; "We call them … (full name - set the first name)" -> "Name used in emails … (the full name, until you set the first name)" |
| I3 | booking line "Booked: 1 Jan 2025, 10:00 am" (year always) and no "with the interviewer" when none was chosen |
| S3 | (with B1) approve says "No department budget is set - nothing was reserved"; history says "Salary form link made - not emailed (no mailbox)" when the log has `sent: false` |
| B2 | /bgv and /offers: with no job chosen the stage table is the page - the "Choose a job" card is gone |
| B3 | done in 27.1 |
| M1 | /me for an admin without an employee record: "Create my employee record" / "Link to an existing one" (employee ID or company email; never a record another login owns; audit `employee_linked_to_login`); others keep "ask HR". The installer's first admin gets a linked record. 3 tests |
| ST2 | the missing keys added (`settingsHome.page.company.modules`, 8 `purpose.*` - the catalog has one more than the report saw - `nav.home`, `nav.recruitment`, plus `nav.core_hr`, `nav.separation` found by the new test). Tests that fail on a missing key built at run time: `src/i18n/dynamicKeys.test.ts` (Settings catalog), `tests/test_ui_text_keys.py` (every connection purpose, module and menu label, EN/HI/TA) |
| ST3 | approval steps: name + "Version 1 · Live" / "Draft" / "Replaced"; no internal key; "Try it" instead of "Simulate" |
| X3 | /superadmin kept (owner): `noindex, nofollow` on the page, `robots.txt` disallows it; console sign-in rate-limited (10 per 15 min per IP / email -> 429) |
| Tours | one "Don't show tours again" per person on the server (`ux.tours_off`, user scope; bootstrap `ux.tours_off`); the tour's skip button sets it; "Show me how" still replays a tour - test |
| Dates | `utils/datetime.formatDate / formatDateTime` (en-IN, year whenever it is not this year, or always): the 39 files with plain `new Date(x).toLocaleDateString() / toLocaleString()` now use it; calls with their own options are unchanged |

i18n:check 0 missing (5093 keys). Frontend unit tests 40 passed / the same 3 old failures. Affected backend files: only baseline failures.
