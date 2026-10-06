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
