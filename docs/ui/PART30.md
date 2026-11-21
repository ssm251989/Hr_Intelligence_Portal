# PART 30 - Job agent, public APIs + webhooks, interview-outcome card - proof (2026-11-20)

## 30.1g Job agent end to end (real model, all mail to Mailpit)

Proof stack: Mailpit (SMTP :1025, UI :8025), API :8010 with `DEV_MAIL_CAPTURE=127.0.0.1:1025` and
`CORS_ORIGINS=http://127.0.0.1:5174`, web :5174 (`VITE_API_BASE_URL=http://127.0.0.1:8010`), proof admin
`proof.admin.p23@example.com`, the real model (`agents.job` -> claude-sonnet-5). Browser: playwright-core + the installed
Chromium. Every database migrated with `hrctl.migrate --all-tenants --control-plane`.

| # | Step | Result | OK |
|---|---|---|---|
| A | Jobs > New job, type the title, Next (the wizard saves the job as a draft), stay in the wizard | **49 s later the agent drafted a JD from the title alone** ("Department: Not specified ... Responsibilities: Not specified") with one real model call and raised "Publish ... P30A" while HR was still on step 2 (`p30g-a1`, `p30g-a2`) -> fix 1 | no -> fix 1 |
| B | Same, then the wizard's later steps (skills, responsibilities, salary band: the same `PATCH /jobs/{id}` the wizard sends), leave the wizard without publishing | Nothing for 10 min after the last save (no card, no AI call; the job waits in `autopilot_state` "job.waiting"). 19:05:59 (10.5 min after the last save): one `agents.job` call, card "Publish Proof Backend Engineer P30B" with a JD drafted from the finished inputs (skills, responsibilities; no invented salary or benefit) (`p30g-b1`) | yes |
| B2 | The card listed "hiring manager" as missing although the PATCH sent `hiring_manager_id` (200) | `JobRoleUpdate` has no `hiring_manager_id` and no screen sets a job's hiring manager (no field in the wizard, no hiring-team UI), so a card that required one could never be approved -> fix 2 | no -> fix 2 |
| C | Approve while the job has no interviewer pool | Refused on the screen: "Fill before publishing: interviewer pool. Add it on the job, then approve again." Card stays pending, job stays draft (`p30g-b2`) | yes |
| C2 | Interviewers page: hours for the proof interviewer (`zzverify-interviewer@example.com`), pool for the job; "Change and approve", add one line ("Work model: hybrid, 3 days a week in the Chennai office."), Approve | Job **published** (careers page ticked), the edited JD saved (ends with the added line), card `edited`, AI decision log `final_decision = edited` (`p30g-c1`, `p30g-c2`). The dialog still said "fill before publishing: interviewer pool" after the pool was added -> fix 3 | yes (fix 3) |
| D | Careers page | "Proof Backend Engineer P30B" listed (`p30g-d1`) | yes |
| E | HR agents > activity > Journey on the job | "Prepared Publish ..." (7:05 pm) -> "Proof Backend Engineer P30B was published (careers page)." (7:09 pm) (`p30g-e1`) | yes |
| F | Delete the leftover P30A draft (Jobs screen's Delete) | Its card closed 74 s later: "Closed: the job no longer exists.", timeline "Closed the card ..." (after fix 4) | yes (fix 4) |
| G | Mailpit | Nothing from this proof (the only message is an unrelated `@example.com` fixture at 18:54); no real email | yes |

### Bugs found and fixed (each has a test that fails on the old code, `tests/test_job_agent.py`)

1. **The agent drafted a JD while HR was still in the wizard.** Cause: the Jobs wizard creates the job at its first
   step (title only) and fills skills, salary and JD in the next steps; the agent acted on `job_role_created` a
   minute later. Now a new job waits until it has not been saved for 10 minutes (`jobs.QUIET`), checked every minute;
   a job published, deleted or moved out of draft in the meantime simply leaves the list; nothing older than the
   agent is replayed. Tests: `test_a_job_still_being_edited_in_the_wizard_waits_for_hr`,
   `test_a_job_published_from_the_wizard_never_gets_a_card`. **Owner note:** 30.1g asked for the card "within 2 min";
   with the wait it comes ~10-11 min after HR's last change. A job published from the wizard never gets a card.
2. **"Hiring manager" blocked a card nobody could unblock.** It is now a reminder ("Not set yet (does not block
   publishing)"); the job owner stands in for it (30.3 already falls back to the job owner). Salary band and
   interviewer pool still block - both can be filled on the screens. Test: `test_no_hiring_manager_is_a_reminder_not_a_block`,
   `test_missing_interviewer_pool_blocks`. **Owner question:** should the Jobs wizard get a "Hiring manager" field?
3. **The card's "fill before publishing" list went stale.** The Waiting list now shows it live (the approval already
   checked it live). Test: `test_waiting_list_shows_what_is_still_missing_now`. (My approvals shows the card's text
   as made.)
4. **Deleting the job left its card open until the hourly run.** `job_role_deleted` is now read by the per-minute
   run, which then closes the card. Test: `test_deleting_the_job_on_the_screen_closes_its_card_within_the_minute`.

Not changed (outside 30.1): `PATCH /jobs/{id}` silently ignores `hiring_manager_id` (200, nothing saved).

Screenshots: `docs/ui/screens/p30/p30g-*.png`.

## 30.2h Public API + webhooks against a sandbox company (real model, all mail to Mailpit)

Stack: one API on :8011 in `TENANCY_MODE=multi` (the :8010 API stopped, so only one process polls mail / runs jobs),
`DEV_MAIL_CAPTURE=127.0.0.1:1025`; a local receiver on :9030 that checks `X-Signature` with the secret; the sandbox web
app on :5175 (`http://sandbox.localhost:5175`). Calls and answers: `docs/ui/PART30_API_CURLS.md`.

Sandbox: `hrctl tenant create --slug ctd-techs-sandbox --isolation shared_rls --admin-email sandbox.admin@example.com
--domain sandbox.localhost`. A first try with the default `dedicated_db` was deleted (`hrctl tenant delete --confirm
--drop-database`): this build serves every request from the one installation database (`get_db` has a single engine),
so a dedicated-db company is never reachable; the slug `sandbox` stays taken by the deleted row, hence
`ctd-techs-sandbox` (test mode accepts `sandbox` and `<company>-sandbox`). Setup the sandbox needed, done without mail:
the platform AI connection (the Anthropic part of `hrctl.migrate_connections` only - never the HR mailbox), and its
hiring modules activated with `module_status.activate` (the activation request would email CTD's approvers through the
HR mailbox connection, whose capture I could not confirm for every connector type).

| # | Step | Result | OK |
|---|---|---|---|
| a | Developers page as the sandbox admin: test key (5 scopes), webhook to `http://127.0.0.1:9030/hook` (6 events), test ping | Key `hra_test_e2b84b39...` shown once; secret `whsec_...` shown once; ping delivered 200, signature verified (`p30h-developers.png`) | yes |
| b | Key errors | no key 401 `missing_key`; unknown key 401 `invalid_key`; a live key on the sandbox 403 `wrong_mode` | yes |
| c | `POST /jobs` + the same `Idempotency-Key` again | 201 draft; the replay returned the same id with `Idempotent-Replay: true` | yes |
| c2 | That first job was created while the sandbox's Jobs module was not active (every module off) | **The API created it** - the module gate knew only screen paths -> fix 6 | no -> fix 6 |
| d | `POST /jd-drafts` (real model) | Before the AI connection: plain-text "Internal Server Error" -> fix 5; after: a JD from the inputs, decision log id | yes (fix 5) |
| e | `POST /screenings` | job without a JD -> 422 (says so); short `resume_text` -> "No readable text found in this file" -> fix 7; whole resume + JD text -> score 85, location 100 | yes (fix 7) |
| f | Job 2 via `POST /jobs` at 22:18:18 -> `GET /cards` | 22:28:24 "Publish Sandbox Backend Developer" (JD drafted, only the hiring-manager reminder) | yes |
| g | `POST /cards/{id}/decision` approve | Job published on the careers page through the Jobs screen's Publish; `GET /jobs/{id}` status `published`, `has_jd` true | yes |
| h | `POST /jobs/{id}/applications` (Kiran Das, docx resume, consent text) | 201 `received`; resume read + screened by the app with the real model: score 98; the Screening agent's "Shortlist Kiran Das" card shows as `waiting_card` on `GET /applications/{id}` | yes |
| i | Approve the shortlist card by API | Shortlisted (`hr_selected`, next step "Interview times are being arranged"), but interview scheduling failed: `UniqueViolation` on `interview_scheduling_settings` (see "Not fixed") - the candidate flow stops here on a shared-RLS sandbox | no (owner) |
| j | Webhooks for the candidate (receiver log) | ping, card.created (Publish), job.published, application.created, application.screened, card.decided (Publish), card.created (Shortlist), card.decided (Shortlist) - **every signature verified** (`p30h-delivery-log.png`) | yes |
| k | `GET /applications/{id}/journey` | screened 98 -> shortlist prepared | yes |
| l | Mailpit | No new message from this proof (86 before and after) | yes |

### Bugs found and fixed (tests in `tests/test_public_api.py`, each fails on the old code)

5. **An unexpected error answered plain text.** The metering middleware let the exception through; now any error keeps
   the `{"error"}` shape (500 `server_error`), a missing AI connection is 503 `ai_unavailable`, and both are metered.
   Test: `test_an_unexpected_error_keeps_the_error_shape_and_is_metered`.
6. **The API ignored module activation.** Each scope now needs its module active (jobs, candidates, screening,
   interviews), else 403 `module_not_active`; cards follow their own permissions. Test:
   `test_a_module_the_company_has_not_activated_is_refused`.
7. **Screening hid the reason / spoke of "this file" for typed text.** The parser's plain message is returned (503 for
   AI-side reasons), and a `resume_text` under 80 letters is refused up front (`resume_too_short`). Tests:
   `test_screening_says_why_the_ai_refused`, the short-text case in `test_screening_scores_against_a_job_without_storing_anything`.

### Not fixed - owner decision (outside Part 30)

- **Shared-RLS companies cannot schedule interviews (and have no HR mailbox / local-import settings).**
  `interview_scheduling_settings`, `hr_integrations` and `local_import_settings` are one-row-per-installation tables
  (`id = 1`); in a second company on the same database RLS hides tenant #1's row and the code's "create it if missing"
  hits the primary key. A fix keys them by company (migration + three getters); `hr_integrations` holds the HR mailbox
  credentials, so it needs care. Until then a sandbox proves the API up to the shortlist, not the interview.
- **Dedicated-db companies are not reachable by the app in this build** (one database engine), so test mode needs a
  shared-RLS sandbox.

## 30.3f Interview-outcome card with a booked interview (real model, Mailpit) - also the skipped 29.3d proof

Live company, proof API :8010 (`DEV_MAIL_CAPTURE`), proof people `hm.p30@example.com` (hiring manager of the job),
`iv1.p30@` / `iv2.p30@example.com` (interviewers), candidate `divya.p30c@example.com` (shortlisted, `hr_selected`).

| # | Step | Result | OK |
|---|---|---|---|
| a | The recruiter books two interviews (the screen's `POST /applications/{id}/interviews`, 4 min ahead, one per interviewer) | both 201; candidate `interview_scheduled` | yes |
| b | After the interview time each interviewer sends a scorecard (the screen's `PATCH /interviews/{id}/feedback`): 5/5 and 4/4, both "Move forward", notes | 200 / 200; no decision recorded by either | yes |
| c | Card | 12:02:45 (1.5 min after the second scorecard): "Interview result for Divya Raman (P30C): Strong technical performer; solid system design and communication skills", real summary (strengths, concern "could go deeper on caching", no disagreements), default = majority "Move forward", named reviewer = `hm.p30@example.com` (`p30c-1`, `p30c-2`) | yes |
| c2 | The card named the interviewers "Interviewer 1 / 2" | interviews booked on the recruiter screen keep only `interviewer_id` -> fix 8 | no -> fix 8 |
| d | The hiring manager presses Approve on HR agents | **"Missing permission: agents.suggestion.view"** - the decision endpoint asked a general permission hiring managers do not have -> fix 9; after it: "Approved - the agents carry on." (`p30c-3`) | yes (fix 9) |
| e | What follows (the feedback screen's own decision code) | candidate `interview_selected`; `salary_checked` (band 12-18 L) and `salary_form_sent` by `hm.p30@example.com`; **Mailpit: "Proof Platform Engineer (P30C): your salary and joining details" to divya.p30c@example.com** | yes |

### Bugs found and fixed (tests in `tests/test_interview_outcome.py`, each fails on the old code)

8. **Interviewers unnamed on the card.** The card now uses the interviewer's account name when the interview has only
   `interviewer_id` (the AI still gets "Interviewer 1 / 2", never names). Test: `test_interviewers_booked_on_the_screen_are_named_on_the_card`.
9. **The named hiring manager could not decide.** `POST /api/v1/intelligence/agents/suggestions/{id}/decision` required
   `agents.suggestion.view`; now a card's named reviewer may decide that card, everyone else still needs the permission,
   and `decide()` applies the card's own rules. Test: `test_the_named_hiring_manager_can_decide_through_the_screen_endpoint`.

Who may decide the card: only its named reviewer (the job's hiring manager, or the job owner when none is set). The
card's permission code is deliberately not a registered permission - registering it would give it to every Hiring
Manager through the role template.
