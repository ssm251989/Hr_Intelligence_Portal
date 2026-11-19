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
