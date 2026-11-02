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
