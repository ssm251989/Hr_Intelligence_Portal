# Part 18 -- owner change list: fixes and proof

Each item: problem, change, how verified, screenshot. Proof calls run through the real app
(`backend/scripts/probe.py`, TestClient, signed-in user by role) or inside a rolled-back transaction.
Signed-in screenshots are marked **pending login proof** until a login is available.

## 18.1 Remove 2-step verification

**Problem:** people were asked about 2-step verification. It appeared in Settings > People & access and in Home/health warnings ("admins sign in without 2-step verification").

**Change:**
- New setting `iam.auth.two_step_available` (Settings > Advanced > All settings, group "Advanced"), **off**.
- While it is off:
  - sign-in never asks for a code or to enrol, even if "Require 2-step" was on (`mfa.is_mfa_required` returns false);
  - the 2-step warnings are not produced;
  - the 2-step settings page is hidden from the Settings menu (bootstrap sends `two_step: false`).
- The code is kept; switching the setting on brings everything back.

**Verified:**
```
GET /api/v1/setup/config-health  before: ADMIN_WITHOUT_2FA, USERS_WITHOUT_2FA, COPILOT_NO_KNOWLEDGE, UNROUTED_PURPOSE x2
                                 after : COPILOT_NO_KNOWLEDGE, UNROUTED_PURPOSE x2   (2-step warnings gone)
GET /api/me/bootstrap            -> "two_step": false  (Settings hides the 2-step page)
rolled back: mfa_required=on, feature off -> asked for code: False
             mfa_required=on, feature on  -> asked for code: True
```
(`UNROUTED_PURPOSE` is fixed in 18.2.) Setup checklist had no 2-step step. **Screenshot:** settings menu -- pending login proof.

## 18.2 One company email for everything

**Problem:** the company has one mailbox, but each purpose needed its own route. Helpdesk and candidate-application inbound mail showed as "not connected", so health warned about them.

**Change:**
- Every inbound purpose now falls back to `email.inbound.default`.
- `ConnectorRouter` gained a "company mailbox" fallback: an email purpose with no route of its own uses the connection already routed in the same direction (reading = IMAP, sending = SMTP).
- The health check and the Settings > Connections purpose list now ask the router itself (fallbacks included) instead of looking for a row per exact purpose.
- The Settings > Communication > Mailbox card now says in plain words that it is the one mailbox used for every module (en/hi/ta).
- Per-purpose email routing is no longer shown anywhere for normal users. The routing API is still there for advanced use.

**Verified:**
```
config-health: UNROUTED_PURPOSE for helpdesk email -> gone (only "e-sign" left, fixed in 18.3)
GET /api/v1/connectors/purposes: all 12 email.* purposes routed=True (before: helpdesk, candidate_applications inbound etc. False)
router (rolled back): email.inbound.helpdesk            -> imap dbc7bdb9 via email.inbound.negotiation_replies
                      email.inbound.candidate_applications -> imap dbc7bdb9
                      email.outbound.helpdesk / reports -> smtp 64664ee5 via email.outbound.default
tsc clean, i18n 0 missing
```
**Screenshot:** mailbox card -- pending login proof.

## 18.3 Health checks read the real status

**Problem:** DocuSign is connected, but Home said "Offer letters can't be e-signed yet - connect DocuSign". The check only looked for a company connection row. This app connects DocuSign per person (OAuth sign-in, `app/integrations/docusign.py`), and offers are sent through that person's account. Connections that had never been tested also counted as fine.

**Change:**
- E-sign counts as connected when a company e-sign connection is routed, or when the app has DocuSign keys and someone in the company has signed in to DocuSign.
- Every purpose check asks the router, including fallbacks (18.2).
- A connection is healthy only when it is active **and** its last test passed. A failing one shows its real error (for example "535 login failed"); a never-tested one shows "hasn't been tested yet".
- New `POST /api/v1/setup/config-health/recheck` really tests every connection. It saves the result and time; a failed test does not switch the connection off.
- The Home "Configuration health" card has a **Re-check now** button and shows when it last checked (en/hi/ta).

**Verified:**
```
before (Home):  UNROUTED_PURPOSE "Offer letters can't be e-signed yet - connect DocuSign"
after:          no e-sign issue (DocuSign signed in by a user); "Anthropic / Interview Tracker hasn't been tested yet"
POST recheck -> 200: tested anthropic True, excel_file True, imap True, smtp True -> only COPILOT_NO_KNOWLEDGE left
rolled back: smtp last test failed -> CONNECTION_FAILING "HR Mailbox (SMTP) isn't working" fix "535 login failed"
             no DocuSign sign-in  -> UNROUTED_PURPOSE e-sign warning comes back
```
**Screenshot:** Home health card -- pending login proof.

## 18.4 Module unlock passcode

**Problem / ask:** every main module must stay locked until an admin enters the module passcode. The passcode must never be in code or git.

**Change:**
- **Storage:** new table `module_access` holds the passcode only as a **bcrypt hash** (`$2b$12$…`, 60 characters), plus the unlocked-at/by, wrong-try count and wait-until for each module.
- **Setting the passcode:**
  - on the server, once: `python -m hrctl.modules set-passcode --tenant <slug>` (hidden prompt, typed twice; nothing ends up in shell history);
  - later, in Settings > Advanced > Modules > **Change passcode** (needs the current passcode; main admin only);
  - `python -m hrctl.modules status --tenant <slug>` shows which modules are locked.
- **What gets locked:**
  - Jobs, Candidates, Screening, Shortlisting, Interviews, Candidate emails, Salary, BGV, Offers, Reports, Settings, GenAI usage;
  - plus every other switched-on module (Onboarding, People, Performance, Helpdesk, Assets, Exits, Analytics, HR assistant).
- **Settings** (`modules.lock.*`): on/off; one passcode for all (default) or one per module; 5 wrong tries, then a 15-minute wait. All editable.
- **Enforcement:**
  - APIs of a locked module return **403** with `MODULE_LOCKED` and a plain message.
  - Always open: sign-in, the menu, the lock API and the candidate-facing public pages.
  - A few read lists that every page needs stay open (jobs list, applications list, one candidate), so one locked module never breaks another. Writes to them are locked.
- **In the app:**
  - A locked module shows a lock icon in the menu, and its pages show a friendly "… is locked" card. Admins can type the passcode right there; everyone else is told to ask an admin.
  - Settings > Advanced > Modules lists every module with Locked/Open, Unlock / Lock per module, Unlock all / Lock all, Change passcode, and the lock settings.
- **Audit:** every unlock, lock, wrong try, first set and change is written to the audit log.
- **Until a passcode exists, locking stays off.** Otherwise nobody could unlock anything. **I did not set the passcode**; the owner runs the command once.

**Verified** (one rolled-back transaction with a throwaway test passcode; the real company has 0 `module_access` rows afterwards):
```
no passcode yet            -> active false; GET /api/v1/ui/salary/queue 200
after set-passcode         -> active true, 20 modules locked
salary queue               -> 403 {"code":"MODULE_LOCKED","message":"This module is locked. An admin needs to enter the module passcode ..."}
GET /jobs (shared read)    -> 200;  POST /jobs -> 403
bootstrap                  -> nav items carry lock_key (/jobs -> jobs, /hr-inbox -> candidate_emails ...), module_locks.locked = 20 keys
wrong passcode             -> 400 "That passcode isn't right. 4 tries left."
unlock salary              -> 200; salary queue 200; BGV still 403
recruiter unlock           -> 403
5 wrong in a row           -> 4,3,2,1 tries left, then 429 "Too many wrong tries. Please wait 15 minutes"
right passcode during wait -> 429 (the wait is enforced)
after the wait, unlock all -> 200, locked = []
lock salary again          -> salary queue 403
change passcode            -> wrong current 400; right current 200; old passcode then 400, new 200
stored                     -> "$2b$12$..." length 60 (bcrypt), no plain text anywhere
audit                      -> module_passcode_set, _wrong, module_unlocked, module_locked, module_passcode_changed ...
public branding            -> 200 (never locked)
frontend                   -> tsc clean, i18n 0 missing (52 new keys en/hi/ta), npm run build OK
```
**Screenshot:** locked page card, Settings > Modules -- pending login proof. There is no passcode on the real company yet, so nothing shows as locked until the owner sets one.

## 18.5 Modules removed from the product menu

**Problem / ask:** switch off and hide People (employee records + directory), Org chart, Performance, Compensation, Succession and Helpdesk, keeping the code. "Choose what you use" must show only real, allowed modules, and switching must really update the menu.

**Change:**
- The default switched-on list no longer has `core_hr` (People, Directory, Org chart), `performance` (Performance, Compensation, Succession) or `helpdesk`.
- Data migration `a1c5e8f3d7b2` removed those three from every company's `platform.modules.enabled`. It is a settings change only, no records are touched, and it has a downgrade.
- **Setup "Choose what you use"** now comes from the server: the modules that exist, the licence allows, and `platform.modules.offered` lists (Pre-boarding & onboarding, Assets, Exits, Analytics & report builder, HR assistant). Saving changes only those, and the menu reloads.
- **Settings > Advanced > Modules** has a "Modules switched on" card with a switch for every allowed module (People, Performance, Helpdesk can come back here). Saving updates the menu straight away.
- With People off, the Setup "Import employees" step is not shown. Home hides the goals, tickets and assets boxes when their module is off.
- Their APIs return 404 (existing module gate).

**Verified:**
```
ctd-techs platform.modules.enabled: before [analytics, assets, copilot, core_hr, helpdesk, onboarding, performance, separation]
                                    after  [analytics, assets, copilot, onboarding, separation]
bootstrap nav: no /people, /org-chart, /performance, /compensation, /succession, /helpdesk
GET /api/v1/ui/people, /api/v1/performance/goals, /api/v1/service-desk/tickets -> 404
setup steps: company, entities_locations, branding, mailbox, modules, config_pack, invite_admins (no import_employees)
(rolled back) setup offers [onboarding, assets, separation, analytics, copilot]; setup tries core_hr -> 400
              Settings switch on helpdesk -> 200, nav gains /helpdesk, helpdesk API 200
              setup switches off assets   -> nav loses /assets, helpdesk kept
tsc clean, i18n 0 missing
```
**Screenshot:** menu, Settings > Modules -- pending login proof.

## 18.6 Colourful light and dark mode

**Problem:** dark mode looked dull (near-black green-grey everywhere); light mode was mostly one colour.

**Change** (`theme/tokens.ts`, `theme/createAppTheme.ts`, `ui-kit/StatTile.tsx`, `ui-kit/PageHeader.tsx`, `components/StatCard.tsx`):
- **Dark palette:**
  - deep navy ground `#0A1324`, navy cards `#111E36`;
  - bright accents: teal `#2DD4BF`, coral `#FF8474`, sun `#FFCB57`, sky `#6AADFF`, green `#4ADE80`, and a new **violet** `#B39DFF`;
  - cards get a faint light edge so they stand off the ground.
- **Light palette:** cooler, cleaner ground and a new violet. Coral and amber text are darkened so their chips are readable.
- **Colour everywhere:**
  - soft colour glows behind every page (teal top-left, violet top-right, sky bottom);
  - primary buttons have a gradient and a soft glow (stronger in dark mode);
  - every stat tile and dashboard card wears its own colour (tinted wash and a coloured top edge). Without a set tone, tiles pick a colour from their label, so a row is never all one colour;
  - page header icons sit on a module colour;
  - charts gained violet in their series; progress bars run teal → sky → violet.
- **Contrast checked:** new `node scripts/contrast-check.mjs` tests 16 text/background pairs per mode (WCAG 4.5:1 text, 3:1 chips/icons). All pass. Before the change, light mode had 2 failing pairs: coral chip 2.63, amber text 4.32.
- Company brand colours still override the defaults (the primary colour is lifted for dark mode).

**Verified:**
```
node scripts/contrast-check.mjs -> contrast: all pairs OK (light + dark)
tsc clean, npm run build OK
```
**Screenshots (public pages, both modes):** `login-light.png`, `login-dark.png`, `careers-light.png`, `careers-dark.png`, `candidate-status-light.png`, `candidate-status-dark.png`.
In-app pages in both modes -- pending login proof.

## 18.7 "Jobs need attention" scales to 100+ jobs

**Problem:** the Jobs page showed a long text block per job (counts, issues, four "things to try" lines). With 100 jobs that becomes a wall of text. The backend also ran several queries per job.

**Change:**
- **Backend `job_health`** rewritten with grouped queries, a fixed number no matter how many jobs. Each job gets:
  - a level: green; amber (one issue); red (two or more issues, 5+ candidates waiting, or no applicants for 21+ days);
  - issues with numbers (`no_applicants` + days quiet, `slow_stage` + count + worst days over, `low_scores`);
  - tip codes.
  - The response also has summary counts for the chips.
- **a) Summary chips** at the top: "2 need attention", "1 need action now", "2 no applicants 7 days", "1 candidates waiting too long". Clicking a chip filters the table below.
- **b) Job health column** in the Jobs table: green / amber / red chip with an icon. Hover shows the reasons and what to try.
- **c) Compact "Needs attention" table:** job, issue in one line, days, applicants, health, Open job. It has sorting (job, days, applicants, health), search (job, department, place), and paging at 10 / 25 / 50 / 100. The panel can be collapsed and is hidden when every job is fine.
- All wording is in en/hi/ta; the backend sends only numbers and codes.

**Verified:**
```
GET /api/v1/ui/jobs-health (real data) -> summary {jobs 4, need_attention 2, red 1, no_applicants 2, waiting_too_long 1}
  Automation Anywhere Architect: red   [no_applicants 33 days, slow_stage 1 candidate 31 days over]
  RPA Developer:                 amber [no_applicants 10 days]
  Demo - RPA Developer, Junior AI Developer: green
scale (rolled back, +150 live jobs): 154 jobs -> 40 ms, 5 SQL queries in total
tsc clean, i18n 0 missing (20 new keys en/hi/ta), npm run build OK
```
**Screenshot:** Jobs page chips + table + health column -- pending login proof.

## 18.8 Close a job

**Problem / ask:** "Close job" with a reason. Closing must put the job's resumes on hold automatically (not reject them), and reopening must restore them.

**Change:**
- **Where:** "Close job" in the job row menu and in the job details, for recruiters and admins. The dialog asks for a reason (position filled / hiring cancelled / on hold by the business / other) and an optional note.
- **`POST /api/v1/ui/jobs/{id}/close`** (`app/jobs/closing.py`):
  - the job becomes `closed` (with closed_at, reason and note) and leaves the careers site;
  - **every active application** moves to `on_hold` with `hold_reason = "job_closed"`, keeping its previous stage. Finished or rejected ones are untouched, and it is never a rejection;
  - queued emails and open interview-scheduling, confirmation and form links for those applications are cancelled;
  - the recruiters get an in-app notice (job owner, hiring manager, hiring team; the person closing if the job has none);
  - optional candidate email: setting `recruitment.jobs.close_email_candidates` (default off) or the tick in the dialog, using the editable template `recruitment.job_closed_candidate`;
  - everything is audited.
- **Reopen** (existing J5 dialog) now also returns exactly those applications to their earlier stage.
- The candidate list shows **"On hold - job closed"** for them.
- **New:** `app/platform/comms/defaults.py`. Automatic candidate emails get ready-made wording that becomes a published, editable template on first use. It never overwrites an existing template. This also fixes the 17.8 salary-form email, whose template had never existed.

**Verified** (rolled back, on "Demo - RPA Developer"):
```
before: [bgv_rejected], [hr_selected], [salary_approved]; on careers site: true
bad reason -> 400; interviewer -> 403
close (filled) -> 200 {on_hold: 2, cancelled: {queued_emails: 1}, recruiters_notified: [kg@ctdtechs.com]}
after:  [bgv_rejected untouched], [on_hold / previous hr_selected / job_closed], [on_hold / previous salary_approved / job_closed]
        careers site: false; queued email -> suppressed; in-app "Demo - RPA Developer was closed (filled). 2 candidate(s) are on hold."
close again -> 400 "This job is already closed."
reopen -> 200 {applications_restored: 2}; back to hr_selected + salary_approved; careers site: true
candidate email template created on first use -> published, "Update on your application for {{ job_title }}"
tsc clean, i18n 0 missing, npm run build OK
```
**Screenshot:** Close job dialog -- pending login proof.

## 18.9 LinkedIn / Naukri import: "Complete setup" instead of "Coming soon"

**Problem:** in Candidates > Import, LinkedIn, Naukri, Indeed, Monster and Shine said "Coming soon" with a technical note, and there was nothing to do.

**Change:**
- **Import wizard:** these sources now show a **"Complete setup"** chip. Choosing one explains what the board needs (for example LinkedIn: an employer account with Recruiter System Connect / Talent Solutions API access and a client ID and secret; Naukri: an RMS / Resdex account with an API key). It offers **Open job board settings** and **Upload resumes from <board>**.
- **New Settings > Integrations > Job boards** page, one card per board:
  - a status chip: Not set up / Saved - waiting for API access / Connected;
  - the connect form: masked fields, "e.g. from your account manager" placeholder, saved to the encrypted secret store;
  - Save and test, Test, Disconnect (with confirm), and the last-tested time;
  - "Bring candidates in today": upload the board's resumes (tagged with that board as the source), or forward the board's application emails to the company mailbox (its address is shown).
  - API: `GET /api/v1/ui/job-boards`, `POST /{code}/connect`, `POST /{code}/test`, `DELETE /{code}`. Admins change it; recruiters can view.
- `/candidates/upload` accepts the board sources, so imported people are counted under the right source.
- **Honest limit:** pulling candidates straight from a board needs that board's partner API. Those adapters are placeholders in the connector catalog, so a test says "Details saved … needs the board's partner API, which isn't switched on yet" instead of pretending to connect. Once an adapter exists, the same card turns **Connected** after a passing test.

**Verified** (rolled back):
```
GET job-boards: linkedin [client_id, client_secret], naukri [api_key], indeed [api_key], monster/shine [] -- all not_set_up; mailbox shown
connect naukri without key -> 400 "Please fill in: api_key"
connect naukri             -> saved + test {ok: false, error: API_NOT_AVAILABLE} -> state "saved"
recruiter connect -> 403, recruiter view -> 200
disconnect -> 204 -> not_set_up
tsc clean, i18n 0 missing (39 new keys en/hi/ta), npm run build OK
```
**Screenshot:** Import wizard "Complete setup", Job boards page -- pending login proof.

## 18.10 One filter system; scoring only in Settings

**Problem:** Candidates and Screening had filter panels but Shortlisting didn't; there were no notice-period or tag filters. The Screening list had its own threshold slider and the Screening dashboard its own threshold editor, so thresholds could be changed in several places.

**Change:**
- **One filter panel** (`CandidateFiltersPanel`) on **Candidates, Screening and Shortlisting**: job, stage, match score range, experience range, location, **notice period** (can join now / up to 15, 30, 60, 90 days), source, date added, **tags**.
- **Saved filters per user:** Candidates and Screening save them through the list toolbar's saved views. Shortlisting has a "Saved filters" menu in the panel (same per-user store: save, apply, delete your own).
- **Backend:** the shared filter function (`_filtered_candidate_applications_query`) gained `notice_max` and `tags` (any of them). They are passed through `/candidates/applications` (+ export), `/api/v1/ui/screening/list` and `/shortlisting/list` (+ export).
- **Tags:** new `candidates.tags` (migration `c9e4a2d8f6b1`, GIN index). Tags are edited on the candidate profile (type and Enter; stored lower-case, at most 20). `GET /api/v1/ui/candidates-tags` gives the most-used tags for the picker. List rows carry `tags` and `notice_period_days`.
- **Scoring only in Settings:**
  - the Screening list's threshold slider and the Screening dashboard's threshold panel are removed;
  - both pages show one read-only line, "The shortlist score is 22 … set in Settings > Hiring > Scoring rules - this page only filters", with an **Open scoring rules** button;
  - weights, thresholds and per-job overrides stay only in Settings > Hiring > Scoring rules (17.4-17.6).

**Verified** (rolled back):
```
PUT tags ["RPA", " Senior ", "rpa"] -> ["rpa", "senior"]; GET candidates-tags -> senior 1, rpa 1
/candidates/applications?tags=rpa            -> [Demo - Asha Verma]
/candidates/applications?notice_max=30       -> Asha (15 days), Nisha; Karan (90) left out
/api/v1/ui/screening/list?tags=senior        -> [Demo - Asha Verma]
/shortlisting/list?notice_max=100            -> [Demo - Karan Joshi]
rows carry tags ["rpa","senior"] + notice 15
tsc clean, i18n 0 missing (14 new keys), npm run build OK
```
**Screenshot:** the three list pages with the filter bar -- pending login proof.
