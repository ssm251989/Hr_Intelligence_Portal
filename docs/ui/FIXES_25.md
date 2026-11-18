# PART 25 - HR agent team: install, tests, real-model check (2026-11-18)

Branch `KG-Development` (the agent code came in with `b32e368` / `3b4b8bc`; this part checks it and fixes what the real model showed).

## 25.1 Install + tests

| Check | Result |
|---|---|
| `pip install langgraph` | already installed: **langgraph 1.2.20** (langgraph-checkpoint 4.3.1, prebuilt 1.1.1, sdk 0.4.14) |
| First test run | `ModuleNotFoundError: No module named 'psycopg'` - SQLAlchemy **2.1.8** (installed 2026-11-10, unpinned) makes `postgresql://` mean psycopg 3; this venv has psycopg2. Fixed in the local `backend/.env` only (`postgresql+psycopg2://`, the URL form Part 27 chose; `.env` is not committed). |
| `test_hr_agents.py` | 24 passed (31 after this part's new tests) |
| `test_intelligence.py` + `test_llm_gateway_routing.py` | 3 failed: `test_budget_cutoff`, `test_copilot_uncited_answer_is_not_shown`, `test_copilot_action_creates_draft_not_submission`. The **same 3 fail on `9d9b4eb`** (the commit before the agent code, separate worktree, same DB) - none caused by Part 25. (The doc expected 10 known failures; 7 of those pass today.) |
| Frontend | `npx tsc -p tsconfig.app.json` exit 0; `npm run build` OK (chunk-size + lottie `eval` warnings only) |

## 25.2 Real model (provider anthropic)

Proof stack: mailpit (fresh `mailpit-p25.db`), API :8010 from `backend/.venv` with `DEV_MAIL_CAPTURE=127.0.0.1:1025`
(every email to mailpit), web :5174, temporary admin `proof.admin.p23@example.com` (left from Part 23; role HR Admin).
Autopilot switched **off** during 25.2 so its hourly cards would not mix with the assistant's.
Data: one fixture script ("Proof ... (P25)", `@example.com`): job *Proof - Data Engineer (P25)* with 3 screened
candidates (88 / 79 / 62) and an interviewer pool; job *Proof - Analytics Engineer (P25)* (band 8-12 L) with Priya
(interview_selected, expects 14 L), Arjun (salary_approved, documents uploaded), Kavya (bgv_pending), Rahul
(bgv_cleared, 30 days notice), Sameer (interview_selected, expects 13.5 L); BGV vendor *Proof Verify Co (P25)*;
joiner Deepa (joining today); leaver Sanjay (LWD yesterday, clearance done). Every answer below is the real model's.
Screens: `docs/ui/screens/p25-<item>.png` (the HR assistant with the "Agent team" panel opened).

| # | Question | Agents (hand-offs) | Result | OK |
|---|---|---|---|---|
| a | Create a job for a Senior Python Developer in Chennai, 4 to 7 years, Django and AWS | Job | Draft + JD, status *ready_for_publishing*, nothing published | yes |
| b | Create a job for a QA engineer in Bengaluru and screen any applicants | Job -> **Screening** (agent-to-agent) | Draft + JD; Screening agent: no applicants yet (not published) | yes (wording fixed, see 2) |
| c | Shortlist the top 2 candidates for Proof - Data Engineer (P25) | Screening | ONE card "Shortlist 2 ..." (Nisha 88, Vivek 79). Approve -> both *hr_selected*, Leela stays *screened*; mailpit: 2 x "Interview scheduling for Proof - Data Engineer (P25)" to the interviewer | yes |
| d | Who is waiting for an interview ...? Re-send the slots to Nisha Kapoor | Interview | Nisha + Vivek waiting; invite re-sent (mailpit +1) | yes |
| e | Check Proof Priya Raman's salary | Salary | 27.3 % hike (> 20 % cap), above band -> card "Salary **counter** ... 12 L (band max)". Approve -> mailpit "our salary offer" to Priya, status stays *salary_above_band* until she answers (same `salary_auto.decide` as the Salary screen). The "approve -> documents form" path is covered in 26.2 c. | yes |
| f | What's pending on Arjun's documents? Approve them if all are fine | Documents & BGV | All required received, green; relieving letter optional -> card. Approve -> *bgv_requested*. Then "Send Arjun's BGV to Proof Verify Co (P25)" -> vendor card -> approve -> mailpit "Background check request: Proof Arjun Mehta" to the vendor | yes (after fixes 3, 5) |
| g | BGV for Kavya came back clean, and offer joining dates | Documents & BGV -> **Offer** | Card "BGV passed"; Offer agent holds the dates until HR approves it. Approve -> *bgv_cleared*; "Offer joining dates to Kavya" -> card -> approve -> mailpit "background verification successful - choose your joining date" | yes (after fixes 3, 6) |
| h | Who joins today? / Mark Deepa Menon as joined | Onboarding | "Deepa is scheduled to join today, 2026-11-18" (+ flags a real joiner whose date passed). Card "Confirm ... joined" -> approve -> case *joined*, employee **CTD-0026** active | yes (after fixes 3, 4) |
| i | What blocks Sanjay Kumar's relieving letter? | Exit | Nothing blocks; exit-interview reminder sent (routine); the letters card already existed (no duplicate) | yes |
| j | Take Sameer Khan from salary through to the offer | Salary | One card (salary counter 11 L); the team stops there and says why - the next steps wait for HR's decision. Nothing decided | yes |
| k | (a) by a **Manager** (no `recruitment.job.create`) | Job | "could not create the draft because this account lacks ... recruitment.job.create"; no job created | yes |
| k | (c) by an **employee** (no HR permission) | - | normal assistant path, no agents | yes |
| l | What is the notice period for a senior employee? | - | "90 days after confirmation [1][4]", source CTD Techs Employee Handbook | yes |
| l | Show my offer letter | - | self-service path, not the team | yes |
| m | `copilot.agents.enabled` off -> (a) | - | old path (no team); switched back | yes |
| m | `agents.salary` off -> "Check Sameer Khan's salary" | - | "The salary agent is currently switched off ..." | yes |
| - | Reject a card ("Offer joining dates to Rahul") | - | status unchanged (*bgv_cleared*), no email | yes |
| n | AI Intelligence usage | - | By feature: agents.hr_assistant INR 17.50 (36 calls), bgv 9.31, offer 5.08, salary 4.72, onboarding 4.12, screening 3.73, job 3.46, exit 1.80, scheduling 1.79; module "agents" INR 51.51 / 99 requests (`p25-n-usage-per-agent.png`) | yes |

### What the real model showed, and the fixes (cause quoted first)

1. **Answers showed raw Markdown** (`**Nisha Kapoor**`) and internal ids in the chat panel (`p25-c-shortlist.png`).
   Cause: the HR assistant (supervisor) instructions never asked for plain text (the specialists' `_COMMON` does), and
   the widget shows text as it is. Fix (`agents.py`): plain text, no Markdown, no internal ids.
2. **"Publish the job in My approvals"** (b) - there is no card for publishing. Same instruction: send people to My
   approvals only when an approval card was created; other steps are done on their own screens.
3. **g, h, h, j went to the old assistant path** ("I couldn't find this in your company's policies"). Cause:
   `routing.looks_like_task` needs an action word AND a hiring word; "came back ... offer joining dates", "Who joins
   today?", "Mark ... as joined", "Take ... from salary through to the offer" each missed one. Fix (`routing.py`):
   actions `take`, `came back`, `offer (joining) dates`; objects `joins`, `joined`. "offer" alone stays an object only,
   so "What is an offer letter?" keeps the handbook path. 6 new routing tests.
4. **"Who joins today?" -> "Nobody is joining exactly today"** for a joiner due 2026-11-18. Cause: no agent was told
   today's date (`graph._call` sends only the instructions). Fix (`graph.py`): every agent's system prompt ends with
   "Today is <weekday> <date>" (the same `date.today()` the tools check against). New test (fails without the fix).
5. **Documents: optional relieving letter reported as "missing".** Cause: `documents_status` rows had no `required`
   flag (the service's `missing` list already ignores optional ones). Fix (`tools_e2e.py`): each row says `required`.
   (The first run correctly refused: this company's saved list makes the experience letter required - the fixture
   was missing it.)
6. **Joining dates 12 days out for a candidate with a 30-day notice period.** Cause: the Offer agent's instructions
   said "within the notice period" and its tools never showed the notice period. Fix: `offer_status` / `offer_queue`
   return `notice_period_days` and `suggested_dates` from Autopilot's own `joining_dates_for` (notice period or lead
   time, whichever is later; working days), and the instructions say to use them unless the person asked for other
   dates. Re-run for Rahul: 18 / 21 / 23 Dec. New test.

Nothing was loosened: every decision is still a card; the people-decide rules are unchanged.

Also seen: Autopilot is **on by default** (Part 29) and this company had no saved value, so when the API started its
first hourly run prepared "Confirm joined" cards - including one for a real joiner (gkishore1433@gmail.com, joining
date 2026-11-09). Nothing was decided; that card was left for HR.

## 25.3 Clean-up

Dry run, then delete (scan of every uuid column + agent card / timeline / copilot JSON): 8 applications,
8 candidates, 4 jobs (2 proof + the 2 drafts from a/b), 6 candidate documents (+ files) and 4 BGV copies (+ files),
1 BGV assignment, 1 vendor, 1 interviewer pool, 2 employees + 1 employment record, 1 preboarding case, 1 separation
+ 7 clearance items, 11 agent cards, 2 timeline rows, 26 conversations / 52 messages / 7 drafts, 18 emails,
34 audit rows, 2 negotiation / 2 action tokens, the temporary Manager user. Scan after: 0 rows point at a proof id.
Kept on purpose: AI usage + decision-log rows (real spend). The `copilot.agents.enabled` / `ai.features.disabled`
overrides from (m) deleted (there were none before).
