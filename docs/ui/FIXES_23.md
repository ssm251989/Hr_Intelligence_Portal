# PART 23 - finish, prove and commit

## 23.1 Phase 0 - Bedrock gateway, unit costs, "AI Intelligence" rename

### 1. Files present (2026-10-30)

`git status` before the commit: 18 modified + 4 new Phase 0 files, all on the 23.1 list
(`bedrock.py`, `unit_costs.py`, `bedrock_provider.py`, `test_bedrock_and_unit_costs.py` new).
`git diff --stat`: `18 files changed, 448 insertions(+), 98 deletions(-)`.

```
backend\app\platform\ai\bedrock.py:44:def bedrock_model_id(model: Optional[str], config: BedrockConfig) -> Optional[str]:
backend\app\platform\ai\unit_costs.py:47:def compute(usage: Iterable[UsageRow], applications: Iterable[AppRow], jobs: dict, hires_in_period: Optional[int] = None) -> dict:
backend\app\platform\ai\governance.py:178:def price_tokens(pricing: dict, currency: Optional[str], fx_rates: dict, model: Optional[str], input_tokens: int, output_tokens: int) -> Decimal:
backend\app\experience\ui_genai_router.py:289:@router.get("/unit-costs")
frontend\src\pages\genai\GenAIUsagePage.tsx:53:  ... http.get<UnitCosts>(`/api/v1/ui/genai/unit-costs?period=${period}`) ...
```

Nothing missing.

### 2. Install

`pip install "anthropic[bedrock]"` in `backend/.venv`: anthropic 0.120.2, boto3 1.43.122, `from anthropic import AnthropicBedrock` imports.

### 3. Tests

| Run | Result |
|---|---|
| `test_bedrock_and_unit_costs.py` + `test_llm_gateway_routing.py` | **19 passed** |
| Full backend suite (once) | **1320 passed, 165 failed** in 26 min |
| The same 165 tests on unmodified HEAD `7b342e0` (separate git worktree, same DB) | **165 failed** |

**None of the 165 failures is caused by Phase 0**: every one of them also fails without the Phase 0 change
(`comm` of the two failure lists is empty). Phase 0 files add no new hardcode-guard finding (the
`core/config.py` 96-108 and `help_catalog.py:124` hits are Part 19.2 / older lines).

But the list is much longer than the 4 known failures in build_log, so the baseline has drifted. Real causes,
quoted from the run:

| Tests | Count | Real cause (quoted) |
|---|---|---|
| test_interview_negotiation / _confirmation / _scheduling, test_scheduling | 68 | `AttributeError: 'NoneType' object has no attribute 'round_day'`, `assert None == 'started'`, `'No interviewer is set up for Automation Anywhere Architect. Add one ... in Interviews > Interviewers.'` - the tests still set up the old interviewer pool; interviewers now come from Interviews > Interviewers |
| test_remarks, test_screening, test_screening_service, test_screening_settings | 44 | `'Strong fit (...score 90/100)' == 'Strong fit (Screening: 90%)'`, `KeyError: 'experience_score'`, `'hr_selected' == 'screened'` - remark wording / score shape / statuses changed after the tests were written |
| test_public, test_salary | 11 | `assert 400 == 201` on submit-application, `assert 400 == 200` on salary validation |
| test_candidates, test_suitability_service | 7 | `<lambda>() got an unexpected keyword argument 'file_bytes'` - the tests' fake `parse_resume` predates the `file_bytes` argument |
| test_service_desk | 8 | `jinja2.exceptions.UndefinedError: 'last_working_day' is undefined`, `KeyError`, pagination counts |
| test_experience | 4 | `missing_help(...)`: 59 settings without help (first: `ai.available_models`), disabled-module 404, nav |
| test_intelligence | 3 | `BudgetExceededError: AI budget for 2026-10 is used up` on the **first** call - ambient usage in the shared live DB (100-token test budget) |
| test_recruitment | 3 | `assert 7 == 23` statuses in the seeded pipeline template |
| test_login_flow_mfa_and_sessions, test_mfa_required | 4 | MFA flow |
| test_settings_resolver | 1 | `UnknownSettingError: recruitment.screening.auto_shortlist_threshold` (known) |
| test_no_hardcoded_tenant_values | 1 | 257 findings (known class) |
| others (core_hr 2, performance 2, local_import 3, reports 1, roles_bridge 1, platform_ops 1, applications 1) | 11 | see `-rfE` output |

These need their own clean-up item (open, below). They are not fixed in 23.1.

### 4. Frontend

`npx tsc -p tsconfig.app.json`: exit 0. `npm run build`: built; the only warning is a direct `eval` inside
`node_modules/lottie-web` (not our code).

### 5. On screen (proof stack: API :8010 from backend/.venv, web :5174, mailpit; temp admin)

| Check | Screenshot |
|---|---|
| Provider switch lists "Anthropic Claude (direct)" and "Claude on Amazon Bedrock (AWS)" | `screens/p23-1-ai-provider-options.png` |
| Bedrock chosen: region (empty = ap-south-1 server default), routing, AWS identity, example model id `global.anthropic.claude-sonnet-5`, model id overrides box | `screens/p23-1-ai-settings-bedrock.png` |
| Switched back to Anthropic | `screens/p23-1-ai-settings-back-to-anthropic.png` |
| Usage page: "Unit costs (AI only)" card (per resume / per job / per hire) + per-job table | `screens/p23-1-ai-usage-en.png` |
| Labels in Hindi / Tamil ("AI इंटेलिजेंस", "AI இன்டெலிஜென்ஸ்") | `screens/p23-1-ai-usage-hi.png`, `-ai-settings-hi.png`, `-ai-usage-ta.png`, `-ai-settings-ta.png` |

Script: `frontend/scripts/p23_ai_shots.mjs` (token from env, never stored).

**Fix found on screen:** the Bedrock "Where requests are processed" box looked empty, because its saved value
`""` (= server default) is hidden by MUI unless `displayEmpty` is set. Added `displayEmpty` + shrunk label
in `GenAISettingsPage.tsx`; it now reads "Server default (global.)".

**Unit-cost proof with a real call.** Every AI usage row in the period was from 4-7 Oct (latest
`2026-10-07 12:49:11`), recorded before Phase 0 prices existed, so each had `cost = 0` and the card showed
INR 0. One JD draft on a throwaway job gave:

```
('recruitment.jd_generation', 'claude-sonnet-5', 'job:df97af83-...', 1 row, 1599 in, 458 out, cost 0.684464)
```

(1599 x $2 + 458 x $10) / 1M = $0.007778; x 88 (ai.fx_rates USD) = **INR 0.684464** - matches. The row
carries the catalog model id and the job, and the card showed "Per job INR 0.68 - 1 jobs used AI" with the
job in the per-job table.

**Provider safety.** The switch writes the shared tenant setting. Bedrock was on for about 3 seconds each time
(2026-10-30 16:17:36-38, 2026-11-02 09:27:29-31 and 09:29:20-23). No AI call happened in those windows (latest
usage row stays 2026-10-07).

**Clean-up (done):** proof job + its usage row + 2 audit rows; the `ai.provider` company override and its 6
history rows (there was **no** override before, the default is `anthropic`, so it was removed, not set back);
the temp admin's language preference (1 value, 3 history), role assignment and user. A scan of every
uuid/text column for the job id and the admin id finds nothing left.

### Still open after 23.1

- **165 pre-existing backend test failures** (table above) - not Phase 0; needs a separate clean-up item.
- On the Bedrock view, "Last test passed 10/5/2026" is the old Anthropic-key test; it should say "not tested
  yet" until Test is pressed with Bedrock (23.2).
- Usage rows from before Phase 0 stay at cost 0 (not re-priced).
- Feature names in the AI settings table ("JD drafting", ...) come from the backend in English.
- The settings menu entry is still "AI provider & HR assistant" (the card is "AI Intelligence connection").
- The owner's API on :8000 runs as `Python312\python.exe -m uvicorn app.main:app --reload` (system Python),
  and that interpreter has **no** `anthropic` package (`ModuleNotFoundError: No module named 'anthropic'`).
  Bedrock (and Anthropic) calls need it started from `backend/.venv`.

## 23.1b Bedrock test status + menu label (2026-11-02)

Four files were changed outside the session (`ui_genai_router.py`, `GenAISettingsPage.tsx`, `part18.ts`,
`settingsHome.ts`): Bedrock keeps its own "last test" (on the company's Bedrock connection, created by the first
Test) and shows "not tested yet - press Test" until then; the settings menu says "AI Intelligence & HR assistant"
(EN / HI / TA). Closes the two 23.1 open items "old Anthropic test shown on Bedrock" and "menu entry".

`npx tsc -p tsconfig.app.json`: exit 0. `npm run build`: built (only the known `lottie-web` eval warning).
`test_bedrock_and_unit_costs.py` + `test_llm_gateway_routing.py`: 19 passed.

| Check | Screenshot |
|---|---|
| Settings > Integrations: menu entry "AI Intelligence & HR assistant"; card hint now "AI Intelligence, e-sign, ..." | `screens/p23-1b-settings-menu.png`, `p23-1b-settings-home.png` |
| Anthropic view keeps its own test: "Last test passed 10/5/2026, 10:02:45 PM" | `screens/p23-1b-anthropic-own-test.png` |
| Bedrock chosen: "not tested yet - press Test" | `screens/p23-1b-bedrock-not-tested.png` |
| Test pressed with Bedrock (no AWS access here): `{"ok":false,"error":"could not resolve credentials from session"}` -> "Last test failed 11/2/2026, 3:42:50 PM"; the Anthropic row is unchanged | `screens/p23-1b-bedrock-after-test.png` |
| Back to Anthropic: "Last test passed 10/5/2026" again | `screens/p23-1b-back-to-anthropic.png` |

Script: `frontend/scripts/p23_1b_shots.mjs`.

**Fix found on screen.** The first run saved the failed Bedrock test on the **Anthropic** row
(`last_test_result = {'error': 'could not resolve credentials from session', 'success': False}` on
"Anthropic (platform key)"), and Bedrock still said "not tested yet". Cause: the Bedrock test took **8.0 s**
(AWS credential lookup; repro script: `before call: amazon_bedrock` / `call failed after 8.0s` / `after call:
amazon_bedrock`), and the provider was switched back at 15:39:13 while the test that started at 15:39:08.955
was still running; `/test` read the provider **after** the call to choose the connection. Fix: `/test` decides
Bedrock vs Anthropic **before** the call, so the result stays with the provider that was tested (also when
someone switches meanwhile). Also left over from the rename: the Integrations card hint said "AI provider, ..."
-> "AI Intelligence, ..." (EN / HI / TA).

**Clean-up (done):** Anthropic row's last test put back to 2026-10-05 22:02:45 / passed (the value before the
run); the "Amazon Bedrock" connection created by the Test deleted (back to "not tested yet"); the `ai.provider`
override + 6 history rows deleted (there was no override before); 3 `platform.genai_test` error usage rows
deleted. `GET /ui/genai/settings` after: provider `anthropic`, bedrock `last_tested_at` None, key last test
2026-10-05 passed.

## 23.3 On-screen proofs (proof stack restarted 2026-11-02)

Proof stack: mailpit (fresh `mailpit-p23.db`), API :8010 from `backend/.venv` with `DEV_MAIL_CAPTURE`, web :5174,
temporary admin `proof.admin.p23@example.com` (role copied from kg@ctdtechs.com). Free memory was about 1.4 GB,
so only one API process ran. Proof data comes from one fixture script (`Proof ...` names, `@example.com`
addresses). The clean-up deletes every recorded row plus rows the app made for them (found by scanning every uuid
column for the proof ids, and audit rows by actor / details text), then scans again.

### 23.3a BGV - Download all + BGV vendor (21.4)

Data: job "Proof - BGV Analyst (P23)", candidates **Proof Ananya Rao** and **Proof Vikram Sethi** at "BGV
requested", with 3 generated PDFs each (Aadhaar, degree, experience). BGV vendors **Proof Verify Co (P23)**
(type BGV; education 800, employment 900, address 600, criminal 1200; 5 days) and **Proof Second Checks (P23)**
(type Both). Script: `frontend/scripts/p23_3a_bgv_shots.mjs` (phases A / B / C).

| Step | Result | Screenshot |
|---|---|---|
| BGV page with both proof candidates | stage table + job picker | `p23-3a-bgv-page.png` |
| **Download all** on a candidate card | `Proof Ananya Rao - BGV documents.zip`: `Aadhaar/…pdf`, `Degree/…pdf`, `Experience/…pdf` + **`BGV summary.xlsx`** (candidate, job, BGV status, document, type, document status, "In the ZIP" = yes) | `p23-3a-vendor-card-empty.png` |
| **Download all (2)** from the table's bulk bar | `bgv-documents-2-candidates.zip`: one folder per candidate (6 PDFs) + one `BGV summary.xlsx` with 6 rows | `p23-3a-bulk-bar.png` |
| **Assign BGV vendor** (Proof Verify Co, Education + Employment, due = today + 5 days) | assignment `assigned`, due 2026-11-07, cost 1700; mailpit: "Background check request: Proof Ananya Rao (Proof - BGV Analyst (P23)) - CTD Techs" to the vendor with the secure link `http://127.0.0.1:5174/bgv-vendor/<token>` | `p23-3a-assign-dialog.png`, `-assigned.png`, `-mail-assigned.png` |
| Vendor opens the link | page shows company, vendor, candidate, role, due date, the 2 checks, 3 documents to download; status -> **`in_progress`** | `p23-3a-vendor-page.png` |
| Vendor uploads the report with a note | "Report received. Thank you - HR has been told."; status -> **`report_received`** | `p23-3a-vendor-upload.png`, `-vendor-uploaded.png` |
| HR is notified | card: "Report received Nov 2, 2026 - Proof Verify Co - BGV report - Ananya Rao.pdf" + vendor's note + **Download report**; bell: "BGV report received for Proof Ananya Rao … from Proof Verify Co (P23) - decide now" | `p23-3a-report-received.png`, `-hr-notice.png` |
| **Discrepancy - clear with a note** (note required) | application **`bgv_cleared`**, assignment `decided / discrepancy`; card moves it to "Earlier assignments" | `p23-3a-discrepancy-dialog.png`, `-discrepancy-done.png` |
| **Reminder**: Vikram assigned with due date tomorrow, daily job `vendors.run_reminders` run once | `{'reminders': 1}`; mailpit: "Reminder: background check for Proof Vikram Sethi tomorrow"; listed on the card | `p23-3a-reminder-on-card.png`, `-mail-reminder.png` |
| **Reassign** to Proof Second Checks | old assignment `cancelled (reassigned to Proof Second Checks (P23))`; mailpit: "…is cancelled" to vendor 1 + a new request to vendor 2 | `p23-3a-reassign-dialog.png`, `-reassigned.png` |
| **Cancel assignment** with a reason | `cancelled (Candidate withdrew - no checks needed.)`; mailpit: "Background check for Proof Vikram Sethi is cancelled" to vendor 2 | `p23-3a-cancelled.png`, `-mail-latest-vikram.png` |

Mailpit had exactly the 6 vendor emails (`p23-3a-mailpit-inbox.png`): request (Ananya), request (Vikram),
reminder, cancelled (vendor 1, from the reassign), request (vendor 2), cancelled (vendor 2).

**Fix found on screen:** the bell's "Hiring activity" said "**Bgv** vendor assigned / opened / report received".
Cause: `reports/router.py` `_humanize_action` only upper-cased the first letter of the raw action. Acronyms
(BGV, HR, AI, JD, CTC, ID, LWD, PDF) now keep their capitals ("BGV vendor assigned"); `test_reports -k activity`
7 passed.

**Note (by design, not changed):** while a vendor works on a case the application stays "BGV requested"
(the vendor status lives on the assignment), so the table chip "BGV in progress" stays 0.

**Clean-up (done):** 1 job, 2 candidates, 2 applications, 6 BGV documents, 2 agencies, 3 assignments,
9 messages (incl. the in-app notice to kg@ctdtechs.com), 9 audit rows, 7 files (6 PDFs + the vendor report).
Scan of every uuid column afterwards: nothing left.

### 23.3b Agencies - Recruitment / BGV / Both (21.5)

Script: `frontend/scripts/p23_3b_agency_shots.mjs` (A: add + edit through the form; B: filter, stats, sample, import).

| Step | Result | Screenshot |
|---|---|---|
| Add **Recruitment** agency "Proof TalentReach (P23)": contact, email, phone, address, fee **8.33 % of annual CTC**, payment terms | saved `recruitment`, fee `percent / 8.33` | `p23-3b-form-recruitment.png` |
| Add **BGV** agency "Proof SafeHire Checks (P23)": Education 800, Employment 900, Address 600, turnaround 5, report format | saved `bgv`, 3 checks with prices, turnaround 5 | `p23-3b-form-bgv.png` |
| Add **Both** "Proof AllRound Partners (P23)": fixed fee 40000 + Education 700, Criminal record 1100, turnaround 7 | saved `both` with fee and checks | `p23-3b-form-recruitment-bgv.png` |
| **Edit** SafeHire: turnaround 4, GST / PAN | saved (turnaround 4, GST `PROOF0000P23`) | `p23-3b-edit-dialog.png`, `-edited.png` |
| **Type filter** tabs | All = the 3; Recruitment = TalentReach + AllRound; BGV = SafeHire + AllRound | `p23-3b-filter-all.png`, `-filter-recruitment.png`, `-filter-bgv.png` |
| **Stats**, Recruitment (fixture: 2 candidates sent, 1 hired with annual CTC 900000) | chips "2 sent", "1 hired", "Fees due 74,970" (= 900000 x 8.33 %); the sent list shows both | `p23-3b-stats-recruitment.png` |
| **Stats**, BGV (fixture: 1 case with the report 3 days after assigning, 1 open case 2 days overdue) | "2 BGV cases (1 open)", "Avg 3 days", "1 overdue", "Cost so far 1,700" | `p23-3b-stats-bgv.png` |
| Stats, Both with no activity | recruitment and BGV chips all at 0 / "No reports yet" | `p23-3b-stats-both.png` |
| **Sample import file** + **Import from Excel** (the sample's 2 rows renamed to proof names + 1 bad row: type "Payroll", email "not-an-email") | "2 imported, 1 not: Proof Import Broken (P23): The email "not-an-email" doesn't look right."; "Proof Import Verify (P23)" got its 5 checks from `education:800; employment:1000; ...` | `p23-3b-import-result.png` |

**Bug found and fixed:** the first import run said "**3 agencies imported**". The bad row was stored as a
Recruitment agency with the email `not-an-email`. Cause (`agency_router.py` `import_agencies`):
`types.get(vals[1].lower(), "recruitment")` turned every unknown type into Recruitment, and no email was ever
checked (only the browser form has `type="email"`). Fix:
- blank type = Recruitment, and "Recruitment + BGV" is read as Both;
- any other word is passed through, so the existing check refuses it ("Type must be Recruitment, BGV or Both.");
- one `_clean_email` check is used by add, edit and import.

New `tests/test_agency_import_validation.py`: 3 passed. A refused row rolls back the request's session, and in
the test set-up that would also roll back the test's own transaction, so the row checks are tested directly.

**Clean-up (done):** 5 proof agencies (3 from the form, 2 imported; the 3 from the first import were deleted
before the re-run), 1 job, 4 candidates, 4 applications, 1 offer, 2 submissions, 2 BGV assignments, 6 audit
rows. Scan afterwards: nothing left. Only the real "Bright talent partners" agency remains.

### 23.3c Budget released on exit - pro-rata and full (21.7)

Data: budget "Proof Dept (P23)" FY 2026-27 = 20 L; two hires **Proof Karan Mehta** and **Proof Divya Nair**, each
with 6.5 L committed, joined 1 Jun 2026, resignation in clearance, last working day **15 Oct 2026**, nothing open.
HR's **Complete** (`POST /ui/exit-checklist/separations/{id}/complete`, the button's endpoint) was used for both.
Script: `frontend/scripts/p23_3c_budget_shots.mjs`.

| Step | Result | Screenshot |
|---|---|---|
| Finance dashboard before; Settings > Hiring > Department budgets: "Release budget on exit" on, **pro-rata** (default, no company override) | | `p23-3c-finance-before.png`, `-settings-pro-rata-default.png` |
| Complete Karan's exit (pro-rata) | HTTP 200 `completed`; commitment **379,166.67 still committed, 270,833.33 released** (6.5 L x 5/12: Nov-Mar after the October LWD); history "+2.7 L released - Proof Karan Mehta exited (Proof - Data Engineer 1 (P23)) on 15 Oct 2026 (Proof Dept (P23))" | `p23-3c-finance-after-pro-rata.png` |
| Switch to **Release the full annual amount** | "Saved." | `p23-3c-settings-full.png` |
| Complete Divya's exit (full) | commitment `released`, **650,000** released; history "+6.5 L released - Proof Divya Nair exited ..."; Proof Dept bar "3.8 L of 20 L used - 16.2 L left" (only Karan's spent part stays) | `p23-3c-finance-after-full.png`, `-finance-after-full-page.png` |
| Back to pro-rata | | `p23-3c-settings-back-to-pro-rata.png` |

**Bug found and fixed:** the history's existing real line said "+4 L released - Gunda Kishore - **salary
approved** (AI)". "Salary approved" is a stage, not why money came back. Evidence: the release `released_at
2026-10-07 12:51:33.692` and the audit row `candidate_removed` by kg@ctdtechs.com at `12:51:33.714`. So it was
a **removal**. Cause: `removal.py` and `jobs/cleanup.py` (job closed) called `budgets.release()` without a
reason, and `_dropout_reason` fell back to the application's current status. Fix:
- removal now says "<name> - removed";
- job clean-up says "<name> - job closed (<job>)";
- an unknown status reads "dropped out" (with labels for hr / interview / salary rejected and left after
  joining).

New `tests/test_budget_release_reason.py`: 2 passed. The real 7 Oct row keeps its old text (history data was not
rewritten).

**Observation (real data, not changed):** Department budgets AI and RPA have a quarter split of 10,000 each
(40,000 in total) against a yearly budget of 40,00,000.

**Clean-up (done):** the proof budget, 2 jobs, candidates, applications, commitments, employees, employment
records, joining cases, exits, 6 audit rows; the `recruitment.budgets.release_mode` company override + 2 history
rows (there was none before). Scan: nothing left. Budgets back to AI + RPA, 9 employees.

### 23.3d HR assistant - the 10 questions (22.1)

**Code under test.** The working tree had uncommitted PART 25 changes in this same code (`copilot/service.py`
step 0.5 "agent team", `CopilotWidget.tsx`, LangGraph not installed), written outside this session. So the proof
API ran the **committed** code from a clean git worktree at HEAD `82c3e7d` (same `.venv`, same DB, `uploads`
linked). The real model was used (provider `anthropic`). Script: `frontend/scripts/p23_3d_assistant_shots.mjs`.

| # | Question (expected) | Answer on screen | Source shown | Screenshot |
|---|---|---|---|---|
| 1 | How many casual leaves do I get? (12, max 3 at a time) | "You get 12 casual leaves a year, with a maximum of 3 days at a time [1]." | CTD Techs Employee Handbook - 14. Frequently asked questions | `p23-3d-01-casual-leave.png` |
| 2 | Notice period for a senior employee? (90 days) | "The notice period for Senior, Lead and Manager (L5 and above) employees is 90 days after confirmation [1][4]." | Handbook - 6. Notice period and resignation; 14. FAQ | `p23-3d-02-notice-senior.png` |
| 3 | Can I work from home? (2 days/week after confirmation) | "Yes. After confirmation, employees may work from home up to 2 days a week, with manager approval ... During probation ... only in exceptional cases with HR approval" | Handbook | `p23-3d-03-wfh.png` |
| 4 | When is salary credited? (last working day) | "Salary is credited to the employee's bank account on the last working day of each month [1][2]." | Handbook | `p23-3d-04-salary-date.png` |
| 5 | Hotel limit, junior, metro? (Rs 4,000/night) | "Up to Rs 4,000 per night [1][2]" | Handbook | `p23-3d-05-hotel-junior-metro.png` |
| 6 | How long is probation? (6 months) | "Probation is 6 months, extendable once by up to 3 months [1][2]." | Handbook | `p23-3d-06-probation.png` |
| 7 | How many open jobs do we have? (live) | "You currently have 0 open jobs." (live: all 3 jobs are closed) | live data | `p23-3d-07-open-jobs.png` |
| 8 | Which candidates are waiting for an interview? (live) | "There are currently no candidates waiting for an interview." (live: 2 applications, neither at interview) | live data | `p23-3d-08-waiting-interview.png` |
| 9 | "Eg1" (clarify, no error) | "I'm not sure what you mean - try asking about leave, notice period, salary dates, travel, jobs or candidates." + chips | - | `p23-3d-09-eg1.png` |
| 10 | Not in the handbook: "Is there a company policy on bringing pets to the office?" | "I couldn't find this in your company's policies. You can hand your question over to HR ..." -> **Hand over to HR** | - | `p23-3d-10-not-in-handbook.png`, `-handed-over.png` |

After the hand-over: My approvals > "Also for you" shows **"Question from Proof Admin P23: Is there a company
policy on bringing pets to the office?"** with Reply / Mark done (`p23-3d-11-hr-todo-in-approvals.png`).
Mailpit: **"HR assistant: a question from Proof Admin P23"** to the HR mailbox `hradmin65@gmail.com`
(`p23-3d-12-handover-email.png`). 8 model calls, INR 1.43 in total (6,684 in / 289 out tokens).

**Bug found and fixed:** pressing **Hand over to HR** showed "Something went wrong - This Session's transaction
has been rolled back ...". The real cause, from the API log:
`psycopg2.errors.CheckViolation: new row for relation "agent_suggestions" violates check constraint
"agent_suggestions_agent_check"`. The HR to-do was saved with `agent="copilot"`, but the constraint (and the
model's `AGENTS`) only allow recruiter / onboarding / helpdesk_triage / policy_checker. So **no hand-over could
ever be saved**; the 22.1 dry run stopped before the confirm step. Fix: the to-do is saved as
`helpdesk_triage` (a question routed to HR). My approvals picks the card by `kind = copilot_question`, so nothing
else changes, and no schema change was needed. New `tests/test_copilot_hr_handover.py` fails on the old code
with the same CheckViolation and passes now. The commit has only this hunk of `copilot/service.py`; the PART 25
lines in that file stay uncommitted.

**For PART 25 (not changed here):** in the working tree, `CopilotService._agent_team` imports
`app.hr_agents.graph` **outside** its try block, and `copilot.agents.enabled` defaults to on. Until `langgraph` is
installed, a task-like question from an HR user would fail rather than fall back to the normal assistant.

**Clean-up (done):** 2 conversations, 22 messages, 2 drafts, 8 decision logs, 8 usage rows, the HR to-do, the
email row. Scan: nothing left.

### 23.3e (part 1) Candidate emails + My approvals cards (22.2, 22.3)

Data: job "Proof - Inbox Analyst (P23)", candidates Proofa Ravikumar, Meena Sundar (other email
`meena.home.p23@example.com`), Arun Prakash and Prakash Arun. 7 raw emails (RFC 822) were stored the way the
IMAP poll does: `imap_poll._parse_message` -> `matching.match` -> row -> `triage` (AI summary off, so the
summaries are the email's own first sentence). Script: `frontend/scripts/p23_3e_inbox_shots.mjs`.

| Email | Matching result (DB) |
|---|---|
| from `PROOFA.R.P23@example.com` "Interview time for Thursday" | linked Proofa Ravikumar, rule **email** (case ignored) |
| from `meena.home.p23@example.com` "Documents attached" | linked Meena Sundar, rule **alt_email** |
| sender name "Proofa Ravikumar" from `someone.p23@gmail.example` | linked Proofa, rule **name** (First Last) |
| signature "Regards, Ravikumar Proofa" from `x123.p23@yahoo.example` | linked Proofa, rule **name** (Last First) |
| "Regards, Arun Prakash" from an unknown address | **not linked**, suggestions: Arun Prakash + Prakash Arun |
| "Can I reschedule?" from `vikas.unknown.p23@example.org` | not linked, no suggestions |
| `noreply@bank.p23.example` "Your statement is ready" | status `done`, topic `automated` -> **Closed** |

| On screen | Screenshot |
|---|---|
| Tabs "Needs action (6) / Linked to a candidate (4) / Closed (100)" | `p23-3e-emails-needs-action.png` |
| The ambiguous email: "Not linked yet", "Could be one of these" + **Link to Arun Prakash** / **Link to Prakash Arun** | `p23-3e-emails-not-linked-suggestions.png` |
| Manual link of Vikas's email to Meena Sundar; the tick box "Also remember vikas.unknown.p23@example.org for this candidate" is **on by default** | `p23-3e-emails-manual-link-remember.png`, `-emails-manual-linked.png` |
| "Link to Arun Prakash" pressed on the suggestion | `p23-3e-emails-linked-from-suggestion.png` |
| Linked tab with the rule chips; Closed tab | `p23-3e-emails-linked-tab.png`, `-emails-closed-tab.png` |
| My approvals: 6 highlighted candidate-email cards (blue border, envelope, "Candidate email" chip, summary, time, Open / Reply / Mark done); unread in **bold**, the two opened ones normal; sidebar badge 11 | `p23-3e-approvals-candidate-emails.png`, `-fixed.png` |

DB after: both manual links `match_rule = manual`; Meena's `alt_emails` = `meena.home…`, `vikas.unknown…`; Arun's
= `ap.personal.p23@example.net` (from the suggestion link). `read_at` set only on the emails that were opened.

**Fixes found on screen:**
1. **The card summary said only "Vikas".** Cause (`hr_inbox/triage.py` `first_sentence`): any line that
   **starts** with a greeting and is under 40 characters was dropped whole. So "Hello, can I reschedule my
   call?" (32 characters) went, and the sign-off became the summary. Now only the greeting is dropped ("Can I
   reschedule my call?"). Longer lines are unchanged. New `tests/test_inbox_summary_greeting.py`: 5 passed.
   The proof row was re-triaged to show it.
2. **My approvals said "11 waiting on you" right above "Nothing waiting on you".** The big empty card only
   looked at approvals, not at the "Also for you" items. With only those items, it is now left out
   (`UnifiedInboxPage.tsx`; no new text, because `shell.ts` has uncommitted PART 25 edits).

Not shown: the reply-thread rule (needs an email the app sent with a stored Message-ID; covered by the 22.2 dry
run).

**Clean-up (done):** 1 job, 4 candidates, 4 applications, 7 emails, 4 audit rows. Scan: nothing left.

### 23.3e (part 2) Assign roles (22.4) + agency delete vs deactivate (22.5)

**Assign roles.** Data: employees Proof Roleone Kapoor and Proof Roletwo Iyer, with no app accounts. Script:
`frontend/scripts/p23_3e_roles_shots.mjs`.

| Step | Result | Screenshot |
|---|---|---|
| Row menu > Assign roles (Roleone): "No app account yet", tick **Create account and send invite** + **HR Admin** | account created, invite sent | `p23-3e-roles-employees.png`, `-roles-single-dialog.png`, `-roles-single-result.png` |
| Select both > **Assign roles (2)**: tri-state (HR Admin shows a dash = leave as it is), tick **Finance** = give to all | Roleone +Finance; Roletwo account created (Create account is on by default) + Finance | `p23-3e-roles-bulk-dialog-before.png`, `-roles-bulk-dialog.png`, `-roles-bulk-result.png`, `-roles-employees-after.png` |
| Mailpit | 2 x "Welcome to CTD Techs - set your password for the HR app" (company + personal email), 3 x "Your access in CTD Techs HR was updated" | `p23-3e-roles-mail-1..3.png` |

Audit: `employee_account_created` x2, `app_invite_sent` x2, `roles_changed` x3.

**Bug found and fixed:** after the single dialog, Roleone had **HR Admin + Finance but no Employee role**, while
Roletwo (bulk) had Employee + Finance. Cause (`AssignRolesDialog.tsx`): in the single dialog "untick = take
away", and someone without an account started with **nothing** ticked. So "Create account" + HR Admin gave HR
Admin only: no own profile, leave or HR assistant through the Employee role. Bulk keeps the Employee default for
a new account. Fix: the single dialog starts with **Employee ticked** for someone with no account and no roles.
Checked on a third proof employee: "Employee ticked at start: true", and the new account has Employee + HR Admin
(`p23-3e-roles-single-fixed-dialog.png`).

**Agency delete vs deactivate.** Data:
- "Proof Empty Agency (P23)": nothing;
- "Proof History Agency (P23)": 2 candidates sent;
- "Proof OpenBGV Agency (P23)": 1 BGV case in progress.

Script: `frontend/scripts/p23_3e_agency_delete_shots.mjs`.

| Case | Dialog (quoted) | Result | Screenshot |
|---|---|---|---|
| Open BGV case | "Reassign or cancel these open BGV cases first (on the BGV page): Proof Open Case - In progress" | Deactivate is **disabled** | `p23-3e-agdel-list.png`, `-agdel-open-bgv-blocked.png` |
| No history | "This agency has no candidates, BGV cases or fees. It will be removed. This can't be undone." -> Delete | gone from the DB (`status=all` list no longer has it) | `p23-3e-agdel-empty-dialog.png`, `-agdel-empty-deleted.png` |
| With history | "This agency has 2 candidates and 0 BGV cases. It will be deactivated and hidden, history is kept. You can restore it from the Inactive filter." -> Deactivate | `active=false` | `p23-3e-agdel-history-dialog.png`, `-agdel-history-deactivated.png` |
| Status = Inactive, Restore | listed under Inactive; Restore | `active=true` | `p23-3e-agdel-inactive-filter.png`, `-agdel-restored.png` |

**Clean-up (done):** 3 employees, 3 accounts (+6 role assignments, 3 invite tokens), 7 emails, 3 agencies,
1 job, 3 candidates / applications, 2 submissions, 1 BGV case, 13 audit rows. Scan: nothing left. Back to 9
employees and the one real agency.

### 23.3f Letters + designed emails (22.6)

Made through the live app (proof API = committed code), not by a script that calls the renderer.
Script: `frontend/scripts/p23_3f_letters_shots.mjs`.

| What | How | Files in `docs/ui/letters/` |
|---|---|---|
| 6 letter PDFs: offer, joining, appointment, confirmation, relieving, experience | Settings > Onboarding & employees > Letters preview (`POST /ui/design/letters/{kind}/preview`), about 89 KB each | `<kind>-letter-live.pdf` |
| Letter "Send test to me" | mailpit: "Sample Offer letter from CTD Techs (test)" with `sample-offer-letter.pdf` attached | - |
| 3 designed emails: offer, welcome, exit letters | Settings > Communication > Email design: **Send test to me** pressed on screen (mailpit 14 -> 15), then the same endpoint for each email; shots of mailpit's HTML view at Gmail width (1000 px) and phone width (390 px) + the plain-text part | `<offer\|welcome\|exit-letters>-email-live-gmail.png`, `-phone.png`, `.txt` |

Subjects: "🎉 Junior AI Developer: your offer letter - please review and sign", "👋 Welcome to CTD Techs, Priya!",
"🙏 Your relieving and experience letters from CTD Techs". Each email has an HTML part and a plain-text part
(412 / 419 / 211 characters). Settings screens: `screens/p23-3f-email-design.png`, `-email-design-test-sent.png`,
`-letters-settings.png`. The 22.6a/b script-made samples (`*-sample.pdf`, `*-email-gmail.png`) are kept for
comparison.

**Bug found and fixed:** the sample offer letter was dated **02 November 2026** but said "Please sign this
letter by **14 October 2026**". Cause: the sample data in `ui_design_router.py` had fixed dates typed on 7 Oct
(sign-by 14 Oct, joining 3 Nov, last day 30 Sep). Now `sample_dates()` uses today's date:
- sign within 7 days;
- join on the Monday at least 3 weeks out;
- confirmation 6 months later;
- last working day = the end of last month.

Regenerated: "sign by 9 November 2026", joining "23 November 2026", relieving "31 October 2026". The experience
sample now says "We wish Arun every success" (it had assumed "him"). New `tests/test_design_sample_dates.py`:
2 passed.

**Clean-up (done):** 10 test-email rows in the sent-message log + 10 audit rows of the temp admin.
