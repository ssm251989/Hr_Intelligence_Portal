# PART 26 - HR Autopilot (automatic agents): migrate, tests, end-to-end check (2026-11-18)

Branch `KG-Development` (the Autopilot code came in with `b32e368` / `3b4b8bc` / `ed3efbf`).

## 26.1 Migrate + tests

| Check | Result |
|---|---|
| `alembic heads` | one head **e1f4a7c2d9b8** (Part 29) -> down_revision **c6a8e2f4b1d3** (Part 26) -> down_revision **a9f28d9eafb0**; DB was at a9f28d9eafb0. No down_revision change needed. |
| Upgrade | `python -m hrctl.migrate --all-tenants --control-plane` -> control plane + `ctd-techs: ok`; `alembic current` = e1f4a7c2d9b8 (head) |
| RLS | `agent_activity`, `autopilot_state`: row security enabled + forced, policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` - identical to `applications` / `agent_suggestions`; `hr_app` has INSERT/UPDATE |
| Tests | test_autopilot 15, test_hr_agents 24, test_shortlisting, test_intelligence: only the 3 known intelligence failures (same on `9d9b4eb`) |
| Frontend | `tsc -p tsconfig.app.json` 0 errors (no AutopilotPage type errors left), `npm run build` OK |
| Health | jobs autopilot_events / autopilot_hourly / autopilot_daily green. They showed their raw names; labels added ("HR agents - events (every minute)", "... watchdog and hourly checks", "... morning briefing"). |

## 26.2 End to end (proof stack: mailpit `mailpit-p26`, API :8010 with mail capture, web :5174; Autopilot on, rules off first)

Data: fixture script ("Proof ... (P26)", `@example.com`), real careers applications with generated resumes, the real
salary form, documents form, vendor link and offer signing endpoints; the real model for screening, document checks,
the BGV report reader and the briefing.

| # | Check | Result | OK |
|---|---|---|---|
| a | Resume to a published job | Applied 13:09:31 -> screened by the app (97.5) -> 13:10:50 Screening agent: "Shortlist Kiran Das" card (Part 29: rules off = card). Weak resume (2.5): no card. | yes |
| b | Rule shortlist score = 70 | Job that shortlists automatically: Ravi (98) **shortlisted by the rule** ("Decided by rule", undo window); **undo** on the Shortlisting endpoint -> back to Screened. Job that shortlists by hand: card (after fix 1). | yes (fix 1) |
| c | Salary rule 10 % | Asha answers 8 % over -> **approved by rule**, documents email. Bharat 20 % over -> card "counter at 12,00,000 (band max)". Approving -> counter email (after fix 3). | yes (fixes 2, 3) |
| d | Documents rule on | Asha, clean set -> **approved by rule**, BGV started. Dev, PAN in another name -> card (names_differ, dob_differs). | yes (fixes 2, 4) |
| e | BGV | Vendor rule on -> sent to the fastest vendor (QuickCheck, 3 days) (after fix 5). Vendor uploads a clear report -> AI reading "clear (97 %)" -> pass rule -> BGV passed -> rule off: card with 3 working days (18 / 21 / 23 Dec, after the 30-day notice); rule on (Asha, 98 %): joining dates emailed. | yes (fix 5) |
| f | Joiner today, pre-boarding 100 % | Rule off -> "Confirm gita.p26 joined" card; rule on + Run now -> joined, employee CTD-0028 | yes |
| g | Exit past LWD, clearance done | Rule off -> letters card; rule on + Run now -> letters issued. Exit still blocked 4 days after LWD -> HR told (bell). | yes |
| h | Watchdog | Salary waiting 72 h -> one bell message to each of the 2 approvers; Run now again -> none. Unsigned offer 72 h -> **re-sent once** (mailpit "Reminder: your offer ... is waiting for your signature"), next run -> recruiter told. | yes |
| i | Briefing (Run now) | 22 HR users got a bell message linking to `/autopilot?briefing=<id>`; with `autopilot.briefing.email` on, 22 emails "Your HR briefing for today". Text in Markdown with an invented "all over 48 h old" -> fix 6. | yes (fix 6) |
| j | Switches | Screening agent off -> a 96-score applicant still got a card -> fix 7. Master off -> nothing for a new applicant; the 60 activity rows stay; but on switching back on the applicant got a card a minute later -> fix 8. | yes (fixes 7, 8) |
| k | No `platform.settings.configure` (Manager role) | overview `can_configure: false`; switches and rule fields disabled, no Run now; PUT -> 403 (`p26-k-page-manager.png` vs `p26-k-page-admin.png`) | yes |
| l | AI Intelligence usage | agents.bgv_reader: 2 requests INR 0.42; agents.briefing: 23 requests INR 12.90 | yes |

### Bugs found and fixed (cause quoted first; each has a test that fails on the old code)

1. **Rule on, job shortlists by hand -> nothing at all.** A 96-score candidate got no decision and no card. Cause:
   `shortlist_rule` returned None when `maybe_auto_shortlist` declined (the job's own setting wins), without the card
   fallback. Now the card comes, exactly as with the rule off.
2. **Timeline said "Bharat's salary ... was approved"** while he waited on a card; and "proposed a counter" twice.
   Cause: the TRACK line for `salary_auto_decided` was written for every outcome (the check logs it with
   `new_status: salary_above_band` too); two events (form answer + check) both woke the Salary agent. Now: the line
   only for `new_status = salary_approved`; a pending card of the same kind is not proposed again (`core.waiting_card`,
   also used by the Documents, Offer and Scheduling agents - each had the same double line).
3. **Approving an agent card after a restart did nothing** (card "approved", no counter, no email). Cause:
   `agents.service.decide` applies a card only if its kind is in `_APPLIERS`; the agent appliers register when
   `app.hr_agents.approvals` is imported, which in a fresh process had not happened yet. `decide()` now imports them,
   and an `agent_*` card without an applier is refused ("nothing was changed") instead of silently approved.
   Verified live: card made by another process, approved 2 s after a restart -> counter email sent.
4. **Document check: "End date (May 2026) appears to be in the future"** on 18 Nov 2026. Cause: the AI document
   check (`document_validator`) was never told today's date. It now is (both callers: joining documents and BGV).
5. **No BGV could go to a vendor from Autopilot** - by rule: `TypeError: unhashable type: 'dict'`; by card: HTTP 500.
   Cause: a vendor's checks are stored as `{"check", "price"}` and the BGV agent passed those rows to
   `vendors.assign`, which takes names. Now names (`hiring.check_names`), also for cards made before the fix.
6. **Briefing in Markdown and with invented facts** ("all over 48h old" - the data has no ages). The prompt now asks
   for plain text with "- " bullets and forbids ages / dates / numbers not in the data. Re-run: plain text.
7. **Screening agent switched off still prepared shortlists.** Cause: the `ai_screening_scored` event calls
   `shortlist_rule` directly and only `screen()` checked the switch.
8. **Events from while Autopilot was off were replayed when it was switched on** (a card for an applicant who
   applied during the off time, one minute after switching on). Cause: `run_events` returned early while off and left the
   cursor where it was. The cursor now keeps moving while off, as the design says ("events are not replayed").

Every rule stays default-off; every "card instead" path is kept (fix 1 adds a missing one).

### Seen, not changed (for the owner)

- A card for something an Autopilot rule then did itself stays pending (e.g. "Confirm Gita joined" after the rule
  recorded her; "Issue letters to Hari"). Approving it later is refused by the service and the card keeps the reason.
  Closing them needs a new card status (migration) - owner to decide.
- The watchdog tells the recruiter on the run after the offer reminder (the doc's "next run"), i.e. an hour later in
  production; its docstring says "a day later".
- An event whose handler fails (fix 5 before the fix) is not retried; it shows as "Failed" in the activity.
- Exit letters by card leave the exit at *clearance*, by rule at *completed* - both call the same
  `exit_checklist.generate_letters`; the difference is in that service's completion step, not in the agents.

### My mistakes during the check (reported to the owner)

- One-off scripts run **outside** the proof API had no `DEV_MAIL_CAPTURE`, so they used the real HR mailbox:
  12 "Exit checklist: ..." task emails for the made-up leavers *Proof Hari Menon* / *Proof Indu Varma* went to
  **kg@ctdtechs.com**, and one "Background check request: Proof Chitra Pillai" to `quick.p26@example.com`
  (reserved domain, undeliverable). Every later script ran with mail capture.
- The company setting `recruitment.shortlisting.auto_shortlist` was switched off for check b and back on through the
  settings API; its history shows both changes (version 2 -> 4).

## 26.3 Clean-up (Parts 26 + 29 together)

Dry run, then delete (same scan as FIXES_25): 12 applications / candidates (fixture + 7 careers applicants), 2 jobs,
2 vendors, 2 interviewer pools, 18 candidate documents + 8 BGV copies, 2 BGV assignments, 2 offers + 1 version,
4 letters, 2 preboarding cases + 1 document, 4 employees + 1 employment record, 3 separations + 21 clearance items,
1 budget commitment, 16 agent cards, 53 timeline rows (incl. the 22 briefings), 100 messages (incl. the briefing
bells / emails), 116 audit rows, 14 action / 2 negotiation tokens, 7 consent records, the 2 temporary users
(Manager, employee) - and their files (8 BGV copies + 29 others). Scan after: 0 rows point at a proof id; no proof
file left under `uploads/` (the 40 `uploads/bgv/*.docx|png` from today are written by `tests/test_bgv.py`).
Kept: AI usage + decision-log rows (real spend).

Settings: every `autopilot.rules.*` back to its default (off / 0), `autopilot.briefing.email` off, the Screening agent
on - through the settings service, so their history shows the test and the reset. `autopilot.enabled` is **on**
(Part 29 default) - the owner's choice for this company is still open. `recruitment.shortlisting.auto_shortlist`
back on (see above). `recruitment.salary.auto_approve_hike_pct` untouched (20).
