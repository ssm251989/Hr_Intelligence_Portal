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

## 22.2 Candidate emails: "Not matched" -> "Closed"; smarter auto-link

**Tabs:** Needs action | Linked to a candidate | Closed.
- Closed = status `done`: HR pressed Mark done, or automatic mail (bounces / no-reply) that triage closes by itself.
- Unlinked mail stays in Needs action. It has a yellow **Not linked yet** chip, suggested candidates ("Link to <name>") and the Link-to-candidate picker.
- Old `?tab=not_matched` links open Needs action.

**Auto-link rules** (`app/hr_inbox/matching.py`, in order; the rule is saved on the email as `match_rule` and shown as a chip):
1. the sender's address = the candidate's email, or one of the extra addresses on the profile (`candidates.alt_emails`, new)
2. the sender name / subject / body (signature, quoted reply) contains "First Last" or "Last First". This ignores case, dots and extra spaces, and allows initials ("G. Kishore", "Kishore G").
3. a reply to an email the app sent. The SMTP sender now sets its own Message-ID and stores it on the outbound row; In-Reply-To / References are matched against it.

Exactly one candidate -> linked. Several -> not linked, and the candidates are kept as suggestions. The app never guesses between two.

**Manual link** has a new tick box, "Also remember <address> for this candidate" (on by default). It adds the address to `alt_emails` (audit `candidate_alt_email_added`), so the next email from it links by rule 1. Picking a suggestion remembers the address too.

**Examples** (dry run on temporary candidates, rolled back):

| Case | Email | Result |
|---|---|---|
| sender email | from PROOFA.R@example.com | linked: Proofa Ravikumar, rule `email` |
| extra email on profile | from meena.home@example.com (alt email of Meena Sundar) | linked: Meena Sundar, rule `alt_email` |
| "First Last" | sender name "Proofa Ravikumar", from someone@gmail.com | linked: Proofa Ravikumar, rule `name` |
| "Last First" | signature "Regards, Ravikumar Proofa", from x123@yahoo.com | linked: Proofa Ravikumar, rule `name` |
| initials | signature "M. Sundar" / subject "Re: BGV - Sundar M" | linked: Meena Sundar, rule `name` |
| ambiguous | "Regards, Arun Prakash" with candidates "Arun Prakash" and "Prakash Arun" | **not linked**; suggestions: both |
| no match | noreply@bank.com "Your statement" | not linked, no suggestions |

**One-time re-match on live data** (`rematch_unmatched`, audit `candidate_emails_rematched`):
`{'checked': 68, 'linked': 0, 'ambiguous': 0}`. All 68 stored emails are `mailer-daemon@googlemail.com` "Delivery Status Notification (Failure)",
already `status=done, topic=automated`, so they now sit in **Closed**. HR can run it again: `POST /api/v1/ui/candidate-emails/rematch`.

Linked emails still appear on the candidate timeline (`inbound_email_received` / `inbound_email_linked` audit entries).

**Still to prove on screen:** screenshots of the three tabs, the Not-linked chip with suggestions, and the remember-address tick box (proof setup stopped for low memory).

## 22.3 Candidate emails highlighted in HR "My approvals"

- Every candidate email in **Needs action** is also a card in My approvals (`inbox.candidate_email_items`, for the roles that see Candidate emails: recruiter, hiring manager, admin). Each card shows:
  - a coloured left border with a light blue background, the envelope emoji and a **Candidate email** chip ("Not linked yet" when unlinked);
  - the candidate (or sender), the job, the one-line summary and the received time;
  - buttons **Open**, **Reply**, **Link to candidate** (only when unlinked) and **Mark done**.
- **Unread is bold.** New column `hr_inbound_emails.read_at`/`read_by` (migration f8e17c8d9eaf). It is set the first time HR opens the email's thread; emails already done count as read.
- **One flag, two places:** Mark done in My approvals and on Candidate emails set the same `status=done`. Both pages fire an `approvals-changed` event so the badge refreshes straight away.
- **Badge:** new `GET /api/v1/inbox/count` (workflow approvals + every My approvals item, candidate emails included). The sidebar shows the number next to My approvals (a dot on the icon when collapsed), refreshed every minute and on focus.
  Live check for kg@ctdtechs.com: `{'total': 5, 'candidate_emails': 0, 'unread_emails': 0}`, which is 5 to-dos (position open again + 4 interviewer link to-dos) and 0 candidate emails needing action (all 68 are closed bounces).
- **Deep link:** Open/Reply/Link go to `/candidate-emails?email=<id>` (`&reply=1` opens the reply box, `&link=1` scrolls to the link picker).

**Still to prove on screen:** a My approvals screenshot with a highlighted (unread + read) candidate email. Needs a proof email in the proof setup.

## 22.4 Employees: "Assign roles"

- **Where:** the Employees list has a toolbar button **Assign roles** (works on the ticked rows) and a bulk-bar button "Assign roles (n)". Each row's "..." menu also has **Assign roles**.
- **Who sees it:** only people with `iam.role_assignments.configure`, which is HR Admin and Super Admin by default. This is the spec's "users.manage_roles"; the permission registry only allows the fixed actions, so the existing permission is used.
- **Dialog:** a checkbox for each role with a one-line description of what it can see and do. The roles are Employee, Interviewer, Hiring manager, Recruiter, HR (the HRBP template), HR Admin, Finance, IT, and Admin & facilities, plus the company's custom roles (live: Plant HR, Shift supervisor panel, Store manager, Technical panel).
  - **Finance, IT and Admin & facilities** are new system role templates.
  - **One employee:** their current roles are pre-ticked; you tick exactly what they should have.
  - **Many employees:** tick = give to all, untick = take from all, dash (mixed) = leave as it is.
  - **Interviewer:** when it is being given, the dialog asks for skills and interviewer pools (`interviewers.make_interviewer`). Removing it also takes them out of the pools.
  - **Other roles:** roles not in the list (Super Admin, Manager, Auditor...) are shown read-only and never changed.
- **No app account:** the dialog lists who has none and offers **Create account and send invite** (ticked by default, `accounts.send_invite`).
- **Last HR Admin guard:** removing HR Admin is refused when nobody else would hold HR Admin or Super Admin, including when you remove it from yourself.
- **Takes effect:** at the employee's next page load (permissions are read per request). The legacy `users.role` follows the ticked roles (admin / recruiter / hiring_manager / interviewer / employee), so older role-gated pages such as Candidate emails agree.
- **Email:** "Your access in {company} HR was updated" (template `access.updated`). Setting `employees.roles.notify_on_change`, default on.
- **Audit:** `roles_changed` with added, removed and legacy role.

**Dry run** (2 temporary employees, rolled back, emails stubbed):
```
state before: [('Proof Roleone', ['Employee']), ('Proof Roletwo', ['Employee'])]
single: set Employee+Recruiter+HR Admin -> result changed, added ['HR Admin','Recruiter'] | legacy role: admin
bulk (2): add Finance, remove Recruiter -> Proof Roleone changed +Finance -Recruiter; Proof Roletwo changed +Finance
last admin removes own HR Admin -> result last_admin: "This is the last HR Admin. Give HR Admin to someone else first."
state after: Proof Roleone ['Employee','HR Admin','Finance']; Proof Roletwo ['Employee','Finance']
```
**Still to prove on screen:** the single and bulk dialog screenshots and the mailpit email (proof setup stopped for low memory).

## 22.5 Agencies: Delete button

- **Where:** a "..." menu on each agency card shows **Delete agency**, and the agency profile has a **Delete agency** button. Inactive agencies also get **Restore** on the profile.
- **Who:** HR Admin only, via the new permission `recruitment.agency.delete`. HR Admin and Super Admin get it through "recruitment delete"; Recruiter does not.
- **`GET /{id}/delete-check`** works out what will happen:
  - **No history** (no submitted candidates, no BGV cases): confirm "It will be removed. This can't be undone.", then the agency, its job links and member links are deleted. Audit `agency_deleted`.
  - **History:** "This agency has 4 candidates and 2 BGV cases. It will be deactivated and hidden, history is kept." Then the agency is set `active=false` and is listed only under the new **Status: Inactive** filter. Audit `agency_deactivated`. **Restore** sets it active again (audit `agency_restored`).
  - **Open BGV assignments** (assigned / in progress / report received) are listed in the dialog, and Delete stays disabled. The API answers 409 "Reassign or cancel the open BGV cases first."
- **Portal logins:** the agency's logins (role `agency`) are switched off (`deactivated_at`) on delete or deactivate, and switched back on by Restore. The accounts are kept for the audit trail.
- **Agency list:** now has a Status filter (Active / Inactive / All). It defaults to **Active**, so the live paused "Bright talent partners" is under Inactive.

**Dry run** (temporary agencies, rolled back):
```
Proof Agency Empty     mode=delete     candidates=0 bgv_cases=0          -> deleted (gone from DB)
Proof Agency History   mode=deactivate candidates=4 bgv_cases=2          -> deactivated (kept, active=False)
Proof Agency Open BGV  open_bgv=['Proof Open Case']                      -> HTTP 409 "Reassign or cancel the open BGV cases first."
Inactive filter lists: ['Proof Agency History']; restore -> active True
```
Live check (read-only): the only live agency, "Bright talent partners" (paused, 0 candidates, 0 cases), would be a clean delete. It was not touched.
**Still to prove on screen:** the delete and deactivate dialog screenshots.
