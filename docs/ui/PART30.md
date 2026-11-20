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
