# PART 32 - One CTD approver + signed approvals (on-prem first) - proof (2026-11-22)

Proof on a **fresh install** in throwaway databases (`python -m app.platform.install`, databases `t32_main` /
`t32_cp`, login `t32_app`, company "Proof Company (P32)", admin `admin.p32@example.com`), API :8012 with the install's
own `.env` + `DEV_MAIL_CAPTURE`, web :5176. A **proof-only** CTD key pair and two signed CTD files (approver A
`licence.proof@ctdtechs.com`, approver B `approvals.proof@ctdtechs.com`) were made with `tools/ctd_licence` in the
scratchpad; the proof public key + file A sat in `backend/app/platform/licence/` for the proof only (never committed).
Afterwards: the throwaway databases + login dropped, the proof keys deleted, the licence folder back to code only.

| # | Step | Result | OK |
|---|---|---|---|
| 1 | Install ends | 9 steps done; "Modules: requested ACT-2026-00001" (first access), not sent - no HR mailbox yet | yes |
| 1b | Admin opens `/jobs` | Only "Waiting for CTD Techs approval": request number, the ONE approver from the signed file, the request text, Email CTD (mailto filled in), Copy request, code entry (`p32-1-waiting-page`). API: `/jobs`, `/api/v1/candidates`, `/api/public/v1/jobs` -> 403 `WAITING_FOR_CTD`; `/auth/me` and `/api/v1/licence/status` 200 | yes |
| 2 | CTD side: `python -m ctd_licence approve @request` | shows company, admin, modules, install id, nonce; code `CTD1....` printed and logged | yes |
| 2b | Code pasted on the waiting page | unlocked; Jobs, Candidates, Screening, Shortlisting open (`p32-3-unlocked-jobs`) | yes |
| 3 | Choose what you want: + Interviews -> ACT-2026-00002 -> CTD approves with the tool -> code on the Modules page | first try: **"String should have at most 40 characters"** -> fix 1; after it "Candidates, Interviews, Jobs, Screening, Shortlisting - now active" (`p32-5-module-approved`). The request card said "we keep trying automatically" for a request no mailbox can send -> fix 3 | yes (fixes 1, 3) |
| 3b | `UPDATE company_modules SET status='active'` for Salary | Salary's API stays 403 `MODULE_NOT_ACTIVE`; log: "module salary is active in the database without a CTD approval - ignored". The Modules page still **showed** Salary as active -> fix 2; after it: off | yes (fix 2) |
| 4 | Settings > Licence > Load CTD file (file B) | "CTD file loaded. Requests now go to approvals.proof@ctdtechs.com"; the next request (ACT-2026-00003) and its Email CTD link go to the new address (`p32-6`, `p32-7`) | yes |
| 5 | Mail | nothing left the PC (no mailbox on the fresh install: Email CTD / Copy request) | yes |

### Bugs found and fixed (tests in `tests/test_licence.py`, each fails on the old code)

1. **The Modules page refused CTD's code**: its code field still allowed 40 characters (the old 8-character code).
   `test_the_modules_page_takes_a_long_signed_code`.
2. **A row switched on by SQL showed as "active"** on the Modules page (the gate already refused it). `status()` now
   shows it off. Part of `test_a_module_switched_on_in_the_database_stays_off`.
3. **Wrong words for a request that no mailbox can send**: "we keep trying automatically" -> "Send it to CTD Techs
   yourself: Email CTD ... or copy it".

## Checks

- `tests/test_licence.py` 19 passed (signature: valid / edited / other install / other key / other company / expired /
  used twice / 5 wrong -> lock; tamper by SQL and by editing a stored approval; missing / edited / unsigned CTD file;
  `.env` approvers ignored, list read-only; locked install -> 403 except sign-in, waiting page, code entry; jobs and
  agents skip a locked company; 14-day upgrade grace then lock; no grace for a company created later; valid_until
  warns then read-only; the tool round trip, approver outside ctdtechs.com refused).
- Full backend suite in 12 batches: **164 failed / 1596 passed** - every failure is in the 165-test baseline (the one
  missing is the settings test Part 31 fixed); none new.
- Frontend: i18n 0 missing, tsc + vite build OK; vitest 59 passed / 3 failed (the 3 old ones).
