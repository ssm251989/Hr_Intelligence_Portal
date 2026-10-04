# Part 19 - Choose modules + activation code by email: proof

Spec: `Claude outputs/PART19_MODULE_ACTIVATION.txt` (owner, 2026-10-03). Part 19 replaces 18.4 (the one shared module passcode).

**Commits:**
- part-19.1 `c7e20f1`: backend
- part-19.2 `2359c7f`: frontend
- part-19.3: this proof, plus the fixes it found (below)

**How it was proved:**
- **Demo companies:** two new ones on the shared database: **demo-a** "Demo - A (Jobs only)" and **demo-b** "Demo - B (Candidates + Screening)", with hosts `demo-a.localhost` and `demo-b.localhost`.
- **Live API:** a second server (`uvicorn` on :8010, `TENANCY_MODE=multi`) answers per host.
  - Every 403 below is a real HTTP response from that server, without signing in; the module gate runs before sign-in.
  - The owner's own server (:8000, ctd-techs) was left untouched.
- **Request / activate:** the real service functions (`activation.request_activation` / `activate_with_code`), run as each demo company's own admin row.
- **Email:** Docker isn't on this machine, so there is no mailpit. A small local SMTP capture (127.0.0.1:1025, writes `.eml` files, never relays) stands in for it. The PLATFORM mailbox (`PLATFORM_SMTP_*`) points at it for the proof only.
- **Codes:** the code is read from the captured email, as CTD Techs would. Codes are written as `****-****` here (never in git).

## 19.1 Choose what you use

**Starting point:** a new company starts with every module **off**.

```
hrctl modules status --tenant demo-a  -> jobs off, candidates off, ... genai_usage off (all 12)
host demo-a  GET /candidates        -> 403 {"code":"MODULE_NOT_ACTIVE","message":"This module is not active for your company","module":"candidates",...}
host demo-a  GET /api/v1/ui/jobs    -> 403 MODULE_NOT_ACTIVE (jobs)
host demo-a  GET /screening/settings-> 403 MODULE_NOT_ACTIVE (screening)
```

**Existing company (ctd-techs) - no change in behaviour:**
- The migration backfilled all 10 hiring modules as active.
- Onboarding stays **off**. It was already off: kg@ctdtechs.com switched every optional module off on 2026-10-03 21:19, setting `[]`.
```
hrctl modules status --tenant ctd-techs -> jobs, candidates, screening, shortlisting, interviews, candidate_emails, salary, bgv, offers, reports, genai_usage: active; onboarding: off
menu (bootstrap)  /, /approvals, /jobs, /candidates/dashboard, /screening/dashboard, /shortlisting/dashboard, /interviews/dashboard,
                  /hr-inbox, /salary, /bgv, /offers, /agencies, /reports, /genai-usage, /setup, /settings   (same as before)
:8000 GET /candidates -> 401 (active, sign-in needed)    GET /api/v1/ui/onboarding/board -> 403 MODULE_NOT_ACTIVE (was 404 MODULE_DISABLED)
```

## Demo A - Jobs only

```
request [jobs]          -> pending, email_sent true, expires 10 Oct 2026 21:57 IST
status                  -> jobs: pending
wrong code ABCD-EFGH    -> 400 "This code is not correct. 4 tries left."
right code              -> activated [jobs]
same code again         -> 400 "This code has already been used."
menu                    -> /, /approvals, /jobs, /genai-usage, /setup, /settings
                           (GenAI usage comes with any AI module; Jobs has the AI job description)
host demo-a GET /candidates            -> 403 MODULE_NOT_ACTIVE "This module is not active for your company"
host demo-a GET /api/v1/ui/candidates/x-> 403 MODULE_NOT_ACTIVE
host demo-a GET /api/v1/ui/salary/x    -> 403 MODULE_NOT_ACTIVE
host demo-a GET /api/v1/ui/jobs        -> passes the gate (404 for this sub-path = route level, not 403)
```

The spec's `/api/v1/candidates` is `/candidates` in this API. That path and `/api/v1/ui/candidates/*` are both gated.

**Captured email** (the approver's copy; this is what CTD Techs receives):

```
X-Envelope-From: <no-reply@ctdtechs.com>
X-Envelope-To: <kg@ctdtechs.com>
From: HR Platform <no-reply@ctdtechs.com>
To: kg@ctdtechs.com
Subject: Activation request - Demo - A (Jobs only) - Jobs

Company: Demo - A (Jobs only)
Installation: demo-a.localhost (company demo-a)
Requested by: admin@demo-a.localhost <admin@demo-a.localhost>
Modules: Jobs
Requested at: 03 Oct 2026, 21:57 IST

Activation code: ****-****
Valid until: 10 Oct 2026, 21:57 IST (works once)

Share this code with the company when they may use these modules. They enter it on
Settings > Company > Modules.
```

The company's own mailbox is never used, and the company is never a recipient.

## Demo B - Candidates + Screening, no job record

```
request [screening]           -> 409 MODULE_NEEDS "Also switch on Candidates? Screening needs Candidates."
request [screening] with needs-> pending [candidates, screening]; email to kg@ctdtechs.com, Subject "Activation request - Demo - B (Candidates + Screening) - Candidates, Screening"
wrong code                    -> 400 "This code is not correct. 4 tries left."
right code                    -> activated [candidates, screening]
same code again               -> 400 "This code has already been used."
menu                          -> /, /approvals, /candidates/dashboard, /screening/dashboard, /agencies, /genai-usage, /setup, /settings
host demo-b GET /candidates           -> 401 (active; sign-in needed)
host demo-b GET /api/v1/ui/screening/jd -> 401 (active)
host demo-b GET /api/v1/ui/jobs       -> 403 MODULE_NOT_ACTIVE
host demo-b GET /api/v1/ui/salary/x   -> 403 MODULE_NOT_ACTIVE
```

**Resume upload + AI reading + scoring with no job.** These are the real endpoint functions (`upload_resume`, `parse_candidate_resume`, `list_candidates`, `ui_jd_screening_router.run_screening`) using `Sample/ASWATH_T_AA.pdf`:

```
uploaded       candidate 4177829a… source manual
parsed (AI)    "ASWATH T", 5.0 years, skills: RPA, Automation Anywhere, UiPath, Linux, ServiceNow, Jira
talent pool    1 candidate (GET /candidates)
JD screening   "Demo - Senior Python developer" (pasted JD) -> ASWATH T: match 15, weak_fit   (an RPA profile vs a Python JD -- sensible)
job records    0      applications 0
```

**Menu notes:**
- Agencies shows with Candidates: it is how agencies send candidates, so it belongs to that module.
- People, Exits, Assets and Analytics are not in Part 19's list. A new company now starts with them off: the `platform.modules.enabled` default changed to `[]`. They stay under "Other modules".

## Wrong / expired / used code, lockout

```
used code                      -> 400 CODE_USED "This code has already been used."            (A and B above)
expired (demo-b, [reports], expires_at moved 1 min into the past)
                               -> 400 CODE_EXPIRED "This code has expired - request a new one."
                                  page then shows the expired banner + "Request a new code" (open_request -> status "expired")
5 wrong tries (demo-a, [reports])
                               -> 4, 3, 2, 1 tries left, then 429 "…code entry is locked for 30 minutes and CTD Techs has been told."
right code while locked        -> 429 "Too many wrong tries. Please wait 30 minutes and try again."
lock email (captured)          -> To kg@ctdtechs.com, Subject "Activation code locked - Demo - A (Jobs only)",
                                  "…entered a wrong activation code 5 times. Modules requested: Reports … locked until 03 Oct 2026, 22:28 IST."
switch off Candidates (demo-b) -> 409 MODULE_NEEDED "Screening needs this module. Switch it off too?" (nothing changed)
```

## Approver must be @ctdtechs.com

```
ACTIVATION_APPROVER_EMAILS=someone@gmail.com  python -c "import app.main"
  -> RuntimeError: Module activation is misconfigured: someone@gmail.com is not a ctdtechs.com address. Activation codes only go to ctdtechs.com.
ACTIVATION_ALLOWED_DOMAIN=ctdtechs.com.evil.io ACTIVATION_APPROVER_EMAILS=kg@ctdtechs.com.evil.io  python -c "import app.main"
  -> RuntimeError: … ACTIVATION_ALLOWED_DOMAIN must be ctdtechs.com (or under it), not 'ctdtechs.com.evil.io'.
hrctl activation set-approver kg@gmail.com              -> refused: kg@gmail.com is not a ctdtechs.com address.
hrctl activation set-approver kg@ctdtechs.com.evil.com  -> refused
hrctl activation set-approver kg@ctdtechs.com           -> {"approvers": ["kg@ctdtechs.com"]}
```

The approver list is also checked again on every send.

## Found by this proof and fixed

1. **A successful activation returned a server error.** After the control-plane session closed, `activate_with_code` read `match.id` (and `request_activation` read `previous.id`): `DetachedInstanceError`. The modules were already active, but the page would have said "Something went wrong" and the audit entry was lost. Fix: the IDs are read before the session closes; the run above is after the fix.
2. **Expired code left the page stuck.** After an expired code there was no waiting request, so the page showed the module as "waiting" with no way forward. `open_request` now returns the expired request, and the page offers "Request a new code".
3. **New companies started with older optional modules switched on.** Assets, Exits, Analytics and the assistant were on by default. The default is now `[]` (only what the company chooses).

## Checks

- Backend: `compileall` OK; `alembic upgrade head` (tenant b19c1d2e3f4a, control plane c19a2b3d4e5f) OK.
- Frontend: `tsc -p tsconfig.app.json` clean; i18n 3919 keys, 0 missing (en/hi/ta); `npm run build` OK.

## Screenshots - pending login proof

The picker, waiting banner, code entry and final menus are signed-in screens. This session could not sign in: token creation and the probe helper were both refused. So no screenshots were taken, as with the earlier "pending login proof" entries. To take them:
1. Sign in as an admin of a demo company, or ctd-techs.
2. Open Settings > Company > Modules.
3. Run `frontend/scripts/take_screenshots.mjs` with `SHOT_ONLY=settings,setup`.

## Left in place for the owner

- **Demo companies:** demo-a and demo-b (control plane + rows on the shared database) and their activation requests. Remove them with `python -m hrctl.tenant delete --slug demo-a --confirm demo-a` (same for demo-b). That deletes data, so it is the owner's call.
- **Platform mailbox:** not configured on this machine (`PLATFORM_SMTP_HOST` empty). Until it is set, a request is saved but its email isn't sent. The page says so, and the console's Resend sends it once the mailbox works.
- **Old passcode table:** `module_access` (Part 18.4) is no longer used and is empty for ctd-techs. Dropping it is a later contract migration.

---

# Part 19.2b / 19.2c - approvers by priority, escalation, resend, failed email (owner change 2026-10-03)

**Commits:**
- `fa18fe4` docs: PART19 at the top of RESUME
- `adcfd5f` 19.2c-A platform mailbox
- `706d7a6` 19.2b+c
- `7771a93` HR admin mailbox only

The 19.2b and 19.2c logic share one file (activation.py), so they are one commit.

## 19.2c-A - why the activation email to CTD Techs failed (real cause)

**What the owner saw:** "Your request is saved, but the email to CTD Techs couldn't be sent yet…"

**The saved request** (ctd-techs, 2026-10-03 22:06:28, by kg@ctdtechs.com, modules [jobs], now ACT-2026-00006). Its stored send error, verbatim:
```
The platform mailbox isn't set up (PLATFORM_SMTP_HOST).
```

**Cause:**
- No sending mailbox had been configured for activation emails: `PLATFORM_SMTP_HOST` was empty in `.env`.
- The dev mailpit can't run here (no Docker).
- The request itself was saved correctly; only the email never left.

**Fix:**
1. Added a sending mailbox with plain failure reasons. These go to the request history and the backend log, never to the company.
2. Dev: mailpit (Windows binary, SMTP with login, UI http://127.0.0.1:8025).
3. Owner instruction **"for sending use HR admin mail only"**: activation emails now go through **CTD Techs' own HR admin mailbox**. That is the ctd-techs "HR Mailbox (SMTP)" connection, hradmin65@gmail.com via smtp.gmail.com, which is CTD Techs' own mailbox. A requesting company's mailbox is never used.

**Test email:**
```
hrctl platform mailbox test --to kg@ctdtechs.com   (HR admin mailbox)  -> {"ok": true}
(first attempt from hrctl: KeyError 'Unknown provider: smtp' -- providers weren't registered outside the web app; fixed)
```

**Your live request ACT-2026-00013** (2026-10-04 delivery):
```
22:38:08 request  sent   [kg@ctdtechs.com]  client kg@ctdtechs.com          (went to dev mailpit -- mode was smtp then)
23:08:00 resend   failed [kg@ctdtechs.com]  ctd (HR admin mailbox)  Can't reach the mail server ([Errno 11001] getaddrinfo failed).   <- no network/DNS at that moment
14:58:06 retry    sent   [kg@ctdtechs.com]  system                          <- automatic retry, delivered through the HR admin mailbox
```
The modules (Jobs, Candidates, Screening, Shortlisting, Interviews, Candidate emails) are waiting for that code.

## 19.2b - approvers with priority 1/2/3

```
P1 KG kg@ctdtechs.com (seeded)       P2 / P3 empty until the owner provides them
set P2 someone@gmail.com             -> 400 APPROVER_NOT_ALLOWED "someone@gmail.com is not a ctdtechs.com address. Activation codes only go to ctdtechs.com."
set P2 p2@ctdtechs.com.evil.io       -> 400 APPROVER_NOT_ALLOWED
set P2 p2.test@ctdtechs.com, P3 p3.test@ctdtechs.com -> ok (audit: activation_approver_set, old -> new)
```

**Escalation** (escalation time set to 2 minutes for the proof), request ACT-2026-00008 from demo-a:
```
22:25:53 request    sent  to=kg@ctdtechs.com      by=client admin@demo-a.localhost
22:27:57 escalation sent  to=p2.test@ctdtechs.com by=system   first line: "Escalation: not actioned by kg@ctdtechs.com since 03 Oct 2026, 22:25 IST."
22:30:57 escalation sent  to=p3.test@ctdtechs.com by=system   first line: "Escalation: not actioned by p2.test@ctdtechs.com since 03 Oct 2026, 22:27 IST."
distinct codes in the 3 emails: 1   (the SAME code -- any approver can share it)
then: wrong code -> "This code is not correct. 4 tries left." ; right code -> Jobs active ; again -> "This code has already been used."
menu: /, /approvals, /jobs, /genai-usage, /setup, /settings
```
After the proof, the test approvers were removed and escalation went back to 24 h (P1 only, as the owner asked).

## Resend

**Company side** (demo-a, ACT-2026-00011):
```
resend                     -> sent (resent 1 time)
resend straight away       -> 429 "You can resend in 15 min."
cooldown 0 for the test    -> resends 2, 3, 4, 5 ok (… 0 left today)
6th resend in a day        -> 429 "You can resend at most 5 times a day. Please call CTD Techs and quote ACT-2026-00011."
company view               -> "request sent to CTD Techs on 3 Oct, 22:32 - resent 5 times"
```
The test found a bug: a setting of 0 was ignored because `int(value or 15)` treats 0 as unset. Fixed; the cooldown went back to 15 after the test.

**Console** (ACT-2026-00010):
```
Resend to priority 2 -> sent to p2.test@ctdtechs.com
Show code            -> ****-**** (shown once)
superadmin_audit     -> "activation_code_shown {request: ACT-2026-00010}", "activation_resent {priority: 2, sent: true}"
request history      -> request (client) / resend (client) / resend to p2 (ctd) / code_shown (ctd)
```

## 19.2c - email can't be sent: friendly message, retries, recovery

The proof broke the dev mailbox password, then made a request from demo-b (ACT-2026-00012).

**The company sees:**
- `number ACT-2026-00012`, `delivery not_sent`, Copy request number, Try sending again;
- the text "Your request is saved, but the email to CTD Techs couldn't be sent yet. We'll keep trying automatically. … Quote request number ACT-2026-00012 …".
- No SMTP reason and no code.

**Backend log:**
```
WARNING app.platform.activation [demo-b] activation email ACT-2026-00012 (request) to ['kg@ctdtechs.com'] failed:
        Signing in to the mail server failed (535 5.7.8 Authentication credentials invalid).
```

**Request history:**
```
22:32:35 request  failed  to=kg@ctdtechs.com  by=client admin@demo-b.localhost | Signing in to the mail server failed (535 5.7.8 Authentication credentials invalid).
22:34:13 retry    failed  to=kg@ctdtechs.com  by=system                        | (same)          <- automatic, +1 min
(mailbox password fixed at 22:34:38)
22:40:13 retry    sent    to=kg@ctdtechs.com  by=system                                         <- automatic, +5 min
company view -> delivery "sent", sent_at 22:40:13 (the page refreshes every 30 s while not sent)
```

**Retry and failure rules:**
- Backoff is 1, 5, 15, 60 min, then hourly up to 24 h. After that the console shows red "Email not delivered", and CTD can Resend or Show code.
- A refused address moves on to the next priority.
- An empty approver list or an unset mailbox gets a plain reason: the console health banner "Activation emails can't be sent - <reason>. [Fix platform mailbox]".
- Support phone / email / hours are platform settings and are empty until CTD Techs fills them. The company message then says "You can also contact CTD Techs."

## Expired code
```
demo-b ACT-2026-00014 (expires_at moved 1 min into the past) -> 400 "This code has expired - request a new one." ; company view status "expired" -> [Request a new code]
```

## Checks
- Backend: compileall OK; control-plane alembic `d19b2c3e4f5a` OK.
- Frontend: tsc clean; i18n 4007 keys, 0 missing (en/hi/ta); `npm run build` OK.

## Screenshots

The dev mailpit screenshots have the codes blurred to `****-****`:
- `screens/mailpit-inbox.png`: the request emails, numbered ACT-…, and the escalation to p3.test.
- `screens/mailpit-escalation-p2.png`: "Escalation: not actioned by kg@ctdtechs.com since 03 Oct 2026, 22:25 IST."
- `screens/mailpit-request-email.png`: demo B's request email to kg@ctdtechs.com (number, company, requester, modules, expiry).

**Signed-in screens -- pending login proof:** the picker, the waiting banner with Resend/Cancel, code entry, the final menu, and the console. This session cannot sign in: creating tokens and impersonating users are refused. Take them as shown in "How to try it" in the hand-over message.

---

# Interview automation (bug 2026-10-04: "Jagadeeswara Reddy shortlisted, no interview email")

## 1. Trace (real rows, ctd-techs, 2026-10-04)
```
candidate    Jagadeeswara Reddy  <gkishore1433@gmail.com>  uploaded 15:24:50 (manual), parsed
application  5894fd75…  job "Junior AI Developer" 0a040f96… (published, created 15:20:07)  status hr_selected, score 96
audit        15:24:50 candidate_uploaded · 15:24:56 ai_resume_parser_scored · 15:25:13 application_created
             15:25:19 ai_screening_scored · 15:25:19 ai_auto_shortlisted (system, score 96) · 15:25:19 salary_checked
undo window  recruitment.shortlisting.undo_hours = 4 (business hours) -> undo_until 2026-10-05T07:30Z = Mon 5 Oct 13:00 IST
messages     15:25:19 in_app to kg@ctdtechs.com "…shortlisted automatically… You can undo this for a few hours." (sent)
negotiation_tokens / interview_confirmation_tokens / interviews for this application: none
interviewer pools: ONE pool "AI interviewers" [kg@ctdtechs.com] -- attached to the OLD closed job 3ebd6e26… ("Junior AI Developer", 27 Sep);
                   none for the new published job 0a040f96…
availability: kg@ctdtechs.com Mon-Sun 10:00-18:00; si@, jr@, zzverify@ every day off
company modules: all hiring modules active (owner entered the code at 15:17-15:18)
HR mailbox (hr_integrations): smtp.gmail.com / hradmin65@gmail.com configured; last interview emails went out fine on 29 Sep
background jobs: auto_shortlist_released in audit_log = 0 (ever, for both auto-shortlists); processes = 2 x uvicorn, NO celery worker/beat; no REDIS_URL
```

## 2. Where the chain stopped
`shortlist event OK (auto, 15:25:19) -> undo window OK (until Mon 13:00) -> scheduling job queued: NEVER`

**Causes:**
- **Never released:** after an AUTOMATIC shortlist, scheduling only starts when the background job `auto_shortlist_release` runs after the undo window. That job runs only on the Celery worker/beat, which has never run on this machine, so no auto-shortlist was ever released ("0 ever").
- **No interviewer for the new job:** even once released, the next step would have failed. The interviewer pool belongs to the earlier, closed job with the same title, so the new job had no interviewer. The candidate would have been flagged "manual scheduling" silently: no to-do and no email to anyone.
- **No meeting link:** a booked interview got a calendar invite but no meeting link (`interviews.meeting_link` was never set on this path).

**The other checks:**
- A manual shortlist DID start scheduling straight away (shortlisting/router.py), but through a different call with no problem reporting.
- The mailbox was fine; this was not the activation-email problem.

## 3. Fixes (`backend/app/interview_scheduling/automation.py` + callers)
- **One start for both:** manual shortlist, auto-shortlist release and **[Send interview times now]** all call `automation.start()`.
  - It respects the scheduling mode: company setting `recruitment.interviews.scheduling_mode` = auto|manual, per job `shortlisting_json.scheduling_mode`.
- **Background run without a worker:**
  - The release + retries run every minute inside the app (APScheduler, `INTERVIEW_JOBS_IN_APP`, on when there is no REDIS_URL), and as Celery beat task `hrms.interview_automation` with a worker.
  - An advisory lock keeps it to one process; a heartbeat feeds the Health page.
- **Pool:** a job re-created with the same title uses the earlier job's pool (roster.pool_members_for_job).
- **Never silent:**
  - No interviewer / no free day -> red to-do "Interview not scheduled for <name> - <plain reason>" with [Add availability] [Schedule manually]. It shows on Home (heads-up), on the job (Job details) and on the profile (status card), and the recruiter is emailed once per reason.
  - The no-pool reason now says so: "No interviewer is set up for <job>. Add one … in Interviews > Interviewers."
- **Mailbox failure:** retried with backoff (5, 15, 60 min, then hourly for 24 h). The profile shows "Interview email not sent - mailbox problem. We'll try again at <time>" with [Fix mailbox], and Home shows the same with [Fix mailbox] [Schedule manually].
- **Profile in plain words:**
  - "Waiting: the undo window ends at Mon 5 Oct, 1:00 PM"
  - "Waiting for Kishore to pick interview times - email sent 3:47 PM"
  - "Waiting for <candidate> to pick a time"
  - "Booked: 5 Oct, 10:00 AM with Kishore - calendar invite and meeting link sent to both"
- **Profile buttons:** [Send interview times now], [Resend to candidate] / [Resend to interviewer] (the picker email while waiting; the invite + meeting link once booked).
- **Meeting link** for every booking: the company's own room (`recruitment.interviews.meeting_link`) if set, else a new Jitsi room. It goes in the invite's location, both emails and the interview record.
- **Worker health:** Settings > Data > Health is red when no worker runs (with the start command), plus a separate check that the interview automation ran in the last 10 minutes. The start command is in docs/RESUME.txt §6 and `scripts/start-dev.ps1`.
- **Dev only:** `DEV_MAIL_CAPTURE=127.0.0.1:1025` sends every email to mailpit.

## 4. Verification on Jagadeeswara Reddy

Setup: dev mailpit + a proof server on :8010 with DEV_MAIL_CAPTURE, so no real email left the machine.

```
before           profile: waiting_undo, undo_until 2026-10-05T07:30Z ; pool for the job now: [Kishore kg@ctdtechs.com] ; mode auto
send now 15:47   outcome started -> "Waiting for Kishore to pick interview times" ; mailpit: kg@ctdtechs.com "Interview scheduling for Junior AI Developer"
interviewer      picked 10:00 + 15:00 (Mon 5 Oct) -> "Thanks! We'll now ask the candidate…"
15:48:26         mailpit: gkishore1433@gmail.com "Interview scheduling for Junior AI Developer"
candidate        picked 10:00 + 15:00 -> "Interview Confirmed … Interviewer: Kishore, Time: 05 Oct 2026, 10:00 AM IST"
15:49:30         mailpit: "Interview confirmed: Junior AI Developer" to BOTH gkishore1433@gmail.com and kg@ctdtechs.com, each with interview.ics
                 body "Meeting link: https://meet.jit.si/Interview-HUo2m2M5HUu" ; ics LOCATION = same link, DTSTART 20261005T043000Z
profile          state scheduled, "Booked: 5 Oct 10:00 AM with Kishore", meeting_link set, invite_sent_to [interviewer, candidate]
resend to cand.  15:50:29 mailpit: "Interview confirmed…" to gkishore1433@gmail.com again (with invite)
send now again   "This candidate isn't at the Shortlisted step." (already booked)
```

**Failure paths** (proved on ctd-techs inside one transaction that was rolled back; 0 proof rows left):
```
no interviewer  start -> problem: "No interviewer is set up for Proof - Data Engineer …. Add one … in Interviews > Interviewers."
                profile not_scheduled ; Home problems [kind not_scheduled] ; recruiter email "Interview not scheduled for Proof Candidate … - action needed" (mailpit)
mailbox down    start -> retrying (WinError 10061 refused), next try +5 min ; profile mailbox_retry ; Home [kind mailbox] ; recruiter email attempt logged with its error
```

**Screenshots:**
- `screens/interview-interviewer-pick.png`, `interview-interviewer-done.png`, `interview-candidate-pick.png`, `interview-candidate-done.png`
- `screens/interview-mailpit-inbox.png`, `interview-confirmed-candidate-email.png`, `interview-confirmed-interviewer-email.png`, `interview-not-scheduled-recruiter-email.png`
- Signed-in screens (profile card, Home row, job banner): pending login proof.

**Important -- real data:** Jagadeeswara Reddy is now really booked in the app (Mon 5 Oct 10:00 with Kishore), but the emails went only to the dev mailpit. Neither the candidate nor kg@ctdtechs.com got real emails. On the candidate's page, use [Resend to candidate] and [Resend to interviewer] to send the real invites through the HR mailbox, or cancel and rebook.

**Checks:** compileall OK; tsc clean; i18n 4021 keys, 0 missing; `npm run build` OK.

---

# Interview link "not recognized" (bug 2026-10-04, after the data reset)

## 1. The real records (ctd-techs)
```
16:25-16:27  a candidate (Gunda Kishore, gkishore1433@gmail.com) was uploaded and shortlisted, and interview scheduling started:
             a negotiation token was created and its email (picker link) was sent through the HR mailbox.
16:27:35     kg@ctdtechs.com DELETED that candidate permanently (Candidates > Remove > Delete permanently):
             audit candidate_deleted {"related_rows": {"applications": 1, "negotiation_tokens": 1}, "audit_entries_removed": 12, ...}
16:27:54     the same person was uploaded again -> new candidate + application c7291dc9… (auto-shortlisted 16:28:04)
link in the earlier email -> its token row no longer existed -> "This link isn't recognized. Please use the exact link from your email..."
```
**The current link was fine.**
- Token `V3NWj5_h56BoFxG6nmzzO**********************`: 43 URL-safe characters, tenant ctd-techs, application c7291dc9…, created 16:30:29, expires 9 Oct, not used.
- `GET http://localhost:8000/interview-negotiation/<token>` -> 200 "Please pick exactly 2 of the 3 times…".
- The rendered email's text link and both HTML hrefs equal the built URL exactly.

You then completed it yourself:
- 16:31:11 the interviewer picked times.
- 16:31:41 the candidate picked.
- 16:31:50 confirmed: Mon 5 Oct 15:00 IST with a Jitsi link.

## 2. Comparison: URL token vs page vs DB
**What was ruled out:**
- The token is stored raw (not hashed) and compared exactly.
- No URL-encoding needed (only A-Z a-z 0-9 - _).
- No trailing characters and no line break in the email.
- Base URL = APP_BASE_URL http://localhost:8000; the page is served by that backend.
- The tenant resolves (single mode -> ctd-techs).
- Not a rolled-back transaction: the token commits before the email is sent.
- Not expired (5 days), and no timezone issue (expires_at stored in UTC).

**Cause:** the email's link belonged to a candidate that had been deleted. Deleting removes the token, and the page couldn't tell "deleted / cancelled" from "never existed", so it showed the same "not recognized" message for everything.

**Second, real risk found:** links are built from `http://localhost:8000`. They only open on this computer, so a candidate on another device couldn't open them at all.

## 3. Fixes
- **A clear page for every case** (negotiation._lookup_row + negotiation_router):
  - already picked -> "You've already picked a time: 05 Oct 2026, 10:00 AM IST…"
  - cancelled (recycle bin, Cancel, or the candidate deleted permanently) -> "This interview was cancelled…"
  - replaced by a newer email (retry / change interviewer / re-arranged) -> "There's a newer email…"
  - declined -> "noted"
  - expired -> **automatically re-arranged**: fresh times, new email. "This link has expired - we've sent you a new one" (interviewer), or "…we're arranging new times and will email you shortly" (candidate). At most once per 10 minutes, and only for the latest link of a shortlisted candidate with no interview.
  - otherwise "Link not recognized - please use the newest email from us".
- **Deleted candidates:** before the token rows go, a hash of each interview link is kept in `retired_links` (no personal data), so the page says "cancelled".
- **Why a link stopped working** is recorded on the token (`invalidated_reason`: cancelled / replaced / send_failed / expired).
- **Recruiter:** the profile card shows the link status: "Link opened 4:38 PM" / "Link not opened yet". A new state "Interview link expired" offers [Resend link], which arranges fresh times and sends new emails.
- **Public address:** links (interview pickers, confirmations, logo) are built from the company setting **Public address for links in emails** (`org.public_base_url`, Settings > Company > Profile), falling back to the server's APP_BASE_URL. Never hardcoded.
- **Health:** new "Email links" check, amber while the address is localhost ("they only open on this computer"), with a [Set public address] button.
- **Migration** c20a1b2c3d4e: negotiation_tokens.invalidated_reason + opened_at; table retired_links (RLS).

## 4. End-to-end proof
Setup: dev mailpit + a proof server on :8010 with DEV_MAIL_CAPTURE, so nothing reached a real mailbox. Two test candidates were used on the published "Junior AI Developer" job and deleted afterwards.

```
setup 16:37:35   "Proof - Link Test" + "Proof - Link Expiry" shortlisted -> scheduling started -> 2 interviewer emails (kg@ctdtechs.com) in mailpit
Link Test        interviewer link -> picked 2 -> candidate email (proof.test@example.com, link host 127.0.0.1:8010) -> picked 2
                 -> "Interview Confirmed … Kishore, 05 Oct 2026, 10:00 AM IST"
16:38:05         "Interview confirmed: Junior AI Developer" to BOTH proof.test@example.com and kg@ctdtechs.com, each with interview.ics
profile          state scheduled, Kishore, 2026-10-05 10:00 IST, meeting_link https://meet.jit.si/Interview-48t2UKyyDsyA, invite_sent_to [interviewer, candidate]
reopen cand.     "Already done - You've already picked a time: 05 Oct 2026, 10:00 AM IST. The calendar invite and meeting link are in your email."
made-up token    "Link not recognized - We can't find this link. Please use the newest email from us…"
Link Expiry      link opened 16:38:28 (opened_at recorded) -> expiry simulated -> profile state link_expired, opened_at set, [Resend link]
open it          "Link expired - new one sent" -> 16:38:49 new email with new times (6 Oct) ; the old link now "There's a newer email"
delete both      permanently (reference removed-6c201a86 / removed-7306cbaf) -> 4 retired link hashes
new link         "Interview cancelled - This interview was cancelled, so this link no longer works."   <- the reported case, now explained
```

**Screenshots:**
- `screens/link-1-interviewer-form.png`, `link-2-interviewer-done.png`, `link-3-candidate-form.png`, `link-4-candidate-confirmed.png`
- `screens/link-5-candidate-already-picked.png`, `link-6-not-recognized.png`, `link-7-expired-new-one-sent.png`, `link-8-cancelled-after-delete.png`, `link-9-old-expired-link-after-delete.png`
- `screens/link-10-confirmed-candidate-email.png`, `link-11-confirmed-interviewer-email.png` (mailpit)
- Signed-in profile card: pending login proof.

**Checks:** compileall; alembic upgrade (c20a1b2c3d4e); tsc; i18n 4026 keys, 0 missing; npm run build OK.

**Owner action:** set **Settings > Company > Profile > Public address for links in emails** to an address candidates can reach (e.g. your server's public URL). Until then every emailed link points to http://localhost:8000 and only works on this computer.
