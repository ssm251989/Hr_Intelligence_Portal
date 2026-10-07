# PART 22 - proof

## 22.1 BUG: HR assistant not working (merged with 21.6)

### Real cause (quoted from the live DB and code, 2026-10-07)

The owner's questions (`copilot_messages`, user kg@ctdtechs.com):

```
2026-10-06 17:38:40  'Eg1'
2026-10-07 09:49:54  'Eg1'
```

**Cause 1 - "Eg1" is not something the owner typed.** It is an example button's text. `CopilotWidget.tsx`
has `const EXAMPLES = ["assistant.eg1", "assistant.eg2", "assistant.eg3"]`, but those keys were missing from
`i18n/pages/shell.ts` (grep: no `assistant.eg1` anywhere). So the missing key was shown as "Eg1" on the button,
and clicking it sent "Eg1" as the question.

**Cause 2 - "Eg1" was treated as a policy question.** Retrieval found nothing (`confidence 0.0`), so the
assistant always handed over to a ticket:

```
assistant reply  2026-10-07 09:49:54  "I couldn't find a reliable answer ... prepared a helpdesk ticket"  confidence 0.0  [{"handover": true}]
copilot_drafts   2026-10-07 09:49:54  raise_ticket  status=draft  {"subject": "Eg1", "description": "Eg1", "category_code": null}
```

**Cause 3 - "Something went wrong." on Raise ticket = an empty category.** The ticket draft takes its category
from the setting `copilot.handover_category`, which was `''` (registered default ""). So `category_code: null`,
and confirming hit

```python
# app/copilot/service.py confirm_draft
if not payload.get("category_code"):
    raise CopilotError("choose a ticket category before confirming")   # -> HTTP 400
```

The widget threw that reason away: `.catch(() => setTurn(index, { draft: { state: "failed", text: t("assistant.failed") } }))`,
and `assistant.failed` = "Something went wrong.". Both drafts are still `status=draft` (the confirm never got past the check).

**Cause 4 - even with a category, the ticket would go nowhere.** Helpdesk is hidden for ctd-techs:
`enabled_modules = ['analytics','assets','copilot','employees','home','onboarding','recruitment','separation','settings']`
(no `helpdesk`). There are 5 active ticket categories (`it, leave, other, payroll, policy`) and 0 tickets.

**Also found:**
- The handbook PDF's search passages had wrong section names. These come from table cells and the page header:
  `headings: [None, 'Page 1', '14. Frequently asked questions', ..., '(EL)', '26 weeks', '5 working days', '1 January', 'Christmas']`.
  So the sources could never read "Employee Handbook - 6. Notice period".
- Settings > Data & privacy > Sample files calls `GET /api/v1/samples`. No such endpoint existed, so the page always said
  "Sample files aren't available yet."
- There were no tools for data questions about jobs or candidates.

### Fix
- **Example questions:** the example buttons now ask real questions in en/hi/ta.
- **Unclear questions** ("Eg1", "hi", one meaningless word) are caught by `is_unclear()` before anything else. The reply is
  "I'm not sure what you mean - try asking about leave, notice period, salary dates, travel, jobs or candidates", with 4
  clickable suggestion chips. No ticket is offered.
- **Hand-over:**
  - Helpdesk **on**: a ticket draft whose category is chosen automatically (the setting if valid, else general/other/policy,
    else the first active category). The category shows as an editable dropdown on the card.
  - Helpdesk **off**: "Hand over to HR". Confirming creates an HR to-do (My approvals, card "Question from the HR assistant",
    with Reply + Mark done buttons) and emails the HR mailbox (template `copilot.hr_handover`).
  - New draft action `hr_handover` (migration d6cf5a6b7c8d).
- **Errors:** a failed confirm now shows the server's reason instead of "Something went wrong.".
- **Sources:** PDF section headings use the numbered sections only when the document has them, and the repeated page
  header/footer is dropped. The live handbook was re-indexed (33 -> 17 passages, audit `policy.reindexed`). Sources read
  "CTD Techs Employee Handbook - 6. Notice period and resignation".
- **Data questions:** new tools `open_jobs` (needs recruitment.job.view) and `waiting_for_interview` (needs
  recruitment.application.view). They answer from live data and use the asker's own permissions.
- **Sample files:** `GET /api/v1/samples` + `/api/v1/samples/{key}`. "HR policy handbook" =
  docs/samples/CTD_Techs_Employee_Handbook_SAMPLE.pdf (shipped as app/platform/samples/hr_policy_handbook.pdf).

### Handbook indexed
`knowledge_documents`: "CTD Techs Employee Handbook", status `active` (shown as **Ready**), uploaded by the owner 2026-10-07 10:04.

### Verification - answers (live handbook + live data, asked as kg@ctdtechs.com through CopilotService; dry run, rolled back)

| Question | Expected | Answer | Source |
|---|---|---|---|
| How many casual leaves do I get? | 12, max 3 at a time | "12 casual leaves a year, with a maximum of 3 days at a time [1]." | Employee Handbook - 14. Frequently asked questions |
| What is the notice period for a senior employee? | 90 days | "The notice period for Senior, Lead and Manager (L5 and above) is 90 days after confirmation [1][4]." | 6. Notice period and resignation; 14. FAQ |
| Can I work from home? | 2 days/week after confirmation | "Yes. After confirmation, employees may work from home up to 2 days a week, with the manager's approval ... During probation ... only in exceptional cases" | 4. Work from home; 14. FAQ |
| When is salary credited? | last working day | "Salary is credited to the employee's bank account on the last working day of every month [1][2]." | 14. FAQ; 7. Salary, payslips and reimbursements |
| Hotel limit for a junior employee in a metro city? | Rs 4,000/night | "Up to Rs 4,000 per night for a junior (L1-L4) employee in a metro city [1][2]." | 8. Travel policy; 14. FAQ |
| How long is probation? | 6 months | "Probation is 6 months, extendable once by up to 3 months [1][2]." | 14. FAQ; 5. Probation and confirmation |
| How many open jobs do we have? | live data | "There are currently **0 open jobs**." (live: job_roles = 2 closed, 0 open) | tool `open_jobs` |
| Which candidates are waiting for an interview? | live data | "No candidates are currently waiting for an interview." (live: 0 applications) | tool `waiting_for_interview` |
| Eg1 | clarification, no error | "I'm not sure what you mean - try asking about leave, notice period, salary dates, travel, jobs or candidates." + 4 chips, no draft | - |
| Do we get a gym membership allowance? (not in handbook) | not found + Hand over to HR | "I couldn't find this in your company's policies. You can hand your question over to HR ..." draft `hr_handover` | - |

Extra checks: "hi" gives the clarification. "leave" and "salary?" (one topic word) are answered from 2. Leave policy and 7. Salary.

**Still to prove on screen** (proof setup: mailpit + API :8010 + web :5174, stopped by the system for low memory on 2026-10-07):
screenshots of the widget (clarify chips, sources, Hand over to HR) and the HR to-do in My approvals, and the hand-over email in mailpit.
