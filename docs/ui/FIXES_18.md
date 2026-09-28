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

## 18.11 All-candidates tables (no "choose a job first")

**Problem:** BGV and Offers only worked after picking one job, so with many jobs you couldn't see who was waiting where.

**Change:**
- **New API** `GET /api/v1/ui/stage-table/{salary|bgv|offers}` (+ `/export` CSV):
  - every candidate at that stage across all jobs;
  - filters: search, job, department, status; sorting: name / job / status / days in stage;
  - paging up to **500 rows** a page, and counts per status;
  - stage figures per row: documents checked (BGV), offer signed and joining date (Offers), expected/approved salary (Salary).
  - It sits behind each stage's view permission and is covered by the 18.4 module lock.
- **`StageTable` component** at the top of the **BGV** and **Offers** pages:
  - search, job and department pickers, status chips with counts, sortable columns;
  - paging at 25 / 50 / 100 / 250 / 500;
  - row checkboxes with "Export selected" and "Export all (n)";
  - bulk **Request BGV** for everyone selected whose salary is approved;
  - clicking a row opens that candidate's existing actions below (loads the job and scrolls to the card).
- **Screening and Shortlisting** were already one table across jobs (job column and filter, paging, sort, bulk, export). They got the shared filter bar in 18.10.
- **Salary** gets its full table + side panel in 18.14. The same endpoint (`stage=salary`) is ready for it.

**Verified** (rolled back, +600 candidates across 20 jobs and 3 departments):
```
/stage-table/bgv?page_size=500 -> total 602, 500 rows, counts {salary_approved 121, bgv_requested 120, bgv_pending 120, bgv_cleared 120, bgv_rejected 121}, ~557 ms
page 2 -> 102 rows
department=AI & status=bgv_pending, sort name asc -> 30, [Scale Person 007, 027, 047]
default sort = waiting longest first (29 days)
/export?department=Finance -> text/csv, 180 rows + header
real data: bgv 2, salary 1, offers 0
tsc clean, i18n 0 missing (33 new keys), npm run build OK
```
**Screenshot:** BGV and Offers tables -- pending login proof.

## 18.12 Salary form sent automatically

**Problem:** the salary form (17.8) went out when a candidate was shortlisted, with one reminder at 24 h. Its email template also had never been created, so the email fell back to "share this link".

**Change:**
- **When** (Settings > Hiring > Salary):
  - `recruitment.salary.form_trigger` = **interview_cleared** (default) / shortlisted / manual;
  - `recruitment.salary.form_after_round` = 0 (the final decision) or N (from interview round N; the round is the interview's position for that candidate).
  - Recording "selected" on an interview (`PATCH /interviews/{id}/feedback`) now sends the branded form once. It is not sent again if already answered.
- **Reminders:** `recruitment.salary.reminder_hours` = [24, 48] by default, any list of up to 5. The hourly job sends each reminder once while the form is unanswered and stops as soon as it is answered.
- **Form fields:** current CTC, expected CTC, notice period, relocation, earliest joining (as before), plus:
  - **offers in hand** (and the best offer), setting `ask_offers`, on by default;
  - optional **payslip upload** (PDF/PNG/JPG, 5 MB), setting `ask_payslip`, off by default. Files are kept under `uploads/salary-payslips` and deleted with the candidate (17.15).
- **Email wording:** the email uses the default template (`app/platform/comms/defaults.py`). It is created as a published, editable template on first use, which fixes the 17.8 gap.

**Verified** (rolled back; sending replaced by a recorder so nothing was emailed):
```
defaults: trigger interview_cleared, after_round 0, reminders [24, 48], ask_offers true, ask_payslip false
after_round = 2, round 1 cleared -> nothing sent
after_round = 0, decision "selected" -> 1 email recruitment.salary_details_request
template created on first use -> published "{{ job_title }}: your salary and joining details"
reminders: at 10h 0 | at 25h 1 | again 0 | at 49h 1 | after both 0
public form -> ask_offers true, ask_payslip true; payslip PDF -> uploaded (1); .exe -> 400
submit with offers_in_hand 1, best offer 10,00,000 -> saved on the candidate
answered -> no more reminders; the test payslip file was deleted afterwards
tsc clean, i18n 0 missing, npm run build OK
```
**Screenshot:** the salary form with the new fields -- pending (needs an unanswered demo link).

## 18.13 Salary auto-decision

**Problem:** a salary was approved automatically whenever it was inside the band. There was no hike rule and no budget rule, and a person had nothing to decide with (approve / counter / reject).

**Change** (`app/recruitment/salary_auto.py`, `app/recruitment/budgets.py`):
- **Auto-approve only when ALL pass** (Settings > Hiring > Salary):
  - hike over current CTC ≤ **X%** (`recruitment.salary.auto_approve_hike_pct`, default **20**, editable);
  - expected CTC within the job's band;
  - the department budget has enough left (no budget set = not checked).
  - Auto-approved at what the candidate asked; the amount is **reserved** against the department budget.
- **Otherwise "needs approval"**, and the reasons are stored for the table:
  - `hike` (e.g. "Hike 35% > 20% limit");
  - `above_band` ("Above company range - check"; far above = "flagged");
  - `budget_short` ("Department budget short by 4 L");
  - `no_current` (current CTC unknown);
  - `no_band`.
- **HR decision** `POST /api/v1/ui/salary/applications/{id}/decide` (permission `recruitment.salary.edit`):
  - **approve** (at an amount or what they asked). This reserves budget, and is refused when the budget is set to "block" and is short;
  - **counter-offer** an amount. The candidate gets the editable `recruitment.salary_counter_offer` email;
  - **reject** with a required reason. This releases any reserved budget.
- **Budget money flow** (tables `department_budgets`, `budget_commitments`, migration `d4f8b2e6a1c3`): *reserved* on approval → *committed* when the offer is signed → *released* when the candidate is rejected at salary or BGV, or removed. The financial year follows `org.fiscal_year_start_month` (default April). The settings page and finance dashboard come in 18.15.

**Verified** (rolled back; test job band 5-12 L, "Demo - Budget Dept" budget 50 L, FY 2026-27; email recorded, not sent):
```
A  8 L -> 9.5 L (hike 18.8%, in band)   -> salary_approved automatically; reserved 9.5 L (40.5 L left)
B  8 L -> 12 L  (hike 50%)              -> needs approval [hike]; HR approve at 10 L -> approved, reserved 19.5 L in total
C 11 L -> 13 L  (above 12 L band)       -> flagged [above_band]; HR counter 12 L -> counter-offer email sent
D  ?   -> 9 L   (no current CTC)        -> needs approval [no_current]; reject without reason 400, with reason -> salary_rejected
E  9 L -> 10 L, budget cut to 25 L (5.5 L left) -> needs approval [budget_short, 4.5 L]; approve with "block" -> 400
    "The Demo - Budget Dept budget for 2026-27 is short by 450,000; raise the budget ..."
release A (removed) -> reserved 19.5 L -> 10 L
```
**Screenshot:** part of the 18.14 salary table.

## 18.14 Salary page = table + bulk

**Problem:** the Salary page was a long stack of cards. With 100-500 candidates you had to scroll through each one.

**Change:**
- **One table** (`StageTable`, stage `salary`) of everyone at the salary stage across all jobs:
  - columns: name, job, department, status, **current CTC**, **expected CTC**, **hike %** (green, or red when over the limit), **band** min-max, **budget left after** this hire (red when negative), and a **salary status chip** (Waiting for form / Auto-approved / Needs approval / Counter-offer sent / Approved / Rejected) with red reason chips ("Hike 35% > 20% limit", "Above company range by 8% - check", "Department budget short by 4.5 L") while a decision is pending;
  - days waiting;
  - rows that need a decision are tinted red.
- **Filters and actions:** search, job, department and status chips with counts; sort by hike % (and name, job, status, days); paging up to 500; select + **bulk approve**; export all or selected.
- **Row click → side panel:** the figures, why it needs a decision, the **history** (checked, form sent, reminders, answered, auto-decided, approved / countered / rejected), **Approve / Counter-offer / Reject (reason)**, and "Send the salary form" for people still waiting.
- Backend: salary rows carry current CTC, hike % (computed when an older check lacks it), band, budget-after, reasons, counter amount, open form and a plain status; `sort=hike` added.
- The **Finance** tab next to Candidates is 18.15.

**Verified** (rolled back, the 18.13 test candidates, `sort=hike&dir=desc`):
```
Bala   50.0%  approved        (HR approved at 10 L)     budget after 28.5 L
Anil   18.8%  auto_approved                              40.5 L
Chitra 18.2%  countered       [above_band]               27.5 L
Esha   11.1%  needs_approval  [budget_short]             -4.5 L  (red)
Devi   —      rejected        [no_current]
history (Bala): salary_checked, salary_auto_decided, salary_approve
tsc clean, i18n 0 missing (49 new keys), npm run build OK
```
**Screenshot:** Salary table + side panel -- pending login proof.

## 18.15 Department hiring budget + finance dashboard

**Ask:** each department gets a hiring amount per year, and every hire reduces it (budget 50 L, hire at 10 L → 40 L left). Configurable in Settings, with a finance view.

**Change:**
- **Settings > Hiring > Department budgets** (`BudgetsSettingsPage`): one row per department (taken from the jobs, and more can be added) for the chosen financial year, with:
  - the **yearly budget** (lakh shown as you type) and an optional **Q1-Q4 split** (must not add up to more than the year);
  - **alert at %** (default 80);
  - **when a hire goes over**: *needs approval* or *block the approval*;
  - used so far, and Save / Clear. Saving is audited (before and after).
  - The financial year follows `org.fiscal_year_start_month` (default April → "2026-27").
- **Money tracking** (from 18.13): *reserved* when a salary is approved (auto or HR) → *committed* when the offer is signed → *released* when the candidate is rejected at salary or BGV, or removed.
- **Salary > Finance tab** (`FinanceDashboard`):
  - totals as coloured tiles: allocated, reserved, committed, remaining;
  - per-department **coloured bars** (committed coral, reserved amber, remaining green) with "10 L of 25 L used · 15 L left", and a ring when near the alert;
  - **trend by month** (stacked bars) and **top roles by cost**;
  - **alerts** (near the alert % / over budget);
  - **Export to Excel** (sheets: budgets, top roles, by month) and an "Edit budgets" link.
- API `GET/PUT/DELETE /api/v1/ui/budgets`, `/dashboard`, `/export` (.xlsx). Viewing needs salary view; editing needs settings configure. Both are covered by the Salary module lock.

**Verified** (rolled back; continues the 18.13 test data):
```
PUT quarters adding up to more than the year -> 400
PUT Demo - Budget Dept 2026-27: 25 L, Q1-Q4 10/10/5/0 L, alert 60%, block -> saved
offer signed for Bala -> 10 L moves reserved -> committed
dashboard: allocated 25 L, reserved 0, committed 10 L, remaining 15 L, used 40%, 1 hire; no alert (40% < 60%)
top roles: Demo - Budget Test Engineer 10 L; trend 2026-09 committed 10 L
export: .xlsx with sheets [Budgets 2026-27, Top roles, By month]
recruiter PUT -> 403
tsc clean, i18n 0 missing (32 new keys), npm run build OK
```
**Screenshot:** Finance tab + Department budgets page -- pending login proof.

## 18.16 Documents form (automatic after salary approval)

**Ask:** as soon as the salary is approved (automatically or by HR), email the candidate a "Documents upload" form. The list of documents must be configurable.

**Change:**
- **Settings > Hiring > Required documents** (`recruitment.documents.required`). Each document has a label, required/optional, allowed file types (PDF / JPG / PNG / DOCX), max MB, and optionally **only for some job types**. It starts with: PAN, Aadhaar, education certificates, experience letters (optional), last 3 payslips, relieving letter (optional), photo. `auto_send` is on by default, and reminders run at **24 h and 72 h** (`reminder_hours`, hourly job).
- **Automatic:** every place a salary becomes approved (auto rule, HR decide, legacy approve and confirm) calls `after_salary_approved`. That sends the branded **`recruitment.documents_request`** email (editable default wording, with the list) with a 21-day link.
- **Candidate page `/documents/:token`:** one row per document (required/optional, types, size) with Upload / Add another, green when received and red with HR's note when asked again. "Send to HR" is enabled only when every required document is in, and then tells the recruiters in-app.
- **Storage:** new table `candidate_documents` (migration `e7a3c9f1b5d2`); files under `uploads/joining-docs/<company>/`, deleted with the candidate (17.15).

**Verified** (rolled back; emails recorded, not sent; test files deleted afterwards):
```
salary auto-approved (9 L -> 10 L, in band) -> status salary_approved + email recruitment.documents_request
  "- PAN card - Aadhaar card - Education certificates - Passport-size photo"
public form lists pan, aadhaar, education, photo (all required); submit before all are in -> 400
uploads -> 200; photo as .exe -> 400; submit when complete -> ok (recruiters told in-app)
tsc clean, i18n 0 missing (29 new keys), npm run build OK
```
**Screenshot:** candidate documents page -- pending (needs a live demo link).

## 18.17 Documents review (agent highlights, HR approves)

**Ask:** when files arrive, the agent checks each one and highlights green / amber / red with the reason. HR approves all or per document, or asks for specific documents again. HR approval moves the candidate to BGV.

**Change:**
- **Agent check on every upload** (`joining_docs.check_document`):
  - rule checks: readable (scans/photos without text → amber "check by eye"); looks like the right document (PAN pattern / "Income Tax", Aadhaar number, degree words, payslip words …); the candidate's name is on it; expiry dates in the past; the photo must be an image;
  - **AI check** (Claude, the existing document validator, new AI feature switch `recruitment.document_check`) for PAN, Aadhaar, education and experience, adding "problem" / "not sure" with its issues;
  - cross-document check: the same name, and the same date of birth on PAN and Aadhaar.
  - The agent never approves; it only colours and explains.
- **HR review panel** on the **BGV page**:
  - rows still at "salary approved" show a *Joining documents* column ("4 files", "1 problem", "1 to check"), and clicking one opens the review drawer;
  - each document shows its files with a green/amber/red chip, the reasons and a link to open the file;
  - buttons: **Approve** one, **Approve all and start BGV**, tick documents + note → **Ask the candidate again** (email `recruitment.documents_reupload` with the list and note; the page shows the note in red), and resend the link.
- **All required approved → BGV starts automatically** (`bgv_requested`). The approved PAN, Aadhaar, degree and experience files are copied into BGV, so BGV starts with them.
- API `/api/v1/ui/documents/{id}` (+ `/approve`, `/reupload`, `/send-form`, `/file/{doc}`). Viewing needs `recruitment.bgv.view`; decisions need `recruitment.bgv.edit`. Covered by the BGV module lock.

**Verified** (same rolled-back run as 18.16; the AI check really ran):
```
PAN (Income Tax, ABCDE1234F, Ravi Kumar)          -> green
"Aadhaar" that is really a payslip                -> red   [wrong_type, ai_problem]
degree certificate in someone else's name         -> amber [name_missing, ai_check]
photo PNG -> green;  reds / ambers = 1 / 1
ask again for Aadhaar + note -> email documents_reupload "- Aadhaar card: This was a payslip - please upload your Aadhaar card."
  candidate page shows aadhaar not received + the note; new Aadhaar uploaded
approve PAN only -> not moved yet; approve all -> moved_to_bgv true, status bgv_requested
BGV documents created: aadhaar, degree, pan
interviewer approve -> 403; all test files deleted
tsc clean, i18n 0 missing (35 new keys), npm run build OK
```
**Screenshot:** BGV table joining-documents column + review drawer -- pending login proof.

## 18.18 BGV decision by HR (no automatic "failed")

**Problem:** BGV could only be "cleared" when every document was marked valid, or "rejected". There was no "send the form again", no reason, and no message to the candidate.

**Change** (`app/recruitment/bgv_decision.py`, `POST /api/v1/ui/bgv/{id}/decide`, `GET …/failed-preview`, `BgvDecisionBox`):
- HR chooses **Passed / Resend form / Failed** on each BGV card.
  - **Passed** → `bgv_cleared`. If not every document is marked valid, HR is warned but may still pass: it is their decision and it is recorded. This then starts the joining-date step (18.19).
  - **Resend form** → HR ticks exactly what is needed (PAN / Aadhaar / education / experience) and adds a note. The candidate gets the upload link with that list and note (`recruitment.documents_reupload`), and the status stays in BGV.
  - **Failed** → a **reason is required**. **Preview the email** shows the polite "background verification update" message with the reason; HR can edit it before sending (template `recruitment.bgv_unsuccessful`, editable). The status becomes `bgv_rejected` and the reserved budget is released.
- **The system never marks BGV failed by itself.** Document checks only colour and explain; the only other place that sets "rejected" is HR's own legacy clear endpoint. Every decision is audited with reason, note and documents.

**Verified** (rolled back; emails recorded, not sent):
```
passed with no valid documents -> bgv_cleared (HR decision)
resend without choosing -> 400; resend degree + note -> bgv_pending, requested [education],
  email documents_reupload "- Education certificates: The degree scan is cut off - please send all pages."
failed without reason -> 400
preview -> subject "Demo - RPA Developer: background verification update", message with the reason
failed with HR-edited message -> bgv_rejected, email recruitment.bgv_unsuccessful sent
deciding again -> 400 "This candidate is not waiting for a BGV decision."
tsc clean, i18n 0 missing (23 new keys), npm run build OK
```
**Screenshot:** BGV decision dialogs -- pending login proof.

## 18.19 Joining date (3 options)

**Ask:** after BGV passes, HR picks 3 tentative joining dates. The candidate is emailed "Background verification successful" with the dates and chooses one with one click. Remind after 48 h; HR can propose new dates; the chosen date is saved and shown to HR.

**Change** (`app/recruitment/joining_dates.py`, `/api/v1/ui/joining/*`, `/api/v1/public/joining/{token}`):
- **BGV passed (18.18)** → the recruiters get an in-app nudge: "BGV passed for … - pick 3 joining dates."
- **Offers page:** a "BGV passed" row without a chosen date shows **Pick 3 dates** (or "Dates sent"), and clicking it opens the **Joining date** drawer. HR picks 3 future dates (+ optional note) and presses **Email the 3 dates**. Validation: exactly 3 different future dates.
- **Candidate email:** `recruitment.joining_dates` ("background verification successful - choose your joining date"), with the dates written out and a link to **`/joining/:token`**. That page has three big buttons, and one click saves the choice.
- **Reminder** after `recruitment.joining.reminder_hours` (default [48]) via an hourly job. **Propose new dates** replaces the old link, which then stops working. The earlier proposals are kept in history.
- **Saved:** the chosen date is stored on the application and shown in the drawer and in the Offers table's Joining date column. Choosing starts 18.20 (offer + welcome).

**Verified** (rolled back; emails recorded, not sent):
```
BGV passed -> bgv_cleared + in-app "BGV passed for Demo - Meera Nair (Demo - RPA Developer) - pick 3 joining dates."
2 dates -> 400; a date today -> "The dates must be in the future."
propose 3 -> email recruitment.joining_dates "- Monday, 12 October 2026 - Monday, 19 October 2026 - Monday, 26 October 2026"
new dates -> old link 404; candidate sees the new 3 dates
reminder at 49h -> 1 sent, then 0
choose a date not offered -> 400; choose 2026-10-20 -> saved; choose again -> 409
HR sees chosen 2026-10-20; Offers table row shows it
tsc clean, i18n 0 missing (17 new keys), npm run build OK
```
**Screenshot:** joining date page (public) -- pending (needs a live link); drawer -- pending login proof.

## 18.20 Offer letter + welcome (automatic after the date is confirmed)

**Ask:** when the candidate confirms a date, the agent sends the offer letter (template + salary + joining date, e-sign through the connected DocuSign) and a happy "Congratulations on your selection" welcome email. The welcome has the onboarding steps and the contacts (HR, department head, management) from Settings. The candidate then moves to Onboarding.

**Change** (`app/recruitment/offer_welcome.py`, called when the candidate chooses the date in 18.19):
- **Offer letter:** the company's own offer template (Settings > Offers, latest version, else the built-in wording) filled with the name, job, **approved salary** (Indian grouping, e.g. 12,00,000), **chosen joining date**, reporting manager and expiry (the Offers setting, default 7 days). The Offer row stores the letter, joining date and expiry; the status becomes `offer_sent`.
- **E-sign:** when someone in the company has connected DocuSign (the job owner or hiring manager first), a DocuSign envelope goes to the candidate. Otherwise the letter is emailed (`recruitment.offer_letter_auto`, editable) and the candidate replies to accept.
- **Welcome email** `recruitment.welcome_selected` (editable): congratulations, the joining day, **next steps** (sign the offer, fill in the welcome portal (link), join on the date) and **people to contact**. Contacts come from the department's own list first, then the company default.
- **Settings > Hiring > Contacts for new joiners** (`recruitment.contacts`): the company default plus one list per department, each person with name, role, email, phone.
- **Onboarding:** when the Onboarding module is on, a pre-joining portal case is created (status `invited`, joining date set). Its welcome-portal link is in the email.

**Verified** (rolled back; emails recorded, not sent; the DocuSign call replaced by a stand-in so no real envelope was created):
```
candidate chooses 2026-10-19 -> status offer_sent
offer: joining 2026-10-19, expiry +7 days, letter contains "12,00,000" and "19 October 2026"
DocuSign connected (kg@ctdtechs.com) -> envelope ENV-TEST-123 for the letter "Dear Demo - Kavya Rao, We are delighted to offer you the role of ..."
email: recruitment.welcome_selected
  steps: "1. Sign your offer letter (you will get a DocuSign email) 2. Fill in your joining details in the welcome portal: …/welcome/<token> 3. Join us on Monday, 19 October 2026"
  contacts: "- Dept Head (Head of Engineering): head@example.com - HR Desk (HR): hr@example.com +91 90000 00000"
onboarding case -> invited, joining 2026-10-19
without DocuSign -> emails [recruitment.offer_letter_auto, recruitment.welcome_selected], step "Sign your offer letter (reply to the offer email)"
tsc clean, i18n 0 missing (15 new keys), npm run build OK
```
The whole post-interview flow (18.12 → 18.20) now runs by itself: interview cleared → salary form → auto/HR salary decision (+ budget) → documents form → agent check + HR approval → BGV (HR decides) → 3 joining dates → offer + welcome → onboarding.

**Screenshot:** Contacts settings page -- pending login proof.
