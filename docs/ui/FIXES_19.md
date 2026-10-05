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

# Offer -> welcome flow broken (bug 2026-10-04, candidate "Kishore Gunda", Junior AI Developer, joining Wed 14 Oct 2026)

## 1. The real records (ctd-techs)
- Candidate `Gunda Kishore` (gkishore1433@gmail.com). Application c7291dc9…, job "Junior AI Developer" ea576a6f (department AI, **no hiring manager set**).
- Offer 6c5feb90: `docusign_envelope_id null`, `signed false`, joining_date 2026-10-14, expiry 2026-10-11. There were no sent/viewed columns, so nothing could record them.
- Joining date: it **was** picked from HR's 3 dates.
  - Audit 16:38:57 `joining_dates_proposed ["2026-10-12","2026-10-14","2026-10-15"]`
  - Audit 16:39:12 `joining_date_chosen 2026-10-14` (actor: candidate)
- 16:39:13 `docusign_envelope_creation_failed`: "DocuSign token request failed: Client error '400 Bad Request' for url 'https://account-d.docusign.com/oauth/token'". DocuSign is not really connected; its login is rejected.
- 16:39:21 `offer_and_welcome_sent {"esign": false, "offer_emailed": true, "onboarding_case": "738b43dc…", "welcome_emailed": true}`.
- Emails sent:
  - 16:39:13 "Junior AI Developer: your offer letter"
  - 16:39:17 "Congratulations on your selection, Gunda!"
  - That is 4 seconds apart, both before any signature.
- Onboarding case 738b43dc: status `invited`, attributes `{}`.
- Configured onboarding forms, documents and policies: **none**. So the portal's only step was the built-in "Offer signed".
- Settings: `recruitment.contacts = {"default": []}`, `org.public_base_url` empty.
- **Rule that sent the welcome:** `app/recruitment/offer_welcome.after_joining_date_chosen` (Part 18.20). It ran right after the date was chosen and sent the offer and the welcome together, by design. There was no "wait for signature" step.

## 2. What was wrong
1. Offer and welcome were sent in one go when the joining date was chosen. Signing was never waited for.
2. When DocuSign failed, the offer email fell back to "Sign your offer letter (reply to the offer email)". There was no in-app signing page at all.
3. The portal's "Offer signed" card was not clickable; the code marked it read-only. With no checklist configured, it was the only step.
4. The email promised "fill in your joining details", but no such built-in step existed. It only appeared if HR had built a custom form.
5. Greeting used `full_name.split(" ")[0]`. For "Gunda Kishore" that is the surname.
6. The contacts block came from an empty setting, so only "reply to this email" was left. The job has no hiring manager.
7. The portal link was built from the server's FRONTEND_URL, which is localhost.

## 3. Fixes
- **Flow:**
  - The joining date is confirmed, then the **offer email** goes out with a **Review & sign** link (or a DocuSign envelope when DocuSign works).
  - The candidate signs.
  - Then the confetti page, the recruiter is told (in-app + email), and **then** the welcome email + welcome portal.
  - New setting `offers.welcome_with_offer` (default **off**) brings back the old "send both together" if wanted.
  - Signing by DocuSign or by HR marking it signed goes through the same follow-up, `esign.on_offer_signed` (once only).
- **In-app signing** (`app/offers/esign.py`, public `/offer/sign/{token}`):
  - The page shows the letter and a PDF download.
  - To sign: type full name + tick "I accept". This records name, time, IP and browser, saves a PDF stamped with the signature, and logs audit `offer_signed`.
  - Expired offers say so in plain words.
  - Migration d20b2c3d4e5f: offers.sign_token, sent_at, viewed_at, signed_at, signed_name, signed_ip, signed_user_agent, signed_pdf_path, sign_method.
  - The PDF is made after the signature is saved, so a PDF problem can never lose a signature. The browser proof caught exactly that (fpdf2 line-position bug, fixed).
- **Welcome portal** (`app/onboarding/welcome_steps.py` + `WelcomeBuiltinSteps.tsx`). The real built-in steps come first, then any configured forms, documents and policies:
  - **Offer signed:** "Review & sign" until signed; then a done tick and **View signed offer** (PDF).
  - **Joining details:**
    - Covers personal details, address, emergency contact, and bank/ID.
    - **Autosaved** as you type; "Send to HR" checks everything.
    - Checks the formats of PAN, IFSC, account number, PIN, phone and email; Aadhaar gets the Verhoeff check; date of birth must give an age of 16–80.
    - Account number, PAN and Aadhaar are stored **encrypted** and shown masked (XXXXXXXX9012).
    - On send, the pre-hire employee record gets the confirmed names and contact details.
  - **Documents:** the configured list (onboarding setting, else the hiring "required documents" list). Each item can be uploaded with the phone camera or as a file. Status shows uploaded / verified / please upload again / already received during hiring.
  - **Your first day:** date and start time, office address with an "Open in maps" link, who to meet, what to bring, and the agenda, then "Got it".
    - New settings: `onboarding.day_one.start_time`, `.meet`, `.what_to_bring`.
  - **People you can reach out to:** a card with name, role, email and phone. Empty lines are hidden.
  - Steps that need the signature say **"Unlocks after you sign your offer"**, and the server refuses them (409) until then.
  - Progress "x of N done" counts only real steps.
  - The HR Onboarding board readiness counts the same steps (`welcome_steps` in readiness).
- **Emails:**
  - Greeting: preferred name, else the first name the joiner typed, else the full name. Never the first word only. The same fix applies to the BGV and joining-date emails.
  - "People you can reach out to" lists the department's and the company's HR contacts (Settings > Hiring > Contacts) plus the job's hiring manager. Each person shows name, role, email and phone; a line is hidden if not set; nobody appears without an email or phone.
  - No "reply to sign" anywhere. Default wording is updated only where the company never edited it.
  - A missing salary now reads "as agreed with HR", never a blank amount.
- **Links:**
  - Sign links use `org.public_base_url` (else APP_BASE_URL).
  - Portal and joining-date links use the new `org.public_app_url` ("Public address of the web app", else FRONTEND_URL).
  - The Health "Email links" check is amber while either one is localhost.

## 4. End-to-end proof
Setup:
- Mailpit, a proof API on :8010 (DEV_MAIL_CAPTURE) and the web app on :5174. Nothing reached a real mailbox.
- Test candidate "Asha Verma" (proof.offer@example.com) on "Junior AI Developer", at BGV cleared.
- Test contacts were added to the setting for this run, then restored to `{"default": []}`.

```
20:21:46  HR proposes 14 / 16 / 17 Oct -> "background verification successful - choose your joining date"
20:22:05  candidate picks 16 Oct (joining_date_chosen)
20:22:09  docusign_envelope_creation_failed (same 400 as Kishore) -> in-app signing
20:22:09  "Junior AI Developer: your offer letter - please review and sign"   <- only email; welcome emails before signing: 0
          email text: "Review & sign it here: http://127.0.0.1:8010/offer/sign/..."  (no "reply")
20:25:43  sign page opened -> offers.viewed_at recorded
20:28:00  typed "Asha Verma" + ticked -> signed_at, signed_ip 127.0.0.1, sign_method in_app, stamped PDF (200 application/pdf)
          page: "Welcome aboard!" + confetti + [Open your welcome portal] + signed PDF link
20:28:01  recruiter told: in-app "Asha Verma signed the offer for Junior AI Developer - joining 16 Oct 2026" + email to kg@ctdtechs.com
20:28:02  "Welcome to CTD Techs, Asha Verma!" (after_signing: true); portal link http://127.0.0.1:5174/welcome/... (not localhost)
          People you can reach out to:
          - Arun Kumar (Head of AI) - arun.ai@example.com                 <- department contact, no phone -> phone hidden
          - Priya Raman (HR partner) - priya.hr@example.com - +91 98400 11111
          ("No Way", a contact with no email/phone, is not shown)
portal    1 of 4 done; the 4 steps are clickable
details   PAN "ABC123" -> highlighted at once by autosave; fixed -> "Saved" -> Send to HR -> 2 of 4
          reopened: account XXXXXXXX9012, PAN XXXXXX234F, Aadhaar XXXX XXXX 0124; DB stores "enc:..."
          greeting now "Welcome to the team, Asha!" (preferred name)
day one   Got it -> 3 of 4
documents Experience letters (required) + PAN card uploaded from file -> 4 of 4 done
HR board  readiness percent 100, welcome_steps {total 4, done 4}; case in_progress; application onboarding_started
```

**Screenshots:**
- `screens/fix-offer-email.png`, `fix-offer-sign-page.png`, `fix-offer-signed-confetti.png`
- `screens/fix-welcome-email.png`, `fix-welcome-portal-start.png`, `fix-welcome-details-check.png`, `fix-welcome-details-masked.png`
- `screens/fix-welcome-documents.png`, `fix-welcome-documents-uploaded.png`, `fix-welcome-day-one.png`, `fix-welcome-portal-after.png`, `fix-welcome-portal-phone.png`
- Signed-in HR Onboarding page: pending login proof. Readiness was checked in-process; numbers are above.

**Clean-up:**
- Normal removal correctly refuses a candidate with a signed offer.
- The test record's own rows were deleted directly by id in one transaction: candidate, application, offer, case, pre-hire employee, 2 uploads, 7 audit, 4 message and 1 token rows. Its files were deleted too.

**Checks:** compileall; alembic upgrade head (d20b2c3d4e5f); tsc; i18n 4089 keys, 0 missing; npm run build OK.

**Owner actions:**
1. Kishore's existing offer is still unsigned. His portal now shows "Sign your offer" with a working Review & sign page.
2. Set **Public address for links in emails** and **Public address of the web app** (Settings > Company). Until then links point to localhost.
3. DocuSign's login is rejected (400 from the token endpoint), so in-app signing is used. Reconnect DocuSign in Integrations if you want envelopes.
4. Add HR, department and manager contacts in **Settings > Hiring > Contacts**, and a hiring manager on the job. The email and portal list them automatically.
5. Optional: set the first-day start time, who to meet and what to bring in the onboarding settings.

# Welcome portal steps + resend / revised offer (bug + feature 2026-10-05, candidate "Kishore Gunda")

## 1. The real records (ctd-techs, before the fix)
- Candidate `Gunda Kishore`, offer 6c5feb90 (`signed false`, `sent_at null`), case 738b43dc (`invited`, created 2026-10-04 16:39, **before** the 21:20 fix commit).
- What the portal API returned for his link (`GET /api/v1/public/ui/onboarding/portal/<token>`):
```
first_name 'Gunda Kishore'   done 1   total 4
{'kind': 'offer',             'label': None, 'done': False, 'locked_reason': None}
{'kind': 'joining_details',   'label': None, 'done': False, 'locked_reason': 'Unlocks after you sign your offer.'}
{'kind': 'joining_documents', 'label': None, 'done': True,  'locked_reason': 'Unlocks after you sign your offer.'}   <- locked AND done
{'kind': 'day_one',           'label': None, 'done': False, 'locked_reason': 'Unlocks after you sign your offer.'}
```
- The page code before the fix (`WelcomePortalPage.tsx` at 87e701e~1), given that payload:
  - `const label = step.kind === "offer" ? t("welcome.step.offer") : step.label;` -> `null` -> **3 cards with no title**
  - `else note = step.done ? t("welcome.step.offer_done") : t("welcome.step.offer_todo");` -> every unknown kind gets the OFFER's text -> **"Waiting for your signature" x3, "Done" x1**
  - `StepDialog` had no branch for these kinds -> **empty dialog (icon + Close)**
- The current page code (dev server started 12:20 today) renders the same payload with titles. So the screen you saw came from a page loaded **before** the 2026-10-04 change, talking to the **updated** backend (uvicorn --reload).
- Name: the resume's first line is "Gunda Kishore" (the parser did **not** swap it). `onboarding/portal.py:99` split it into first_name "Gunda" / last_name "Kishore" on the pre-hire record. `greeting_name()` then fell back to the whole full name.
- Note: at 12:53:40 today kg@ctdtechs.com marked Kishore's offer signed by hand (`sign_method manual`), and at 12:53:57 completed onboarding. His welcome email went out then.

## 2. Causes
1. **Old page + new server (version skew).** The backend started sending new step kinds with `label: null` and left the titles to the page. A page that didn't know those kinds treated every one as "the offer step" and had no form for it. Nothing protected an older open page, and nothing caught an unknown step type.
2. **A locked step counted as done.** Kishore's documents were already received during hiring, so "Upload documents" was `done: true` while still locked. Result: "1 of 4 done" with the offer unsigned.
3. **Greeting** used the whole full name (the 10-04 rule), and the pre-hire record took the first word as the first name (it is his surname).

## 3. Fixes
- **Every step has its own state** (`app/onboarding/welcome_steps.py`): `locked | not_started | in_progress | done`.
  - A locked step is **never** done.
  - Offer = done only when the latest version is signed (DocuSign: after the envelope is completed).
  - The server also sends an English `label`, `description` and `status_text`, so no page can show an empty card again.
- **Cards** (`WelcomePortalPage.tsx`, `WelcomeBuiltinSteps.tsx`): title + one-line description + own status (Not started / In progress / Done / "Unlocks after you sign your offer"). Every card opens a working page:
  1. Sign your offer -> View offer (PDF) + Review & sign (DocuSign note when an envelope exists; "revised offer, version N" when N > 1)
  2. Your joining details -> the autosaved form
  3. Upload documents -> the configured list with camera upload
  4. Your first day -> time, address + map, who to meet, what to bring
- **Unknown step type:** a plain message for the joiner, and `POST /portal/<token>/problem` -> ERROR log + audit `portal_step_unrenderable` (once per joiner, step and day).
- **Old open page:** the portal answer carries `portal_schema` (2). A page built for an older schema reloads itself once.
- **Names** (`app/candidates/names.py`): first / last / preferred name on the candidate (migration e21a3b4c5d6f).
  - Order of trust: the joiner's own joining details, then what HR set on the profile, then the resume parser's new `given_name` / `family_name` (the prompt explains family-name-first names).
  - Without one of these, greetings use the full name. **Never a guess:** `gkishore@` and `rkumar@` look alike but mean opposite things. An email-based guess was tried during this fix and removed (see 4.).
  - The profile shows "We call them ..." with a pencil (first, last, preferred, Swap). Saving updates the pre-hire employee record too.
  - Eight more emails that used "first word of the full name" now use the same rule.
- **i18n:** new portal and HR keys in en / hi / ta; `i18n:check` 4188 keys, 0 missing.

### Resend / revised offer (new, `app/offers/revisions.py`)
- `offers` stays the LATEST version, so every existing reader keeps working.
- New table `offer_versions` keeps each version: who sent it, reason, note, what changed, approval, and (once replaced) its own sign link, view / signature, PDF and DocuSign envelope.
- **[Resend for signature]:** same offer, reminder email with the sign link; "Last sent <time>, sent <n> times"; 15-minute cooldown (HTTP 429 `RESEND_COOLDOWN`).
- **[Send revised offer]:** opens with the current values (CTC, breakup lines when configured, joining date, designation, location, terms). It needs a reason: salary / joining date / designation / other + note.
  - CTC is re-checked against the job's band and the department budget.
  - Above the limit -> "Needs approval". Approvers get an in-app notice; an admin or salary approver approves (it is sent then) or declines. A blocked budget refuses outright.
  - The old version -> "Replaced". Its DocuSign envelope is voided (new `void_envelope`). Its link shows "This offer was replaced by a newer version" + [See your latest offer] and can't be signed. Its PDF stays downloadable.
  - New letter + new link, unsigned. A signed v1 still needs v2 signed; the application goes back to Offer sent.
  - Email "Revised offer from CTD Techs" with a "What changed" list.
  - The welcome portal's step 1 always shows the latest version.
  - When the revised version is signed, its joining date goes to the hiring record, the onboarding case (+ plan), the portal and later emails. A "Thank you for signing your revised offer" email confirms the date.
- **Offer history** on the profile (new Offer section) and on each Offers-page card: version, date, sent by, reason, what changed, status (Sent / Viewed / Signed / Replaced / Declined / Needs approval / Not approved), PDF per version.
- **Audit:** `offer_resent`, `offer_revised`, `offer_revision_needs_approval`, `offer_revision_approved` / `_rejected`, `offer_viewed`, `offer_signed` (with version), `offer_signed_followup` (once per version), `candidate_contact_info_updated` (old -> new names).

## 4. End-to-end proof (mailpit)
Setup:
- mailpit (127.0.0.1:1025 / :8025, fresh mailbox), a proof API on :8010 (`DEV_MAIL_CAPTURE`, in-app jobs off) and the web app on :5174. Your :8000 / :5173 were not touched.
- Test candidate "Ravi Teja Proof" (proof.revised2@example.com) on Junior AI Developer (band 2.0-4.0 LPA) at BGV cleared, 3.0 LPA approved.
- A temporary admin "proof.hr@example.com" for the HR screens.
```
13:28:20  HR proposes 20 / 22 / 23 Oct -> candidate picks 20 Oct
13:28:24  "Junior AI Developer: your offer letter - please review and sign"  (v1, in-app link; DocuSign 400 as before)
          greeting "Hi Ravi Teja Proof" (no first name known yet -> full name, never a guess)
          HR sets first "Ravi Teja" / last "Proof" (profile pencil); HR starts onboarding
portal    "Welcome to the team, Ravi Teja!"  0 of 4 done
          Sign your offer: Not started | Joining details / Upload documents / Your first day: Unlocks after you sign your offer
          each card opens: offer -> View offer (PDF) + Review & sign + "sign by 12 Oct"; the 3 locked -> description + "unlocks after ..."
          same in Hindi and Tamil
14:12:31  HR [Resend for signature] -> "Reminder: your offer ... is waiting for your signature" (same link) -> "sent 2 times"
          second resend at once -> 429 "It was sent less than 15 minutes ago. You can resend in 15 min."
14:12:38  HR [Send revised offer]: CTC 300000 -> 350000, joining 20 -> 22 Oct, reason Salary changed + note
          -> "Revised offer from CTD Techs":  What changed: - CTC: 3.0 LPA → 3.5 LPA  - Joining date: 20 Oct 2026 → 22 Oct 2026
          v1 link -> "This offer was replaced by a newer version" + [See your latest offer] (= the v2 link); POST sign on v1 refused
          portal step 1 -> "This is your revised offer (version 2)", its Review & sign = the v2 link
14:13:52  HR tries 4.5 LPA -> v3 "Needs approval: 12.5% above the band maximum (₹4,00,000)"; no candidate email; approvers told in-app
14:13:55  approver [Don't approve] -> v3 "Not approved"; v2 stays current
14:14:23  candidate signs v2 (typed name + tick, IP 127.0.0.1) -> "Welcome aboard!"
          case joining 2026-10-20 -> 2026-10-22, application joining chosen -> 2026-10-22, approved salary 350000
          emails: "Thank you for signing your revised offer, Ravi Teja" (joining Thursday, 22 October 2026) + "Welcome to CTD Techs, Ravi Teja!"
          recruiter: "Ravi Teja Proof signed the offer ... joining 22 Oct 2026" (captured in mailpit)
portal    1 of 4 done | Sign your offer: Done ✓ | the other three: Not started, each opens its form (details / 7 documents / day one 09:30 + map)
history   v3 Not approved | v2 Signed (PDF stamped "Signed electronically ...", CTC 3,50,000) | v1 Replaced (PDF, CTC 3,00,000)
```
Found by this proof and fixed:
- An email-based name guess (first try) greeted the first test candidate "Hi Teja Proof". Removed; names come only from trusted sources (above).
  - That interim rule was live on your :8000 when you marked Kishore signed at 12:53, so his real welcome email ("Welcome to CTD Techs, Kishore!") came from it. It happened to be right for him; with the final rule his greeting stays "Gunda Kishore" until his names are set (owner action 1).
- The revised email's text part showed `-&gt;` and `Review &amp; sign`, because the template renderer HTML-escapes variables. Arrows are now "→", and the fixed wording is template text. The first wording is retired, so stored copies update.
- "Work location: Chennai" was appended after the sign-off even when unchanged. It is now added only when HR changes it, and before the sign-off.
- Two onboarding tests already failed on HEAD (the 10-04 built-in steps count toward readiness). Their assertions now match that.
- The run was redone on a fresh candidate after these fixes; the timeline above is that second run.

**Screenshots** (`screens/`):
- HR: fix20-profile-offer-v1, fix20-names-dialog, fix20-names-saved, fix20-hr-resent, fix20-revise-prefilled, fix20-revise-filled, fix20-revise-sent, fix20-revise-over-band, fix20-revision-pending-approval, fix20-profile-history-final
- Portal: fix20-portal-before-sign, fix20-portal-step-offer, fix20-portal-step-locked, fix20-portal-hi, fix20-portal-ta, fix20-portal-phone, fix20-portal-step-offer-v2, fix20-portal-after-sign, fix20-portal-details-form, fix20-portal-documents, fix20-portal-day-one
- Signing: fix20-old-link-replaced, fix20-sign-v2-page, fix20-sign-v2-done
- Mailpit: fix20-mail-offer-v1, fix20-mail-reminder, fix20-mail-revised, fix20-mail-thanks-revised, fix20-mail-welcome

**Clean-up:**
- Both test candidates deleted by id in one transaction: 2 candidates, 2 applications, 2 offers, 5 offer versions, 2 cases, 2 pre-hire employees, 2 budget rows, 2 link tokens, 25 audit rows, 13 messages (incl. the test in-app notices to kg@ctdtechs.com), the temporary admin + its role.
- The signed PDF file was removed.
- Kishore's records were not changed.

**Checks:** alembic upgrade head (e21a3b4c5d6f); compileall; pytest test_offers + test_onboarding + new test_offer_revisions: 78 passed; tsc; i18n 4188 keys, 0 missing; npm run build OK.

**Owner actions:**
1. Kishore: open his profile -> "We call them" pencil -> **Swap first and last** -> Save (first "Kishore", last "Gunda"). His portal and emails then say "Kishore". His resume was read before the parser returned given / family names.
2. Anyone with a welcome page left open from before 2026-10-04 needs one reload. Newer pages reload themselves when the server is newer.
3. Above-band revised offers notify the salary approvers (Settings > Hiring > Salary approvers). Today that falls back to the admins, i.e. kg@ctdtechs.com.

# Post-joining exits and absconding (bug + logic change 2026-10-05: "Withdraw offer" on a JOINED person)

## 1. What "Withdraw offer" did to the record (Kishore Gunda, ctd-techs)
```
12:53:40  kg@ctdtechs.com  offer marked signed by hand (sign_method manual)
12:53:57  system           application onboarding_started -> onboarding_completed   <- Offers page "Complete onboarding" (shown everywhere as "Joined"),
                                                                                       9 days BEFORE his joining date (14 Oct)
14:35:41  gkishore1433@... inbound email: "Confirms joining the company on 14 October 2026."
14:45:25  kg@ctdtechs.com  portal_token_rotated (new welcome link)
14:46:20  kg@ctdtechs.com  case history "revoked", reason "Accepted another offer"    <- Onboarding board "Withdraw offer"
```
State after the click (half joined, half withdrawn):
| record | state |
|---|---|
| onboarding case 738b43dc | `revoked` |
| application c7291dc9 | `onboarding_completed` ("Joined") |
| offer 6c5feb90 | signed, onboarding_status `completed` |
| pre-hire employee EMP-00013 | `inactive` (never converted) |
| budget | 2,80,000 still `committed` |
| emails | none sent for the withdraw |
| audit log | **no entry** (only the case's own history line) |

**Cause:** there were two separate "joined" markers.
- The Offers page "Complete onboarding" set the *application* to Joined with no joining-date check and no employee conversion.
- The Onboarding board's own checks looked only at the *case* (`_close` refused only `case.status == "joined"`), which was still open.
- The menu showed Withdraw / Didn't join to everyone, whatever the stage.

**Repair** (audit `record_repaired`, before/after on the case and the application):
- He had not joined (14 Oct is in the future) and had confirmed joining by email, so he was restored to signed, waiting to join: case `in_progress`, application `onboarding_started`, offer `in_progress`, pre-hire record `pre_hire`, budget left committed. No email was sent.
- Then, at **16:00:22, kg@ctdtechs.com recorded "Candidate declined" (Accepted another offer)** with the new flow. That is now his consistent state: case `declined`, application `offer_declined`, budget released, his job's opening free again + a to-do.

## 2. Actions by stage (one rule set: `app/onboarding/joiner_stage.py`)
| stage | actions shown and accepted |
|---|---|
| before joining date | Withdraw offer (company decision, reason, email to candidate) - Candidate declined (reason list) |
| on / after joining date, not joined | Mark as joined - Did not join (reason, optional "contacted on") - (withdraw / declined still allowed: they haven't joined) |
| joined | Not reporting - Absconded - Resigned - Terminated (last working day, reason, notes, rehire eligible; confirmation step) |
| closed | nothing |
- The board shows exactly `allowed_actions`, and every endpoint calls `require()` first: 409 `ACTION_NOT_ALLOWED` with a plain message, e.g. "Chetan Absconds has already joined, so the offer can't be withdrawn or declined. Use Absconded, Resigned or Terminated instead."
- **Mark as joined** is the only way to "joined" (employee record made live + application Joined). The Offers page "Complete onboarding" now goes through it too, so it can't run before the joining date.
- New statuses: application `offer_withdrawn / offer_declined / no_show / left_after_joining`, case `declined / exited` (migration f22b4c5d6e7a). Shown with labels everywhere (status chip, Kanban "not moving", stepper, jobs stage "Dropped out / left", pipeline report).

## 3. After joining: exits (`app/onboarding/joiner_actions.py`, on top of the Exits module)
- **Absconded / Resigned / Terminated** each create a real Exit case (separations: absconding / resignation / termination):
  - the LWD is approved at once (notice shortfall waived: the date is a fact, not a request);
  - clearance checklist + **asset recovery** for anything still issued;
  - rehire eligible (default No for absconded / terminated, Yes for resigned; editable).
- The record is kept: the employee goes `on_notice` until the Exit case completes, and the case history keeps every step.
- **Access:** the welcome link stops; the app login is switched off at once for absconding (and when the LWD has passed), otherwise on the LWD (hourly job).
- **Notify:** in-app + email to the job owner / hiring manager and the employee's manager / HRBP.
- **Not reporting -> absconding** (Settings > Onboarding & employees > Leaving soon after joining):
  - Reminder after 2 days, show-cause / return-to-work notice after 5, final notice after 10 (days from the last day they came in; all editable; can be switched off).
  - Each is sent once by the hourly scheduler job `joiner_exits`, and HR is told in-app; after the final notice HR confirms Absconded.
  - "Back at work (stop notices)" ends the flow, with a note.

## 4. After any exit / no-show / withdraw / decline
- Application status updated -> the job's opening counts again; a job that had **closed itself as filled re-opens** (audit `job_reopened_position_open_again`).
- Recruiter to-do on Home ("Your to-do"): **"Position open again - N past candidates match (job)"** (talent-pool re-match), linking to the job's talent pool. One to-do per job; it closes when a pool candidate is added.
- Department budget commitment **released**.
- Queued emails for the person suppressed, open links (action tokens) invalidated, welcome link revoked, offer link says "This offer is no longer open".
- Audit on the case AND the application, so the candidate timeline tells the story (labels in en / hi / ta).

## 5. Report: Reports > "Dropouts & early exits"
- Counts: offer dropouts (withdrawn + declined), no-shows, early leavers (resigned / terminated within 90 days), absconding.
- By job, department, recruiter and reason; period 30 / 90 / 365 days / all. Endpoint `GET /api/v1/onboarding/dropout-report`.

## 6. Proof (mailpit, proof API :8010 with DEV_MAIL_CAPTURE, web :5174)
Test joiners on two test jobs, temporary admin proof.hr@example.com:
```
(a) Anil Withdrawn, joins in 10 days
    menu: Change date | New link | Candidate declined | Withdraw offer        (no "didn't join", Mark joined disabled)
    Withdraw, reason "Position put on hold by the business"
      -> case revoked, application offer_withdrawn, budget released, audit offer_withdrawn
      -> mailpit "About your offer for Proof Exit Role A at CTD Techs" (no internal reason in it)
      -> his offer link: "This offer is no longer open"; welcome link: "This link doesn't work any more."
      -> Home > Your to-do: "Position open again - 0 past ca... / Anil Withdrawn - offer withdrawn"
(b) Bina NoShow, joins today
    menu adds "Mark as didn't join" -> reason "Could not be reached", contacted on 5 Oct, notes
      -> case no_show, application no_show, outcome stored with reason + contacted_on
(c) Chetan Absconds, joined 20 Sep (Mark joined in the UI)
    after joining the menu is only: Not reporting | Absconded | Resigned | Terminated
    API: POST /revoke, /declined, /no-show -> 409 ACTION_NOT_ALLOWED "...has already joined..."
    Not reporting, last day 4 Oct -> scheduler run at day 1/2/3/5/7/10/11 -> sent 0/1/0/1/0/1/0:
      "We missed you at work - please get in touch" (day 2)
      "Absence from work since 04 October 2026 - please explain and return to work" (day 5)
      "Final notice: absence from work since 04 October 2026" (day 10)
    Absconded -> Exit case absconding, LWD 4 Oct, rehire No, 3 notices on it, 6 clearance items incl.
      "Recover Proof test laptop (PROOF-LAPTOP-01)", login switched off, budget released
      (this confirmation was clicked by kg@ctdtechs.com in the live app at 16:00:59; the confirm dialog was re-proved on Esha)
    Esha Absconds: Not reporting with a last day 11 days back -> all 3 notices at once -> Absconded with the
      confirmation step ("...mark them as NOT re-hirable") -> Exit case absconding, LWD 24 Sep
(d) Divya Resigns, joined 20 Sep, job A set to 1 opening -> job auto-closed as filled (16:06:27)
    Resigned, reason "Better offer elsewhere", confirm ("mark them as re-hirable")
      -> Exit case resignation, rehire Yes; job A re-opened (16:07:22); to-do; HR/manager email
Report: offer dropouts 2, no-shows 1, early leavers 1, absconding 2; by job A 3 / B 2 / Junior AI Developer 1 (Kishore)
```
**Found and fixed during the proof:**
- A raw `{name}` in the withdraw email note.
- A second exit on the same job added a duplicate to-do; it now updates the one open to-do.
- The new statuses fell into the Kanban "New" column and stepper step 1; they now map to "Not moving" / the offer or joined step.

**Screenshots** (`screens/`):
- Before joining: fix21-a-card-before, fix21-a-menu-before-joining, fix21-a-withdraw-dialog, fix21-a-mail-withdrawn, fix21-a-offer-link-closed, fix21-a-recruiter-todo
- Joining day: fix21-b-menu-joining-day, fix21-b-no-show-dialog
- After joining: fix21-recent-joiners, fix21-c-menu-after-joining, fix21-c-not-reporting-dialog, fix21-c-not-reporting-started
- Notices: fix21-c-mail-reminder, fix21-c-mail-show-cause, fix21-c-mail-final, fix21-c-notices-sent, fix21-c-menu-not-reporting
- Exits: fix21-c-absconded-dialog, fix21-c-absconded-confirm, fix21-d-resigned-dialog, fix21-d-resigned-confirm, fix21-board-after
- Reports, timeline, settings: fix21-report, fix21-timeline-esha, fix21-settings-leavers

**Clean-up:**
- All test records deleted by id in one transaction: 5 candidates, 5 applications, 5 offers, 5 cases, 5 employees, 3 employment records, 3 exit cases + 16 clearance items, the test laptop + its allocation, 4 budget rows, 5 to-dos, 2 test jobs, 35 audit rows, 19 messages, the temporary admin + 3 employee logins created by Mark joined.
- Kishore's records were not touched after the repair, except by kg@ctdtechs.com's own decline.

**Checks:** alembic upgrade head (f22b4c5d6e7a); pytest test_offers, test_onboarding, test_offer_revisions, test_joiner_exits (7 new), test_jobs, test_jobs_service: 163 passed. test_service_desk has 8 failures that are identical on HEAD (not touched). tsc; i18n 4281 keys, 0 missing; npm run build OK.

**Owner actions:**
1. Kishore is now "declined" (your 16:00 action). If that was a test click, tell me and I'll restore him to "signed, joining 14 Oct". If it was real, send him a note yourself: "declined" sends no email by design.
2. Check the notice wording in Settings > Message templates (onboarding.not_reporting_*) with your HR/legal practice.
3. Add salary / HR contacts (Settings > Hiring > Contacts) so the notices name a person, not "your HR team".


# Configuration health links + Policies & handbook (bug 2026-10-05: "Upload policies" opened an unrelated page)

## 1. What the button did (ctd-techs, before the fix)
- Home > Configuration health showed `COPILOT_NO_KNOWLEDGE`: "The HR assistant has no policy documents yet…", button **Upload policies**.
- `backend/app/experience/config_health.py` gave it `fix_path = "/settings/integrations/ai"`. That is Settings > Integrations > **AI provider & HR assistant**: provider, API key, models, prices. It has no upload control.
- The intended page never existed:
  - The backend had `POST /api/v1/intelligence/copilot/knowledge`, which only took pasted text (title + body). Nothing in the frontend called it, and there was no file upload.
  - The Helpdesk knowledge base (where KB articles also feed the assistant) is hidden: the `helpdesk` module is off for ctd-techs. The enabled modules are analytics, assets, copilot, home, onboarding, recruitment, separation and settings.
- A second cause made any wrong link look "unrelated": `SettingsCategoryPage` silently redirected a link to a hidden or unknown page to the **first page of that category**, with no message.

## 2. Fix
- **One page: Settings > Company > Policies & handbook** (`/settings/company/policies`; aliases `/settings#policies`, `#handbook`, `#knowledge`).
  - Upload: drag & drop or choose several PDF/.docx files (20 MB each), with a **Download a sample handbook** link. Each file gets a title, category (Leave, Code of conduct, Benefits, IT, Other), version and effective date before upload.
  - List: status **Processing**, **Ready for HR assistant**, or **Failed** + a plain reason ("No readable text was found. It may be a scanned copy…", "password-protected", "couldn't be opened"). Each row also shows file, version, effective date and who uploaded it.
  - Row actions:
    - **Preview**: the PDF itself, plus the exact text the assistant reads, by heading.
    - **Download**.
    - **New version**: the old version keeps answering until the new one is Ready, then it becomes history.
    - **Edit details**.
    - **Try again** (for Failed rows).
    - **Delete**, with a confirm: removes the file and its searchable text. The row is kept so earlier answers still name their source.
  - Works with Helpdesk off. The API is `/api/v1/ui/policies` (not under the copilot prefix, which switches off with the assistant). When the assistant is off, the page says so and still stores files.
  - Files go to the storage connection (`storage.documents`) under `policies/<company id>/`. With no storage connection they go to the server disk under `uploads/policies/<company id>/`.
  - Reading happens in the background after the upload response. Rows stuck in Processing after a restart are picked up again.
  - Audit: policy.uploaded / new_version / ready / failed / details_changed / deleted.
- The health button now opens exactly this page. The warning is shown **only when the HR assistant is on** (copilot module + `copilot.chat` AI feature), and it clears once **one** policy is Ready.
- **"Ignore this"** on every health item (admin only):
  - The key is stored in `platform.health.ignored`.
  - Ignored items are listed under Settings > Data & privacy > System health > "Ignored checks" with **Show again**.
  - Audited as health.ignored / health.unignored.
- A settings link to a hidden page now shows: "*X* isn't available right now. It belongs to a part of the app that is switched off for your company, or you don't have access to it."
- **Found while proving it:**
  1. **The HR assistant could not answer anyone.** `gateway.complete` never sent `max_tokens`, which the AI provider requires, so every governed AI call failed with `TypeError` (`ai_decision_log` status error). The owner's own question at 22:28:05 failed this way. The same path also serves agents, HR-inbox triage, review summaries and exit summaries. Fixed with the same cap the direct path uses (`ai.max_tokens_per_request`, default 4096). Regression test added.
  2. The assistant's round button stayed on top of its open panel and covered the **Send** button. It is now hidden while the panel is open.
  3. System health "storage" linked to Integrations > File storage. That page only shows usage, and its data endpoint `GET /api/v1/settings/storage` doesn't exist (405). The link now opens Integrations > Connections, where a storage connection is added or repaired. The usage page itself is still unbuilt (not part of this fix).

## 3. Every health / setup item: where its button goes
| Item (code) | Button goes to | Page exists & visible? | Fixes the item? | Fixed |
|---|---|---|---|---|
| HR assistant has no policies (COPILOT_NO_KNOWLEDGE) | was `/settings/integrations/ai` (AI provider page) | yes | **no**: no upload there | **now `/settings/company/policies`**; only when assistant on; clears on 1 Ready |
| Emails can't be sent / replies not read (UNROUTED_PURPOSE email.*) | `/settings/communication/mailboxes` | yes (admin or HR-mailbox right) | yes | correct |
| AI not connected (UNROUTED_PURPOSE llm.*) | `/settings/integrations/ai` | yes | yes (provider + key) | correct |
| Offer letters can't be e-signed (UNROUTED_PURPOSE esign.*) | `/settings/integrations/esign` | yes | yes | correct |
| Any other unconnected service (UNROUTED_PURPOSE fallback) | was `/settings/integrations` (redirected to first page) | yes | partly | **now `/settings/integrations/connections`** |
| Email not ready, notification can't send (UNPUBLISHED_TEMPLATE) | `/settings/communication/templates` | yes | yes | correct |
| Approval step with nobody to approve (WORKFLOW_NO_APPROVERS) | `/settings/automation/approvals` | yes | yes | correct |
| Admins / people without 2-step (ADMIN_WITHOUT_2FA, USERS_WITHOUT_2FA) | `/settings/people/two-step` | only when 2-step is switched on, and the item only appears then too | yes | correct (now shows "isn't available" instead of jumping if ever reached while off) |
| Connection token expiring (OAUTH_EXPIRING) | was `/settings/integrations` (redirected) | yes | partly | **now `/settings/integrations/connections`** |
| Connection failing / not tested (CONNECTION_FAILING, CONNECTION_NOT_TESTED) | `/settings/integrations/connections` | yes | yes | correct |
| Setup: Company details | `/setup?step=company` | yes | yes | correct |
| Setup: Company & offices | `/setup?step=entities_locations` | yes | yes | correct |
| Setup: Logo & colours | `/setup?step=branding` | yes | yes | correct |
| Setup: Connect your mailbox | `/setup?step=mailbox` | yes | yes | correct |
| Setup: Import employees | `/setup?step=import_employees` | step exists only when People (core_hr) is on, and so does the item | yes | correct (off for ctd-techs, so neither shows) |
| Setup: Choose what you use | `/setup?step=modules` | yes | yes | correct |
| System health: company links | `/settings/company/profile` | yes | yes | correct |
| System health: mailbox | `/settings/communication/mailboxes` | yes | yes | correct |
| System health: AI | `/settings/integrations/ai` | yes | yes | correct |
| System health: storage | was `/settings/integrations/storage` (usage page, data endpoint missing) | yes | **no** | **now `/settings/integrations/connections`** |

Each link was opened by Playwright as an admin on the live app (`fix22-link-01..18`); the landed URL and page title were recorded. A made-up link (`/settings/integrations/old-ai-page`) shows the new "isn't available" notice (`fix22-link-18`).

## 4. Proof (live app :5173 / :8000, temporary admin, removed afterwards)
- `fix22-01-home-health`: the item with **Upload policies** and **Ignore this**.
- `fix22-02-upload-policies-opens`: the button lands on Settings > Company > **Policies & handbook**.
- While I worked, **kg@ctdtechs.com uploaded the sample handbook themselves** (22:27:55, Ready at 22:27:56, 6 passages, audit policy.uploaded / policy.ready). That cleared the warning for real. Their question to the assistant at 22:28:05 failed with the max_tokens bug above.
- My run:
  - `fix22-05` empty page
  - `fix22-06` queue: title "Employee handbook", version 2026.1, effective 1 Oct
  - `fix22-07` **Ready for HR assistant**
  - `fix22-08` preview of what the assistant reads
  - `fix22-09` home: the Configuration health card is gone
- `fix22-10`: asked "How many days of annual leave do I get, and can I carry them forward?". The answer was "You get 18 days of annual leave per calendar year, credited at 1.5 days per month [1][2]. You may carry forward up to 6 unused annual leave days…". **Sources:** [1] Sample employee handbook · Leave policy, [2] Employee handbook · Leave policy.
- `fix22-11/12`: Delete with confirm, then my copy is gone and the owner's handbook stays.
- "Ignore this" / "Show again" are covered by `test_ignore_health_item_and_undo`. I did not create a fake problem in the live company to click it once the owner's upload had cleared the only item.
- **Clean-up:** the temporary admin and its role, its 2 assistant conversations, 4 AI log rows (including one probe call) and their usage rows, my proof policy (row, file, audit rows). Nothing ignored was left behind.

**Checks:**
- alembic upgrade head (a23c5d6e7f8b).
- New tests: `tests/test_policies_health.py` (6) and `test_llm_gateway_routing::test_complete_always_sends_max_tokens`, all passing.
- test_experience / test_intelligence: 5 failures, identical on HEAD (not touched).
- i18n 4331 keys, 0 missing; `npm run build` OK.
- vitest: 3 failures (theme mock, UploadCandidateDialog), identical on HEAD.

**Owner actions:**
1. The handbook you uploaded is the **sample**: 18 days leave, Rs 5,00,000 insurance, and so on. The assistant now answers from it. Replace it with your real handbook (**New version** on its row), or delete it.
2. Optional: connect a storage service (Integrations > Connections) so policy files live there instead of on the server disk.
