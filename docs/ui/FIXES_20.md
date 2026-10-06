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
