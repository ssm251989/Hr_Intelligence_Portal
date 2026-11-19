# PART 29 - HR automation runs on its agents ("agent prepares, HR approves") - check (2026-11-18)

## 29.1 Check

| Check | Result |
|---|---|
| `alembic heads` | one head **e1f4a7c2d9b8**; `alembic upgrade head` (via `hrctl.migrate --all-tenants --control-plane`) applied c6a8e2f4b1d3 + e1f4a7c2d9b8 |
| `pytest tests/test_agents_run_flow.py tests/test_autopilot.py tests/test_hr_agents.py` | first run: 1 failed - `test_screened_candidate_above_the_threshold_gets_a_shortlist_card...`: no card, because this dev company saved `recruitment.shortlisting.auto_shortlist = true` (2026-09-27) and the agent correctly leaves such jobs to their own auto-shortlist. The test now sets its jobs to shortlist by hand. Then all pass (49 -> 69 with this part's new tests). |
| `pytest -q` | before the fixes: **165 failed / 1402 passed**; `3b4b8bc` (before Parts 27-29, worktree, same DB): **171 failed / 1366 passed**; no failure that is not also on 3b4b8bc. After all fixes: see build_log. |
| Frontend | i18n / `tsc` / `vite build` OK |

## 29.2 Existing company

This dev company had no saved `autopilot.enabled`, so the new default (on) applied as soon as the API started; its first
hourly run prepared "Confirm joined" cards, one for a real joiner (gkishore1433@gmail.com, joining 2026-11-09) - left
for HR. Every agent switch is on; every rule is off / 0. `recruitment.salary.auto_approve_hike_pct` was **not**
changed (owner question below).

## 29.3 End to end (real model; proof stack as in FIXES_26.md)

| # | Step | Result | OK |
|---|---|---|---|
| a | Careers apply -> Screening agent | strong resume: "Shortlist Kiran Das" card within ~80 s; weak (2.5): no card, stays Screened | yes |
| b | Approve -> interview times | interviewer email in mailpit; Journey: "was screened: score 98" (after fix 1), "shortlist prepared", "Interview times sent" | yes (fix 1) |
| c | Job set to schedule by hand | HR shortlists by hand -> "Send interview times to Ravi" card -> approve -> interviewer email | yes |
| d | Scorecard "Move forward" -> salary -> card | **Scorecard step not run** (needs a booked interview: interviewer + candidate slot confirmation). Salary form -> above band -> Salary agent counter card -> approve: checked in FIXES_26 c. | partly |
| e | Documents -> BGV -> offer -> signed -> welcome | Chitra: documents card -> approve -> BGV sent to the fastest vendor -> vendor report -> AI reading "clear 97 %" -> BGV passed -> "Offer joining dates" card -> approve -> candidate picks 18 Dec -> offer sent -> signed in-app -> HR emailed, welcome email; all on her Journey | yes |
| f | Joining day card -> approve -> employee | 25.2 h (CTD-0026) and 26.2 f (rule: CTD-0028) | yes |
| g | Employee resigns (own login) -> card -> Change and approve | Proof Jaya Kumar resigned with 8 Dec (30 days' notice). Exit agent Run now -> "Approve ... last working day 2026-12-18" with the note "asked for 2026-12-08, 10 day(s) short ...". Change and approve: 11 Dec, 7 days waived -> status clearance, 7 checklist items | yes |
| h | Letters card -> approve | clearance done -> "Issue relieving and experience letters to Proof Indu Varma" -> approve -> both letters issued | yes |
| i | Ask the agents: "who is waiting for a salary decision?" | first: old assistant path ("I couldn't find this in your company's policies") -> fix 2 -> Salary agent: "Esha Gupta and Bharat Rao ... above the band ..." (`p29-i-ask-agents.png`) | yes (fix 2) |
| j | Decline a card | 25.2: rejected joining-dates card -> no change, no email | yes |
| k | Master off / on | 26.2 j: off -> no card for a new applicant; activity kept. On again -> the off-time application was replayed (card) -> fixed (FIXES_26 fix 8): events are not replayed | yes (fix) |

### Fixes (each with a test)

1. **The Journey had no "screened" step** - the app screens on apply by itself, and only the agent's own screening
   wrote a line. `ai_screening_scored` is now a timeline step ("<name> was screened: score N") and still goes to the
   shortlist rule; the agent's own duplicate line is gone.
2. **"Who is waiting for a salary decision?" missed the agent team** (no action word). Routing now treats "who is
   waiting / waiting for / stuck / overdue" as a task; "my ..." questions stay self-service.

Plus the Part 26 fixes (FIXES_26.md), several of which sit on this flow (approving cards after a restart, BGV vendor,
double timeline lines).

## 29.4 Still to build - owner to confirm the order

- Job agent on the timeline (draft JD on "New job", publish card)
- Interview outcome summary card for the hiring manager (the decision stays with people)
- Public APIs and webhooks for the agents (Phase 1 of the blueprint, 25 Dec)

## 29.4 Owner decisions (2026-11-19) and the closed card status

Decisions: Autopilot stays **on** for this company (the owner handles the real "Confirm joined" card); every salary is a
card - `recruitment.salary.auto_approve_hike_pct` 20 -> **0** through the settings API the Settings screen uses (history
version 1, by the check admin); 29.4 order: **Job agent on the timeline -> public APIs + webhooks (Phase 1, 25 Dec) ->
interview-outcome card**; leftover cards are closed automatically (below).

**Closed cards** (migration `b4d7e9a1c3f5`: `agent_suggestions.status` may be `closed`, new column `closed_reason`).
`hr_agents/autopilot/leftovers.py` closes a pending card when its step is no longer waiting:

| Card | Closed when |
|---|---|
| Shortlist | none of its candidates is still Screened (an assistant card can hold several) |
| Send interview times | the candidate left hr_selected, or `interview_scheduling_started` was logged after the card |
| Salary decision | the candidate left salary_above_band |
| Documents | the candidate left salary_approved, or `documents_approved` was logged |
| BGV vendor / BGV result | the candidate left bgv_requested / bgv_pending (vendor: or `bgv_vendor_assigned` was logged) |
| Joining dates | the candidate left bgv_cleared, or `joining_dates_proposed` was logged |
| Confirm joined | the joiner is joined / revoked / declined / no show / exited |
| Resignation | the resignation is no longer submitted (approved on the Exits screen, withdrawn, ...) |
| Exit letters | both letters are issued |

The reason names who did the step when the log shows it ("already done by an Autopilot rule" / "by hr@..."); the agent
timeline gets a "Closed the card ..." line. Nothing is applied and nothing is sent; approving a closed card answers
"this card was closed - nothing to decide". It runs after every events batch that had events and at the end of every
hourly run. 7 tests (`tests/test_agent_cards_closed.py`).

**Real email can no longer leave from tests:** `tests/conftest.py` sets `DEV_MAIL_CAPTURE=127.0.0.1:1025` for every
test (only the two fake-SMTP files turn it off), and `platform_mail.send`'s own-SMTP path now honours the capture like
the HR mailbox and connector paths already did. The local `backend/.env` carries the capture too (not committed).
