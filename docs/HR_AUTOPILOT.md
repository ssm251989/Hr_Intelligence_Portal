# HR Autopilot - automatic agents (Part 26)

The agent team (docs/HR_AGENT_TEAM.md) works when someone asks the HR assistant. **Autopilot agents
work on their own**: they wake up when something happens, and on a schedule, do the routine work,
decide only where the company's rules allow it, and send everything else to My approvals.

Owner decision (2026-11-02): **auto within rules** -- routine work is automatic; every decision
about a person needs a company rule that is OFF by default.

```
 audit log (application_created, salary_checked, documents_submitted, bgv_requested,
            bgv_vendor_report_received, bgv_passed ...)  --every minute-->  runner.run_events
 schedule:  hourly  -> watchdog, joining day, exit letters, morning briefing
            daily   -> sourcing
                         |
     Screening -> (shortlist rule) -> Salary -> Documents -> BGV vendor -> BGV report (AI) -> Offer dates
                         |                 \__ inside a rule: decided        \__ otherwise: approval card
     Onboarding (joining day) . Exit (letters) . Watchdog (stuck items) . Briefing (8-9 am)
                         |
              agent_activity  ->  Autopilot page (/autopilot)
```

## Agents

| Agent | Wakes on | Routine (always, when on) | Decides only with rule (default off) | Otherwise |
|---|---|---|---|---|
| Screening | application_created, ai_screening_scored; hourly for missed ones | screens new applications | `shortlist_min_score` -> shortlists with the existing undo window | - |
| Sourcing | daily | finds open jobs with < `sourcing.min_strong` strong candidates | - | talent-pool proposal card |
| Salary | salary_checked, salary_form_answered | - (in-band approvals are the existing salary rule) | `salary_max_over_band_pct` -> approve expected CTC if budget allows | card: counter at band max |
| Documents | document_uploaded, documents_submitted | - | `documents_auto_approve` (all in, no AI flag, name/DOB match) -> approve, BGV starts | card with the flags |
| BGV | bgv_requested, bgv_vendor_report_received | AI reads the vendor's report (feature `agents.bgv_reader`) | `bgv_auto_assign_vendor` -> fastest vendor; `bgv_auto_pass_clear_report` -> passed when AI reads "clear" >= 90% | vendor card / BGV result card with the AI reading |
| Offer | bgv_passed, bgv_discrepancy | 3 working-day dates (lead time or notice period) | `joining_dates_auto` -> emails the dates | card with the dates |
| Onboarding | hourly | - | `mark_joined_when_ready` (joining date reached, pre-boarding 100%) -> joined, employee record | "confirm joined" card |
| Exit | hourly | tells HR when letters are blocked 3+ days after the LWD | `exit_letters_auto` -> relieving + experience letters | card |
| Watchdog | hourly | unscreened applications, screened not reviewed, interview scheduling problems, salary waiting, documents waiting / missing, BGV overdue, joining date not chosen, unsigned offer (re-sent once, then escalated), approval cards waiting | - | in-app message to the job owner / approvers / admins, once a day per item |
| Briefing | hourly (sends at `briefing.hour`, company time zone) | each HR user: their approval cards, what autopilot decided / flagged, interviews today, joiners and leavers this week (AI-written with `agents.briefing`, plain list otherwise); bell + optional email | - | - |

## Safety
- Master switch `autopilot.enabled` is **off** by default; each agent has its own switch; every rule is off / 0.
- Decisions run through the **same service functions as the screens** (salary_auto.decide, joining_docs.approve,
  bgv.vendors.assign, bgv_decision.decide, joining_dates.propose, joiner_actions.mark_joined,
  exit_checklist.generate_letters, autoshortlist.maybe_auto_shortlist). A service refusal (budget, state) -> card instead.
- Interview feedback/decisions, resignation approval, rejections and job publishing are never automatic.
- Idempotent: every handler re-reads the current state; the watchdog nudges once per item per 24 h.
- Event cursor per company (`autopilot_state`), 20 s safety lag, first run starts from "now" (no history replay).
- Every step is in `agent_activity` with trigger, event, outcome and the rule that allowed it.
- Module-aware: an agent whose module is not active for the company does nothing.

## Code
`backend/app/hr_agents/autopilot/` -- `core.py` (switches, rules, record, notify, cards, state), `hiring.py`,
`people.py`, `watchdog.py`, `briefing.py`, `runner.py` (EVENTS map, run_events / run_hourly / run_daily, RUN_NOW).
`backend/app/hr_agents/autopilot_router.py` (`/api/v1/ui/autopilot/*`), `backend/app/models/autopilot.py`,
migration `c6a8e2f4b1d3_part26_autopilot.py`, jobs in `platform/jobs/scheduled.py` (autopilot_events 60 s,
autopilot_hourly, autopilot_daily), page `frontend/src/pages/autopilot/AutopilotPage.tsx`, strings `i18n/pages/autopilot.ts`.

## Adding an automatic agent
1. Handler `fn(db, tenant, application, run)` (event) or `fn(db, tenant, run)` (sweep) in the right module, using
   `enabled()`, `rule()`, `record()`, `card()`; decide only inside a rule.
2. Event: add the audit action to `runner.EVENTS`. Sweep: call it from `run_hourly` / `run_daily`.
3. New agent name: `AUTOPILOT_AGENTS` (model + migration check constraint), `autopilot.<agent>.enabled` setting + help,
   page strings (EN/HI/TA). New rule: setting + help + `autopilot_router.RULES` + page string.
4. Test in `tests/test_autopilot.py`.
