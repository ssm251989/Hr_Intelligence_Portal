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
