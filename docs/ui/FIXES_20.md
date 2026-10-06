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
