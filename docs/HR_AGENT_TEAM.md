# HR agent team (LangGraph) - hiring to exit

The HR assistant no longer does HR work on its own. It is the **supervisor** of a team of nine
agents, and the agents talk to each other along the employee journey.

```
Person -> HR assistant (supervisor) --task--> any agent; every agent reports back (result)

  Job -> Screening -> Interview -> Salary -> Documents & BGV -> Offer -> Onboarding
  (each agent can hand the next step forward, or one step back)

  Exit agent (resignations, clearance, letters)      HR policy agent (handbook answers)
```

| Agent | Feature code | Reads / routine actions | Proposes (approval card -> reviewer permission) | Hands to |
|---|---|---|---|---|
| HR assistant | `agents.hr_assistant` | - (delegates) | - | all nine |
| Job | `agents.job` | list_jobs, create_job_draft (draft only), draft_job_description | - | Screening |
| Screening | `agents.screening` | list_jobs, list_applications, screen_new_applications, top_candidates | propose_shortlist -> `recruitment.shortlisting.edit` | Interview, Job |
| Interview | `agents.scheduling` | waiting_for_interview, scheduling_problems, interview_status, start_interview_scheduling (shortlisted only), resend_interview_invite, find_candidate | - (interviewers give feedback/decision on the Interviews screen) | Salary, Screening |
| Salary | `agents.salary` | salary_queue, run_salary_check, send_salary_form, find_candidate | propose_salary_decision (approve / counter / reject) -> `recruitment.salary.edit` | Documents & BGV, Interview |
| Documents & BGV | `agents.bgv` | bgv_queue, documents_status (AI flags + cross-check), send_documents_form, list_bgv_vendors, find_candidate | propose_documents_approval, propose_vendor_assignment, propose_bgv_decision -> `recruitment.bgv.edit` | Offer, Salary |
| Offer | `agents.offer` | offer_queue, offer_status, resend_offer, find_candidate | propose_joining_dates -> `recruitment.offer.edit` | Onboarding, Documents & BGV |
| Onboarding | `agents.onboarding` | onboarding_board, pending_employee_cards | propose_mark_joined -> `onboarding.preboarding.approve` | Offer, HR policy |
| Exit | `agents.exit` | open_exits, exit_detail (blockers), send_exit_interview_reminder | propose_exit_letters -> `separation.case.approve` | HR policy |
| HR policy | `agents.policy` | search_handbook (answers only from passages, with source) | - | - |

## How it works
- **Code**: `backend/app/hr_agents/` -- `agents.py` (who exists, instructions, hand-offs), `tools.py`
  (Job / Screening / Interview tools + the tool runner), `tools_e2e.py` (Interview extras, Salary,
  Documents & BGV, Offer, Onboarding, Exit, Policy), `graph.py` (the LangGraph graph), `routing.py`
  (which questions go to the team), `approvals.py` (what happens when HR approves a card).
- **Hand-offs**: an agent calls `transfer_to_<agent>` with a task; the graph moves to that node
  (`Command(goto=...)`). Every hand-off and report is an A2A-style message
  `{id, from, to, kind: task|result, text, data, at}`, saved on the assistant's reply
  (`copilot_messages.tool_calls_json`) and shown in the assistant panel under "Agent team".
- **Which questions**: an HR task (an action word + an HR object from job to exit, e.g. "shortlist the
  top 3 for ...", "check Priya's salary and send the documents form", "propose joining dates for Arun",
  "what blocks Ravi's relieving letter") goes to the team -- only for people with at least one HR
  permission (`routing.HR_PERMISSIONS`). Questions about the asker's own data ("my offer", "my leave"),
  plain policy questions and drafts keep the existing assistant path. English only for now.
- **People decide**: agents never publish, shortlist, approve salary, approve documents, send data
  to a BGV vendor, decide BGV, send joining dates, record a joining or issue exit letters. Each of
  these is an approval card in My approvals; approving it runs the **same service function the
  screen uses** (`salary_auto.decide`, `joining_docs.approve`, `bgv.vendors.assign`,
  `bgv_decision.decide`, `joining_dates.propose`, `joiner_actions.mark_joined`,
  `exit_checklist.generate_letters`). If the service refuses (state changed meanwhile, budget short,
  ...), the card stays pending and HR sees the reason. Routine follow-ups the screens offer as one
  click (salary/documents form or reminder, slot emails again, unsigned offer again, exit-interview
  reminder) run directly. Interview feedback and resignation approval are never done by agents.
- **Permissions**: every tool checks the asking person's permission; without it the agent explains
  who can do it. The card's reviewer permission decides who can approve it.
- **AI**: every model call goes through the AI gateway, so the provider switch (Anthropic now; Amazon
  Bedrock after AWS access), usage limits and cost per feature (`agents.*`) apply. Limits per request:
  6 agent turns, 6 model calls per turn.
- **Switches**: `copilot.agents.enabled` (Settings > HR Copilot) turns the team off; each agent can be
  switched off in Settings > Integrations > AI Intelligence > Features (the others then report it as
  not available).

## Adding an agent
1. Write its tools in `tools_e2e.py` (permission-checked, reuse the app's own services; anything that
   decides for a person = `_card(...)` + an `@applier` in `approvals.py`).
2. Add an `AgentSpec` in `agents.py` (purpose, instructions, tools, `hands_off_to`), add it to
   `ALL_SPECIALISTS` and to its neighbours' `hands_off_to`.
3. Add `agents.<name>` to `AI_FEATURES` in `platform/ai/governance.py`.
4. Add its display names to `frontend/src/i18n/pages/shell.ts` (`assistant.agents.name.<name>`, EN/HI/TA).
5. Add a scripted-model test in `tests/test_hr_agents.py`.
