# PART 20 - employees, self-service, exits: proof

Spec: `docs/PART20_EMPLOYEES_AND_SELF_SERVICE.txt` (owner, 2026-10-06). Items 20.0-A, 20.0-B and 20.0-C were first built on 2026-10-05 as owner fixes (commits `a3b92ce`, `90eae0b`, `3613c9c`; full proof with screenshots in `FIXES_19.md`). This file quotes the cause of each bug, lists what PART 20 added on top, and links the proof.

---

## 20.0-A Post-joining actions + absconding

**Real cause** (quoted from the DB and audit log of the test person, 2026-10-05):
- There were two separate "joined" markers:
  - The Offers page "Complete onboarding" set the application to `onboarding_completed` (Joined) **before** the joining date, without creating the employee.
  - The Onboarding board looked only at the case (`status = in_progress`) and offered "Withdraw offer" / "Didn't join" to everyone.
- Result:
  - case `revoked`, application still `onboarding_completed`, offer `completed`, employee `inactive`
  - budget still committed
  - no email to the candidate
  - no audit entry for the withdraw
- Repair: the record was put back to "signed, waiting to join" (audit `record_repaired`). On 5 Oct 16:00 the owner then recorded "Candidate declined". The owner later asked for this person to be deleted permanently, which was done. The record now in the app with the same name was created again by the owner on 5 Oct 22:40 and is the owner's own.

**What exists (all checked against the spec):**
| Spec point | Where | State |
|---|---|---|
| Actions by stage, backend refuses invalid ones (409, plain message), UI shows only valid ones | `app/onboarding/joiner_stage.py`, endpoints in `onboarding/api_router.py` | done |
| Before joining: Withdraw (reason, email to candidate) / Candidate declined (reason list) | `joiner_actions.withdraw_offer`, `candidate_declined` | done |
| On/after joining date: Mark as joined / No-show | `mark_joined` (the only way to Joined), `no_show` | done |
| After joined: no withdraw; exits Absconded / Resigned / Terminated | `record_exit` -> Exit case; **from the Employee list and the employee's own login in 20.1 / 20.3** | done in 20.3 |
| Absconding: Not reporting -> reminder 2 d, return-to-work 5 d, final 10 d (Settings > Onboarding & employees > Leaving soon after joining) -> HR confirms; stop if they return; rehire = No (editable); access off; assets to clearance; manager + HR told | `start_not_reporting`, hourly job `joiner_exits` | done |
| After any exit: opening back + "Position open again - N past candidates match" to-do, budget released, pending emails/links cancelled, audit, candidate timeline | `joiner_actions._after_close` | done |
| Reports by job, department, recruiter, reason (offer dropouts, no-shows, early leavers < 90 days, absconding) | Reports > "Dropouts & early exits" (`dropout_report`) | done |

**Proof:** `FIXES_19.md` "Post-joining exits and absconding":
- Withdraw refused after joining in both UI and API (409 "already joined").
- No-show.
- All three absconding emails in mailpit.
- Resigned.
- The report.

Screenshots `screens/fix21-*`. The 20.6 run below repeats the exit from the Employee list.

---

## 20.0-B Configuration health links + policies upload

**Real cause** (quoted, 2026-10-05):
- `config_health.py` gave the item `COPILOT_NO_KNOWLEDGE` the link `fix_path = "/settings/integrations/ai"`. That is the AI provider page (provider, key, models) and it has no upload.
- No policy upload page existed: the backend only took pasted text, and the Helpdesk knowledge base is hidden because the `helpdesk` module is off for CTD Techs.
- Separately, `SettingsCategoryPage` silently redirected any link to a hidden page to the first page of that category, which is why links looked "unrelated".
- Found while proving it: every HR-assistant answer failed. `gateway.complete` never sent `max_tokens`, and the provider rejected the call with `TypeError: Missing required arguments … 'max_tokens'` (`ai_decision_log` status `error`).

**What exists (all checked against the spec):**
- Settings > Company > **Policies & handbook**. It works with Helpdesk hidden and stores files via the storage connection. It has:
  - multi-file PDF/DOCX upload with a sample file
  - title, category, version and effective date
  - status Processing / Ready for HR assistant / Failed + reason
  - new version, delete with confirm, preview
- The health button opens exactly that page. The warning shows only while the HR assistant is on and clears once one policy is Ready.
- **Ignore this** on every health item (admin only), undone in Settings > Data & privacy > System health > Ignored checks.
- Hidden-page links now say "isn't available right now" instead of jumping.

### Every health / setup item: where its button goes
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

**Proof:**
- `FIXES_19.md` "Configuration health links + Policies & handbook", screenshots `screens/fix22-*`.
- Every link was opened by Playwright as an admin.
- The sample handbook went to Ready and the warning disappeared.
- The HR assistant answered "18 days … carry forward up to 6" and cited "Employee handbook · Leave policy" as the source.

---

## 20.0-C Joining details fields: all optional, configurable

**Real cause** (quoted, 2026-10-05):
- `welcome_steps.FIELDS` hardcoded `required=True` on 15 of 19 fields, so submit returned "Aadhaar number is needed." and blocked "Send to HR".
- The portal printed `fl.required ? "Needed" : "Optional"` under every required field, filled or not. That's why Name on bank account, account number, IFSC and PAN said "Needed" while filled.

**What exists:**
- Settings > Onboarding & employees > **Joining details form** (one versioned setting `onboarding.joining_form`, history + revert). Every field is listed by section with:
  - Required / Optional / Hidden
  - help text in en/hi/ta
  - format check on/off
- **Default: every field optional.**
- The same control covers the welcome-portal **Upload documents** list.
- Portal: `*` and "Needed" only on an empty required field; format check only when something is typed ("PAN looks like ABCDE1234F …"); drafts autosave; a gentle note when optional fields are empty; editable until HR locks.
- Backend validation reads the same settings.
- HR joiner drawer **Joining details** tab: empty fields (not errors), **Remind candidate**, Lock / Unlock.
- Bank/ID stay masked (last 4); the reveal is audited on the employee record.

**Added in PART 20:** the hiring **salary & joining details form** is on the same settings page (card "Hiring: salary & joining details form").
- Notice period, Willing to relocate, Earliest joining date, Other offers in hand and Latest payslip can each be Required / Optional / Hidden.
- Current and expected CTC are locked to Required, because the salary check is calculated from them.
- Defaults keep today's behaviour: notice period required; relocate and joining date optional; offers and payslip follow the older on/off switches (`recruitment.salary.ask_offers` / `ask_payslip`).
- The public form (`/salary-details/:token`) shows, hides and requires fields from it.
- `POST /api/v1/public/salary-details/{token}` checks Required ones ("Please fill in: Notice period.") and drops Hidden ones.
- `salary_auto.missing_fields` only counts a missing notice period while it is Required, so an optional notice period no longer makes the app ask again.
- The hiring **documents form** already had Required/Optional per document (Settings > Hiring > Required documents; removing a document = hidden). No change needed.

**Proof:**
- `FIXES_19.md` "Configurable joining details fields", screenshots `screens/fix23-01..09`:
  - an almost-empty form submits
  - Aadhaar switched to Required blocks only while empty
  - a wrong PAN shows the plain message
  - a Hidden field disappears
  - history + revert work
- The salary-form card is in the 20.6 screenshots.

---

## 20.0-D Asset type dropdown not working

**Investigation (2026-10-06, CTD Techs):**
1. *Does the list load?* `GET /api/v1/ui/servicedesk/categories?kind=asset` read `master_values` with `type_code='asset_category'`. The DB had **0 rows** for it:
   ```
   select type_code, count(*) from master_values group by type_code
   -> blood_group 8, document_type 5, education_level 5, notice_period 5, relationship 4, source_of_hire 8
      (no asset_category, no exit_reason, no ticket_category)
   ```
   So the API answered `[]`, and the dropdown opened an empty menu.
2. *Why empty?* `hrctl/seed_masters.py` seeds only those 6 lists and **never seeded `asset_category`, `exit_reason` or `ticket_category`**. The only asset type that ever existed was the demo data's "Demo - Laptops" (`hrctl/demo_data.py` `DEMO_CATEGORIES`), which went with the demo clean-up. The data reset never touches `master_values` (it is in its `NEVER` list), so nothing was "lost": the lists were simply never filled.
3. *Menu behind the dialog?* No. No component sets `disablePortal`, and no theme override changes `MuiMenu` / `MuiPopover` / `MuiDialog` z-index. MUI's menu portal opens above the dialog (screenshot in 20.6).
4. *Second bug in the same dialog:* `NewAssetDialog` picked the default type only at the moment the dialog opened (`categories[0]?.code ?? ""`). If the list arrived a moment later the field stayed empty, and **Save stayed disabled** (`canSubmit` needs a category).

**Fix:**
- **Defaults for a list that has never had a value**, the first time it is read (`ensure_defaults` in `ui_servicedesk_router.py`, audited `default_values_added`). Seeded for CTD Techs now:
  - asset types: Laptop, Desktop, Monitor, Mobile phone, SIM card, ID card, Access card, Headset, Keyboard/Mouse, Other
  - 10 exit reasons
  - 5 helpdesk topics
- Inside the dropdown: **"+ Add asset type"** (inline name + Add; the new type is selected straight away). When the list is empty: "No asset types yet - add one below." The default type is now picked when the list arrives.
- **Settings > Helpdesk & assets > Asset categories** and **> Exit reasons**: add, rename, switch off. Never delete, because assets and exits keep pointing at the item. New endpoints: `POST /categories`, `PATCH /categories/{kind}/{code}`, `GET ?include_inactive=true`. Permission: assets / separation edit, or settings admin.

**Every dropdown inside a dialog/drawer that gets its options from the server** (fixed lists such as status or work mode can't be empty):
| Dialog | Dropdown | Options from | Was | Now |
|---|---|---|---|---|
| Assets > Add asset | Asset type | `asset_category` list | **empty (0)** | 10 types + "Add asset type" |
| Assets > filter / request an asset (self-service) | Asset type | same list | **empty** | fixed by the same list |
| Exits > start exit / Resign | Reason | `exit_reason` list | **empty (0)** | 10 reasons, editable |
| Helpdesk > new ticket (module hidden for CTD) | Topic | `ticket_category` list | **empty (0)** | 5 topics |
| Assets > Fulfil request | Asset in stock | assets in stock | always has "Pick automatically" | ok |
| Assets > Allocate | Person (search) | employees | ok | ok |
| People > Documents | Document type | `document_type` (5 seeded) | ok | ok |
| People > Job change | Department / Location | departments, offices | ok | ok |
| Schedule interview | Candidate / interviewer | candidates, interviewers | ok | ok |
| Interviewers > Pools | People | users | ok | ok |
| Onboarding > Start onboarding | Signed offer | ready offers | shows an empty-state line when none | ok |
| Joiner actions (withdraw / declined / no-show / exits) | Reason | fixed lists in `joiner_actions.py` | ok | ok |

**Assets with the Assets module hidden:** assigning from the Employee list and profile is part of **20.1** (it uses its own endpoint, not the module-gated `/service-desk/assets`). Assets already appear in the exit clearance checklist (`joiner_actions.record_exit` -> clearance "Return <asset>").

**Proof (live app, 2026-10-06):**
- `p20-0d-assets-add-dialog-dropdown`: Assets > Add an asset > Type opens **above** the dialog with the 10 types and "+ Add asset type".
- `p20-0d-add-type-inline`: the inline add.
- `p20-0d-asset-type-dropdown-in-dialog`: the same list in the Employee "Assign asset" dialog.
- `p20-0d-settings-asset-categories`: the Settings list.

---

## 20.1 Employees tab

**Built:**
- Menu **People > Employees** (first in the group, always on). It is not the older hidden People module, although it uses the same `employees` rows. The old `/employees` route forwarded to that hidden module; it is now this page. The old links to `/employees/<id>` open the new profile.
- Columns (column chooser + saved views):
  - Employee ID, Photo + Name, Designation, Department, Manager, Location, Joined on
  - Experience here (today - joined, or the exit date - joined)
  - Overall experience (previous experience from the resume at hire, editable, + experience here; e.g. "4 yrs 3 mths")
  - Company email (grey **TEST** chip for test mailboxes), Phone, Employment type
  - Status (Active / Notice period / Exited / Absconded)
  - App account (Active / Invited / Disabled / No account)
  - Roles (app roles + "Manager" when someone reports to them + "Interviewer" when in a pool or with availability)
- Filters: search (name, ID, email, phone), department, location, status, role, joined between.
- Exports: **Excel** of the visible columns (`GET /api/v1/ui/employees/export.xlsx`, audited), plus the toolbar's CSV.
- Bulk: **Resend app invite**.
- Row click -> **profile** with Personal / Job / Documents / Assets / History. Bank, PAN and Aadhaar are masked; the audited reveal stays on the HR record.
- Row "..." menu: View profile, Edit, Assign asset, Resend app invite. Make interviewer (20.4) and Start exit (20.3) plug in through `components/employees/registry.tsx`.
- **Assign asset** works with the Assets module hidden: own endpoint `POST /api/v1/ui/employees/{id}/assets`, from stock or a new asset registered on the spot. Mark returned also works there.
- **Edit:** corrections, logged with before/after (`employee_details_corrected`). The **Employee ID is read-only**.
- **Employee ID format:** Settings > Onboarding & employees > **Employee ID** (prefix + digits, preview of the next ID). It edits the `core_hr.employee_code` sequence pattern; the running number carries on, so an ID is never reused, and existing IDs never change. Audited `employee_id_format_changed`.
- Decision: **CTD Techs set to `CTD-{SEQ:4}`.** The next new employee gets CTD-0024; the counter was at 23. Kishore keeps EMP-00022.
- Migration `b24d6e7f8a9c`:
  - employees: `company_email`, `company_email_provider`, `joined_on`, `previous_experience_months`, `rehire_eligible`, `exited_on`, `candidate_id`
  - statuses `exited` / `absconded`
  - `users.password_set_at` (Invited = never set a password); it is written by the set-password link

**Proof:**
- `p20-1-employees-list`: the list. CTD Techs has 1 real employee today (Kishore Gunda, EMP-00022, Active, app account Active, role Employee). The demo employees come in 20.2b.
- `p20-1-employee-profile`, `p20-1-profile-job`: the profile.
- `p20-1-settings-employee-id`: the Employee ID setting.
- Found during proof: the menu item was there but 4th in People (below Exits, out of view in the sidebar); it now comes first.

---

## 20.2 Agent: onboarding completed -> employee created

**Built** (`app/employees/creation.py`, `mailboxes.py`, `accounts.py`):
- **Trigger:** "Mark as joined" (= onboarding complete). `joiner_actions.mark_joined` calls `creation.on_joined`. The older conversion no longer makes a login on the **personal** email (`convert(..., create_account=False)`); the agent makes it with the company email after approval.
- **Duplicate check:**
  - Same candidate or same personal email -> the same person: the existing record is **linked**, never duplicated.
  - Same phone, or same name + date of birth -> the card asks **"Is this the same person as CTD-0007?"** and won't create anything until HR answers.
- **The record** (from candidate + offer + job + joining details):
  - first/last/preferred name, designation (offer, else job title)
  - department and location (matched by name; the card says when the job's text didn't match, so HR picks)
  - manager (the job's hiring manager, if they are an employee), joining date
  - employment type (job type), previous experience (resume `total_experience_years`)
  - personal email/phone, emergency contact
  - **bank / PAN / Aadhaar moved from the joining form into the encrypted employee fields** (masked everywhere)
- **Employee ID:** the pre-hire record's ID, from the Employee ID format.
- **Company email:**
  - Built from the pattern (Settings: `employees.email.pattern` `{first}.{last}`, fallbacks `{first}.{l}`, `{first}.{last}{n}`; domain = setting, else the admins' sign-in domain) and **checked free**: not used here, and free at the provider.
  - Created through the email-admin connection (purpose `directory.mailboxes`). New connection types:
    - **Google Workspace** (Admin SDK Directory API, service-account JSON in SecretStore)
    - **Microsoft 365** (Graph, client id/secret in SecretStore)
    - Both are written against the public APIs but **not run against a live tenant yet**.
  - A provider's first password is returned **once** to show HR on screen and is never stored, logged or emailed.
  - **No connection:** an IT to-do "Create mailbox kishore.gunda@ctdtechs.com for Kishore Gunda (joins 2026-10-14)" with **"Done - mailbox created"** (IT can correct the address). The login moves to it and a fresh invite goes there.
- **App account:** login = company email (personal email until a mailbox exists). Role Employee + roles from the rules (`employees.default_roles`, `employees.role_rules`, e.g. designation contains "Interviewer" -> Interviewer). An invite with a "Set your password" link (72 h, single use) goes to the company email + the personal email as backup.
- **Move to Employees:** status Active; the onboarding "Joined recently" row shows **"Employee created - CTD-0012"** (or "Approve employee" while the card waits).
- **Human in the loop:** Settings `employees.on_onboarding_complete` = `approve` (**default**) or `automatic`.
  - The approval card is on **Employees** (top) and in the inbox to-dos (`/employees?card=<id>`).
  - It shows and lets HR edit everything: ID (read-only), names, designation, department, location, type, joining date, previous experience, company email (live "free?" check), roles; the duplicate question when needed.
  - "Approve and create" / "Not now".
- **Failures** (e.g. mailbox API error, invite email failed) show per step in plain words, with **Retry**. Steps already done are not repeated. Everything is audited: `employee_prepared`, `employee_created`, `employee_creation_step_failed`, `mailbox_created`, `it_todo_*`, `app_invite_sent`, `employee_account_created`.

**Proof:** in 20.6, on the isolated proof stack (mailpit), because the live backend would send invites through the real company mailbox.

---

## Fix (owner, 2026-10-06): exit interview moved to employee self-service

**Real cause:**
- `frontend/src/components/servicedesk/ExitCaseDialog.tsx` (HR's exit page) rendered the exit interview as an **editable form** for HR (`{open && canEdit && (<Block … "exits.interview.title">` with TextFields / Rating / Yes-Maybe-No).
- It saved through `POST /api/v1/service-desk/separations/{id}/exit-interview` with HR's `separation.case.edit`.
- The employee's own exit page could never show it: `GET /api/v1/ui/servicedesk/me/separation` **removed** `exit_interview` from the employee's row ("an employee sees progress, not HR's notes").
- There was no employee endpoint at all, so only HR could "answer".
- Any role with `separation.case.view` (e.g. **Manager**) received `exit_interview` and the AI summary in the overview and detail responses.

**Change:**
- **Employee** (`app/employees/exit_interview.py`, `/api/v1/ui/exit-interview/me`, `ExitInterviewCards.tsx`):
  - After "Send resignation" -> **"Step 2: A few questions before you go"** (Skip for now).
  - Later on the employee's exit page until the last working day.
  - The same 6 questions: main reason, liked most, do better, manager support 1-5 stars, recommend Yes/Maybe/No, come back Yes/Maybe/No.
  - Top line: **"Your answers go only to HR. Your manager will not see them."** Autosaved draft; Submit; read-only afterwards.
- **HR** (`HrExitInterviewCard`): a **read-only** card with:
  - status (Not started / In progress / Submitted on <date>)
  - the answers
  - **"AI summary - check the answers"**, made automatically on submit, with "Make the summary again"
  - **Send reminder to employee**
  - **HR notes (private)** (new column `separations.exit_interview_hr_notes`, migration `d26f8a9b0c1e`)
- No editing of the employee's answers. **"Record answers from a call"** only when the person can't answer (absconded, terminated, deceased, or no / disabled app account), saved as **"Filled by HR on <date> (call with employee)"**. The old POST path now does only this and returns 409 otherwise.
- **Managers can't see answers**, enforced in the API:
  - new permissions `separation_hr.exit_interview.view/.edit` in their own module, because the Manager role gets everything under `separation` with view;
  - granted to HR Admin, HRBP and Super Admin only;
  - overview and detail responses drop `exit_interview` / the AI summary for anyone else, and keep only the status.
- **Settings > Onboarding & employees > Exit interview:**
  - add / remove / reorder questions
  - type text, stars, Yes/Maybe/No, or a choice list
  - required per question (default all optional)
  - en/hi/ta text
  - AI summary on/off
  - reminder days before the last day (default 3)
  - Submitted answers keep the questions they were given.
- **Reminder email** (`employee.exit_interview_reminder`): automatic from the hourly job `exit_interview_reminders` when the last day is within the reminder days and nothing is submitted (once), or with HR's button.
- **Reports > Exit interviews** (HR only): reasons, manager-support average, would recommend / come back, by department, manager and tenure band. Totals only, never individual answers. A manager gets 403.

**Proof** (proof stack: API :8010 with mail capture, web :5174, mailpit; demo employees; the test resignations were removed afterwards):
| Check | Result | Screenshot |
|---|---|---|
| Employee (Demo - Aarav) resigns -> step 2 | "Step 2: A few questions before you go", privacy line, Skip for now | fix-ei-01, fix-ei-02 |
| Answers autosave, Submit | "Draft saved"; after Submit read-only "Thank you - HR has your answers" | fix-ei-03, fix-ei-04 |
| HR opens the exit | read-only answers + "AI summary - check the answers" (5 bullets); the only input is HR notes | fix-ei-05 |
| HR tries to write answers (old path / record-call while the employee can answer) | **409** "The employee can answer themselves - send them a reminder instead…" | api |
| Manager (Demo - Sneha, Manager role) | card API **403**; overview + detail have **no** `exit_interview` / AI keys (status only); report **403**; dialog shows no answers | fix-ei-06 |
| Not filled (Demo - Kabir) -> Send reminder | mailpit: "A few questions before you go" to the TEST mailbox + personal email | fix-ei-08 |
| Settings, report | question editor; totals by department / manager / tenure | fix-ei-09, fix-ei-10 |

**Found and fixed during the proof:**
1. The autosave built the next draft from a stale copy of the answers. It now uses the latest answers; a second version that read them after the component's early return crashed the page and was fixed the same minute.
2. The reminder said "Before your last day (your last working day)" when no last day was set. It now says "Before your last working day" (also fixed in the stored template).

**Note:** the live backend reloaded the new hourly job straight away and sent **one automatic reminder to Kishore Gunda** (his requested last day is today; audit `exit_interview_reminder_sent`, 11:33). That is the intended behaviour, but it went out before this proof.
The star rating in the proof reads 1/5 because the test clicked the first star; it is test data.

## Feat -- actionable exit checklist + asset returns (2026-10-06)

**Before:** the exit "Handover checklist" listed 5 items as "To do" that nobody could finish. The employee's page and HR's exit dialog only displayed them; Mark done / Skip lived on a hidden "Board" tab; "Revoke access" revoked nothing; "Exit interview and documents" never completed itself; the relieving / experience letter templates did not exist.

**Now** (`app/employees/exit_checklist.py`, `/api/v1/ui/exit-checklist`, `components/exits/ExitChecklist.tsx`, migration `e27a9b0c1d2f`):
- Every item has a status (To do / Requested / Waiting for confirmation / Done / Not applicable + reason / Blocked + reason), an owner, a due date (last working day minus the item's days) and a history. It opens to show the buttons for the person looking at it. Overdue items turn red.
- **One line per assigned asset**, plus the ID and access cards:
  - HR/Admin: **Request return** (email + to-do for the employee)
  - employee: **I have returned it** (note / photo)
  - owner: **Received** (Good / Damaged / Missing parts; the asset goes back In stock) or **Lost / not returned** (the amount is added to the Finance item)
  - no assets at all -> "No assets assigned" (done)
- **Revoke system and email access:** **Revoke now** or **On the last working day** turns off the app login and suspends the company mailbox through the email provider (TEST provider for now). Without an email-admin connection, IT gets a to-do and confirms by hand.
- **Settle advances and reimbursements:** amounts to recover / pay (lost-asset recoveries are listed), or **Nothing pending**.
- **Handover sign-off:** the manager's item. Notes, who takes over (pick or type), knowledge-transfer document.
- **Exit interview and documents:** done by itself when both of these are true:
  - the exit interview is in: submitted, recorded from a call, or "No exit interview" with a reason (not answered by the last day counts as not answered);
  - both letters exist. They are made automatically once every other required item is done; default templates are created when missing.
- **The exit completes by itself** the day after the last working day, once every required item is Done / Not applicable (open optional items are closed with it). On completion:
  - employee Exited, app login off, mailbox suspended
  - removed from interviewer pools
  - letters emailed as PDFs to the personal email
- HR can close earlier only after the last day, with a reason. The old "Close the exit" button runs the same completion.
- Changing the last working day moves the due dates and a scheduled revoke, and remakes letters that weren't sent yet.
- **Owners:**
  - email when assigned, and when the employee says an item is returned
  - a reminder the day before it is due (hourly job `exit_checklist`)
  - email links `/exits?item=<id>` open the item
  - non-HR owners see **My exit tasks**
  - demo employees never email real staff
- **Settings > Onboarding & employees > Exit checklist:** items, owner, owner email, due days, required, how each item completes, card names.

**Proof** (proof stack: API :8010 with mail capture, web :5174, mailpit; demo employees Diya CTD-9002, Meera CTD-9004 and Rohan CTD-9005, manager Sneha CTD-9006; all test records removed afterwards and the demo employees restored):
| Check | Result | Screenshot |
|---|---|---|
| Diya resigns, HR confirms the last day | 7 items: laptop (proof asset PROOF-XC-1), ID card, access card, handover (manager Sneha, due a day earlier -> Overdue), revoke, finance, exit docs; each with owner + due date + actions | fix-xc-01, fix-xc-02 |
| Employee's own page | same list; "Your turn" only on her asset lines | fix-xc-03 |
| HR: Request return (laptop) | status Requested; mailpit: "Please return: Laptop - Proof Dell Latitude 5440, tag PROOF-XC-1" to her (TEST) mailbox | fix-xc-04 |
| Employee: I have returned it (access card, note + photo) | Waiting for confirmation; note + photo on the item, history entry | fix-xc-05..07 |
| HR: Received Good (laptop) | DB: asset `in_stock`, allocation returned, condition good, received by proof HR | fix-xc-09 |
| HR: Lost (ID card), 500 | item Done, amount 500; the Finance item shows "Recover 500 for Return ID card" | fix-xc-08 |
| Manager Sneha opens the email link `/exits?item=<handover>` | the exit opens with the handover item expanded; she signs off with notes and Aarav taking over | fix-xc-11 |
| Finance: recover 500 | Done | fix-xc-10 |
| IT: Revoke now | DB: user `deactivated_at` set; `test_mailboxes` status `suspended`; the employee's next API call -> 401 | fix-xc-12, fix-xc-13 |
| Exit docs | letters made automatically once the rest was done; interview recorded from a call -> Done by itself ("Exit interview recorded from a call; relieving and experience letters generated") | fix-xc-14 |
| Last day is today | 7/7 done, "The exit completes by itself after the last working day" (not completed yet) | fix-xc-14 |
| Next day (last day moved to 5 Oct, hourly job run) | job `{'reminders': 0, 'completed': 1}`; employee `exited`, exited_on 2026-10-05; mailpit: "Your relieving and experience letters from CTD Techs" with relieving-letter-CTD-9002.pdf + experience-letter-CTD-9002.pdf | fix-xc-15 |
| Meera (no assets): HR-started exit, revoke "On the last working day", last day moved | "No assets assigned" line (done); revoke Requested for 7 Oct and moved with the last day; one job run: revoke -> letters -> completed | api |
| Rohan: letters made, then the last day moved | letter ids replaced (f2f247b1 -> efd7fc02); emailed PDF reads "from 01 Jan 2026 to 05 Oct 2026" | api |
| Settings page | items, owner, due days, required, how each completes | fix-xc-16 |

**Found and fixed during the proof:**
1. Letters failed with "'today' is undefined". `letters.publish` test-renders with the template's required variables only. The default templates now list their variables and use `company_name`.
2. The exit completed **on** the last working day. It now completes the day after (the old Close button too).
3. Letters made before the last day changed kept the old date. Unsent letters are now made again.
4. A scheduled revoke kept its old date when the last day changed. It now follows the new day, and runs before the letters check, so completion happens in the same job run.
5. The job counted reminders that weren't sent (demo owners). It now counts real sends only.
6. The attached photo was labelled "Add a photo". It now reads "Photo".

**Notes:**
- The owner's live exit (Kishore Gunda, last day 11 Nov) already has the new items. Nothing was changed on it.
- For demo employees, owner emails go only to @example.com addresses, so "assigned" / "returned" emails to IT/Admin/Finance don't appear in mailpit. For real exits they go to the item's owner, or to the HR admins when no person is named.
- Revoking before the last day also stops the employee answering the exit interview (expected). "On the last working day" is the softer option.

## part-20.2b (UI) -- Settings > Integrations > Test email provider (2026-10-06)

`components/employees/TestEmailProviderPage.tsx` (backend from bf0de57: `/api/v1/ui/employees/test-provider*`):
- **On / off switch.** On makes the TEST provider the email-admin connection (first in line); off sends new employees through the real connection, or to IT as a to-do. Shows the domain.
  - On this computer, a note that mail is also copied to mailpit.
  - A red warning on the live system while the test provider is still on (the same check is on Configuration health).
- **Test mailboxes table:** address + grey TEST chip, person + Employee ID + created date, Active / Suspended, **Open inbox (n)**. Under the table: "Each mailbox: 15 GB (dummy). Password: none - each person sets their app password from the invite link."
- **Test inbox:** list of emails the app sent to that address; the body is shown as text, or as HTML in a sandboxed frame.
- **Move test mailboxes to a real provider:** **Show who would move** (dry run) lists active / on-notice employees. Without Google Workspace / Microsoft 365 it says "would move once ... is connected" and blocks. With one connected, **Create the real mailboxes now**; first passwords are shown once and never stored. Never automatic.
- The TEST chip in employee screens and the Employees-page banner were already in place (20.1 / 20.2).

**Proof** (live app, temporary admin, removed afterwards):
| Check | Result | Screenshot |
|---|---|---|
| Page | switch ON, domain ctdtechs.com, 8 demo mailboxes (Vikram's Suspended - the demo exited employee) | fix-tp-01 |
| Inbox | a sample message delivered through `test_inbox.deliver` appears in Aarav's inbox and opens (sample removed afterwards) | fix-tp-02 |
| Dry run | 7 would move (the suspended one not included); blocked: "Connect Google Workspace or Microsoft 365 first" | fix-tp-03 |

Fixed while taking the proof: the table was too wide for the settings panel (Inbox column cut off), so quota and password moved into one line under the table. The dry run said "would move to -" when no provider was connected; it now says "once Google Workspace or Microsoft 365 is connected".
