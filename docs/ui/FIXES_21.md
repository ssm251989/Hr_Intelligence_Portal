# PART 21 - proof

Spec: docs/PART21_OWNER_CHANGES.txt. One section per item.

## 21.3 Bug: auto-shortlist "doesn't email the interviewer" (2026-10-06)

**Real cause, from the audit log of the two real cases (no code path was broken):**

`ce0f3340` (careers application, Junior AI Developer):
```
15:37:42 ai_auto_shortlisted system {'score': 96.0, ..., 'undo_until': '2026-10-07T05:07:42Z'}   <- 10:37 IST NEXT DAY
15:40:50 interview_negotiation_retry_triggered kg@ctdtechs.com                                    <- owner's "Retry", 3 min later
15:40:54 interview_negotiation_interviewer_attempt kg@ctdtechs.com {'outcome': 'offer_sent', 'interviewer': 'Kishore'}
```
`efa8bc20`: `22:40:21 ai_auto_shortlisted ... 'undo_until': '2026-10-06T07:30:00Z'` (13:00 IST next day), then Retry at 22:45.

- **The undo window is 4 working hours** (`recruitment.shortlisting.undo_hours` = 4, counted Mon-Fri inside business hours by `_add_business_hours`). An afternoon or evening shortlist therefore releases the next morning.
- **The release job was running fine:** Health `interview_automation` `{'ok': True, 'result': "{'ctd-techs': {'released': 0, 'retried': 0}}", every 60 s}`. `auto_shortlist_released` had **never** been written (count 0), because every test was retried by hand before its window ended.
- **The profile said** "Shortlisted - interview times go out soon", so it looked stuck.
- **Retry vs auto:** both ended in `attempt_auto_negotiate_interview_slots`, but **Retry skipped `automation.start()`**: the scheduling-mode check, the "never silent" problem to-do and the mailbox retries. A Retry inside the window also left the window open.

**Fix:**
- "Retry scheduling" (`negotiation.retry_negotiation`) now calls **the same `automation.start()`** as the auto release (trigger `retry`). A retry inside the undo window ends it (logged `auto_shortlist_released`, "retry scheduling (undo window ended early)"), so the background release can't start a second round.
- The profile now says **when** the emails go out: "Shortlisted - interview emails go out automatically at <date, time>" + "The undo window (working hours only) ends at …; then the interviewer and the candidate are emailed automatically. To start now, use Send interview times now." (en/hi/ta).
- Flow order unchanged (decision: it is the owner-approved interviewer-first negotiation). After the window, the **interviewer** is emailed first to pick times; the candidate then gets the choices; once the candidate picks, both get the invite + meeting link. Failures already show on the profile + Home to-do with the reason and a retry.

**Proof (no manual click by HR):**
- **Setup:**
  - a proof job with auto-shortlist and `undo_hours` 0
  - its own pool with demo interviewer Diya (TEST mailbox)
  - 2 proof candidates whose addresses were TEST mailboxes, so nothing left the server
  - the real auto-shortlist function `maybe_auto_shortlist` ran on both
- **What happened, by itself (the live app's minute job):**
```
20:35:58 ai_auto_shortlisted system   (both)
20:36:23/24 auto_shortlist_released system {'trigger': 'undo window closed'}
20:36:24 interview_negotiation_interviewer_attempt {'outcome': 'offer_sent', 'interviewer': 'Demo - Diya Nair'}
20:36:24 interview_scheduling_started {'trigger': 'auto_release'}
20:36:24 auto_shortlist_release_result {'outcome': 'started'}
```
- **Interviewer:** Diya's test inbox got both "Interview scheduling for Proof job - auto shortlist test" emails at 20:36:24 (fix21-as-01).
- **Candidates:** the interviewer then picked times on the email link (her action, not HR's). Both candidates' test inboxes got their time-choice email at 20:36:57. The profile shows "Waiting for Proof Auto One to pick a time - email sent 8:36 PM" (fix21-as-02).
- All proof records were removed afterwards.

Note: the proof used the TEST-mailbox inboxes instead of mailpit, because the release is done by the live app's background job (the point of the test), which doesn't use the proof stack's mail capture.

## 21.1 Closed jobs go to the Recycle bin after N days (2026-10-06)

**Built** (`app/jobs/cleanup.py`, migration `b4ad3e4f5a6b`):
- **Settings > Hiring > Closed jobs:**
  - "Move closed jobs to the Recycle bin" (on) and "after [30] days"
  - "Keep candidates of closed jobs in the talent pool" (on)
  - how long the bin keeps items (`recruitment.candidates.recycle_days`, 30)
  - Decision: the spec says both "0 = never" and "a 0-day setting moves to the bin". So **0 days = at the next daily run**, and the on/off switch is "never".
- **Daily job `closed_jobs_cleanup`** (Health: "Closed jobs to Recycle bin"), for every closed job past N days:
  - **What moves:** the job, and its applications (and through them screening scores, shortlist, interviews + scorecards, offers, documents) go to the bin.
    - `job_roles.deleted_at`; applications `removed_at` + `removed_reason = 'job_cleanup'`
    - hidden everywhere by the same global filter as removed candidates, now also covering jobs
  - **Links stopped:** open interview, confirmation and salary/document form links; queued emails suppressed; budget released.
  - **Never touched:** people hired / employees (offer signed, onboarding started/completed, employee record). Their application stays.
  - **Candidates:** "keep in talent pool" on -> the candidate profile + resume stay; off -> a candidate with nothing else open goes to the bin too.
  - **Purge:** binned jobs past the bin time limit are deleted permanently, except one still linked to a hired person (kept, restorable).
  - **Audit:** `job_moved_to_recycle_bin` per job and `closed_jobs_cleanup_run` per run (jobs moved, counts).
- **closed_at:** automatic closes (deadline passed, all positions filled) now set `closed_at` too. Older jobs fall back to the close audit date.
- **Warning:** from 3 days before, the job shows "Will move to the Recycle bin on <date>" with **[Keep this job]** (pauses the clean-up for that job).
- **Recycle bin:** new **Candidates | Jobs** tabs.
  - Jobs: closed, moved (by whom), applications, "deleted for good on", **Restore** (the job + exactly what moved with it; then it won't be moved again automatically) and **Delete permanently**.

**Proof** (live app + temporary admin; two proof jobs; all removed afterwards):
- **Safety check before the live job ran:** the only real closed job (Junior AI Developer, closed today) moves on 5 Nov.
- **Automatic move:** Proof job A (closed 31 days ago; 1 ordinary candidate + 1 hired person) was moved **by the live app's own daily job** on its first run:
  - `closed_jobs_cleanup_run {'jobs_moved': ['Proof job A - closed 31 days'], 'applications': 1, 'kept_hired': 1, 'candidates': 0}`
  - DB: job `deleted_by 'system (closed 30+ days)'`
  - the ordinary application `removed_reason 'job_cleanup'`, its candidate **not** deleted (talent pool)
  - the hired person's application untouched
  - Screenshot: fix21-cj-01.
- **Warning + Keep:** Proof job B (closed 28 days ago) showed "Will move to the Recycle bin on 10/8/2026" + Keep this job (fix21-cj-02). Clicking Keep set `cleanup_paused_by` (fix21-cj-03).
- **Restore:** Recycle bin > Jobs listed job A (closed 9/5, moved 10/6 by system, 1 application, deleted for good 11/5) (fix21-cj-04). **Restore** -> job and application back (`deleted_at` / `removed_at` null) (fix21-cj-05).
- **Delete permanently:**
  - job A was **refused** ("Someone hired through this job is still linked to it, so the job is kept…")
  - job B (no hires) was deleted for good
- **Settings page:** fix21-cj-06.

Small known limit: the Jobs page "Recent activity" names a binned job "a job" (its title lookup is hidden by the bin filter). The title is in the audit details.

## 21.2 When a person exits, their hiring data goes to the Recycle bin (2026-10-06)

**Built** (`app/employees/hiring_on_exit.py`):
- **Trigger:** exit completed (`exit_checklist.try_complete`). With "after 0 days" it moves straight away; otherwise the daily job `hiring_data_after_exit` moves it N days after completion.
- **Moves to the bin** (each a checkbox in **Settings > Onboarding & employees > After exit**, all on by default):
  - candidate record (resume, salary-form payslips)
  - applications with their screening scores, shortlist, interviews + scorecards
  - interview / confirmation / salary / document form links (stopped)
  - candidate emails in the HR inbox
  - pre-joining welcome portal (link stopped)
- **Hidden everywhere:** by the global bin filter, which now also hides a binned candidate's HR-inbox emails.
- **KEPT** (never moved): employee record, signed offer letter, joining documents, BGV result, relieving / experience letters, exit record + exit interview, audit log.
- **Timeline note:** audit on the candidate, "Hiring data moved to Recycle bin on exit (<date>)"; also the candidate's bin note.
- **Restore:** Recycle bin > Candidates shows the person with reason **"Exit completed"**; Restore brings everything back.
- **Permanent delete:** after the bin's time limit, only the **hiring-only rows** are deleted for good (interviews + scorecards, screening results, links, inbox emails, resume file, payslips). The candidate / application / offer / BGV rows behind the kept records stay, hidden; then it leaves the bin.
  - Decision: the old candidate permanent delete would have cascaded into the signed offer and BGV records, which must be kept.

**Proof** (proof hire "Proof Leaver Arjun" CTD-9901: candidate, application, interview + scorecard, signed offer, BGV document, inbox email, employee on notice; exit completed by the real `try_complete`; all removed afterwards):
| Data | After exit completed: visible / exists |
|---|---|
| candidate | 0 / 1 (in the bin, reason `exit`, note "Hiring data moved to the Recycle bin on exit (06 Oct 2026)") |
| application | 0 / 1 |
| interview + scorecard | 0 / 1 |
| HR-inbox email | 0 / 1 |
| signed offer | **1 / 1 (kept)** |
| BGV document | **1 / 1 (kept)** |
| employee | **1 / 1 (kept)** |

- Audit: `hiring_data_moved_on_exit {'moved': {'candidate': 1, 'applications': 1, 'inbox_emails': 1}}`.
- Recycle bin shows "Proof Leaver Arjun - Exit completed" (fix21-hx-01). The employee profile is still there (fix21-hx-02). Settings > After exit (fix21-hx-03).
- **Restore** in the UI -> candidate and application back (fix21-hx-04).
- **Bin time limit** (put back in the bin dated 40 days ago, daily job run): `{'purged': 1}`.
  - interview and inbox email deleted for good
  - candidate, application, signed offer and BGV rows still there (hidden)
  - no longer listed in the bin

**Note - real data:** the same daily run also moved the hiring data of the real completed exit **EMP-00022 Jagadeesh T** (exit completed in the live app at 17:05 today): candidate, application, 4 open form links stopped, portal link closed. This is exactly what the new rule does for every completed exit (the live app's own daily job would have done it within a day), and it can be restored from Recycle bin > Candidates.

## 21.8 Sidebar: only one group open at a time (2026-10-06)

**Before:** each group remembered its own open/closed state, so several groups (Candidates, Screening, Interviews...) could be open together.

**Now** (`layout/AppLayout.tsx`): an accordion.
- Opening a group closes the one that was open.
- Going to a page opens that page's own group and closes the others.
- The choice is remembered per page in the browser (`hr-automation-sidebar-open`), so a reload shows the same state.
- The narrow icon-only menu has no sub-lists (as before); widening it again shows the current group.

**Proof** (live app, temporary admin, removed afterwards):
| Check | Screenshot |
|---|---|
| On Candidates: only Candidates is open | fix21-acc-01 |
| Click Interviews: Interviews opens, Candidates closes | fix21-acc-02 |
| Reload the Candidates page: the remembered choice (Interviews open) comes back | fix21-acc-03 |
| Narrow icon menu, then widen again: the Interviews group shows open | fix21-acc-04, fix21-acc-05 |
