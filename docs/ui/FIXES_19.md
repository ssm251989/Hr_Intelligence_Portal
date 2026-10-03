# Part 19 - Choose modules + activation code by email: proof

Spec: `Claude outputs/PART19_MODULE_ACTIVATION.txt` (owner, 2026-10-03). Part 19 replaces 18.4 (the one shared module passcode).

**Commits:**
- part-19.1 `c7e20f1`: backend
- part-19.2 `2359c7f`: frontend
- part-19.3: this proof, plus the fixes it found (below)

**How it was proved:**
- **Demo companies:** two new ones on the shared database: **demo-a** "Demo - A (Jobs only)" and **demo-b** "Demo - B (Candidates + Screening)", with hosts `demo-a.localhost` and `demo-b.localhost`.
- **Live API:** a second server (`uvicorn` on :8010, `TENANCY_MODE=multi`) answers per host.
  - Every 403 below is a real HTTP response from that server, without signing in; the module gate runs before sign-in.
  - The owner's own server (:8000, ctd-techs) was left untouched.
- **Request / activate:** the real service functions (`activation.request_activation` / `activate_with_code`), run as each demo company's own admin row.
- **Email:** Docker isn't on this machine, so there is no mailpit. A small local SMTP capture (127.0.0.1:1025, writes `.eml` files, never relays) stands in for it. The PLATFORM mailbox (`PLATFORM_SMTP_*`) points at it for the proof only.
- **Codes:** the code is read from the captured email, as CTD Techs would. Codes are written as `****-****` here (never in git).

## 19.1 Choose what you use

**Starting point:** a new company starts with every module **off**.

```
hrctl modules status --tenant demo-a  -> jobs off, candidates off, ... genai_usage off (all 12)
host demo-a  GET /candidates        -> 403 {"code":"MODULE_NOT_ACTIVE","message":"This module is not active for your company","module":"candidates",...}
host demo-a  GET /api/v1/ui/jobs    -> 403 MODULE_NOT_ACTIVE (jobs)
host demo-a  GET /screening/settings-> 403 MODULE_NOT_ACTIVE (screening)
```

**Existing company (ctd-techs) - no change in behaviour:**
- The migration backfilled all 10 hiring modules as active.
- Onboarding stays **off**. It was already off: kg@ctdtechs.com switched every optional module off on 2026-10-03 21:19, setting `[]`.
```
hrctl modules status --tenant ctd-techs -> jobs, candidates, screening, shortlisting, interviews, candidate_emails, salary, bgv, offers, reports, genai_usage: active; onboarding: off
menu (bootstrap)  /, /approvals, /jobs, /candidates/dashboard, /screening/dashboard, /shortlisting/dashboard, /interviews/dashboard,
                  /hr-inbox, /salary, /bgv, /offers, /agencies, /reports, /genai-usage, /setup, /settings   (same as before)
:8000 GET /candidates -> 401 (active, sign-in needed)    GET /api/v1/ui/onboarding/board -> 403 MODULE_NOT_ACTIVE (was 404 MODULE_DISABLED)
```

## Demo A - Jobs only

```
request [jobs]          -> pending, email_sent true, expires 10 Oct 2026 21:57 IST
status                  -> jobs: pending
wrong code ABCD-EFGH    -> 400 "This code is not correct. 4 tries left."
right code              -> activated [jobs]
same code again         -> 400 "This code has already been used."
menu                    -> /, /approvals, /jobs, /genai-usage, /setup, /settings
                           (GenAI usage comes with any AI module; Jobs has the AI job description)
host demo-a GET /candidates            -> 403 MODULE_NOT_ACTIVE "This module is not active for your company"
host demo-a GET /api/v1/ui/candidates/x-> 403 MODULE_NOT_ACTIVE
host demo-a GET /api/v1/ui/salary/x    -> 403 MODULE_NOT_ACTIVE
host demo-a GET /api/v1/ui/jobs        -> passes the gate (404 for this sub-path = route level, not 403)
```

The spec's `/api/v1/candidates` is `/candidates` in this API. That path and `/api/v1/ui/candidates/*` are both gated.

**Captured email** (the approver's copy; this is what CTD Techs receives):

```
X-Envelope-From: <no-reply@ctdtechs.com>
X-Envelope-To: <kg@ctdtechs.com>
From: HR Platform <no-reply@ctdtechs.com>
To: kg@ctdtechs.com
Subject: Activation request - Demo - A (Jobs only) - Jobs

Company: Demo - A (Jobs only)
Installation: demo-a.localhost (company demo-a)
Requested by: admin@demo-a.localhost <admin@demo-a.localhost>
Modules: Jobs
Requested at: 03 Oct 2026, 21:57 IST

Activation code: ****-****
Valid until: 10 Oct 2026, 21:57 IST (works once)

Share this code with the company when they may use these modules. They enter it on
Settings > Company > Modules.
```

The company's own mailbox is never used, and the company is never a recipient.

## Demo B - Candidates + Screening, no job record

```
request [screening]           -> 409 MODULE_NEEDS "Also switch on Candidates? Screening needs Candidates."
request [screening] with needs-> pending [candidates, screening]; email to kg@ctdtechs.com, Subject "Activation request - Demo - B (Candidates + Screening) - Candidates, Screening"
wrong code                    -> 400 "This code is not correct. 4 tries left."
right code                    -> activated [candidates, screening]
same code again               -> 400 "This code has already been used."
menu                          -> /, /approvals, /candidates/dashboard, /screening/dashboard, /agencies, /genai-usage, /setup, /settings
host demo-b GET /candidates           -> 401 (active; sign-in needed)
host demo-b GET /api/v1/ui/screening/jd -> 401 (active)
host demo-b GET /api/v1/ui/jobs       -> 403 MODULE_NOT_ACTIVE
host demo-b GET /api/v1/ui/salary/x   -> 403 MODULE_NOT_ACTIVE
```

**Resume upload + AI reading + scoring with no job.** These are the real endpoint functions (`upload_resume`, `parse_candidate_resume`, `list_candidates`, `ui_jd_screening_router.run_screening`) using `Sample/ASWATH_T_AA.pdf`:

```
uploaded       candidate 4177829a… source manual
parsed (AI)    "ASWATH T", 5.0 years, skills: RPA, Automation Anywhere, UiPath, Linux, ServiceNow, Jira
talent pool    1 candidate (GET /candidates)
JD screening   "Demo - Senior Python developer" (pasted JD) -> ASWATH T: match 15, weak_fit   (an RPA profile vs a Python JD -- sensible)
job records    0      applications 0
```

**Menu notes:**
- Agencies shows with Candidates: it is how agencies send candidates, so it belongs to that module.
- People, Exits, Assets and Analytics are not in Part 19's list. A new company now starts with them off: the `platform.modules.enabled` default changed to `[]`. They stay under "Other modules".

## Wrong / expired / used code, lockout

```
used code                      -> 400 CODE_USED "This code has already been used."            (A and B above)
expired (demo-b, [reports], expires_at moved 1 min into the past)
                               -> 400 CODE_EXPIRED "This code has expired - request a new one."
                                  page then shows the expired banner + "Request a new code" (open_request -> status "expired")
5 wrong tries (demo-a, [reports])
                               -> 4, 3, 2, 1 tries left, then 429 "…code entry is locked for 30 minutes and CTD Techs has been told."
right code while locked        -> 429 "Too many wrong tries. Please wait 30 minutes and try again."
lock email (captured)          -> To kg@ctdtechs.com, Subject "Activation code locked - Demo - A (Jobs only)",
                                  "…entered a wrong activation code 5 times. Modules requested: Reports … locked until 03 Oct 2026, 22:28 IST."
switch off Candidates (demo-b) -> 409 MODULE_NEEDED "Screening needs this module. Switch it off too?" (nothing changed)
```

## Approver must be @ctdtechs.com

```
ACTIVATION_APPROVER_EMAILS=someone@gmail.com  python -c "import app.main"
  -> RuntimeError: Module activation is misconfigured: someone@gmail.com is not a ctdtechs.com address. Activation codes only go to ctdtechs.com.
ACTIVATION_ALLOWED_DOMAIN=ctdtechs.com.evil.io ACTIVATION_APPROVER_EMAILS=kg@ctdtechs.com.evil.io  python -c "import app.main"
  -> RuntimeError: … ACTIVATION_ALLOWED_DOMAIN must be ctdtechs.com (or under it), not 'ctdtechs.com.evil.io'.
hrctl activation set-approver kg@gmail.com              -> refused: kg@gmail.com is not a ctdtechs.com address.
hrctl activation set-approver kg@ctdtechs.com.evil.com  -> refused
hrctl activation set-approver kg@ctdtechs.com           -> {"approvers": ["kg@ctdtechs.com"]}
```

The approver list is also checked again on every send.

## Found by this proof and fixed

1. **A successful activation returned a server error.** After the control-plane session closed, `activate_with_code` read `match.id` (and `request_activation` read `previous.id`): `DetachedInstanceError`. The modules were already active, but the page would have said "Something went wrong" and the audit entry was lost. Fix: the IDs are read before the session closes; the run above is after the fix.
2. **Expired code left the page stuck.** After an expired code there was no waiting request, so the page showed the module as "waiting" with no way forward. `open_request` now returns the expired request, and the page offers "Request a new code".
3. **New companies started with older optional modules switched on.** Assets, Exits, Analytics and the assistant were on by default. The default is now `[]` (only what the company chooses).

## Checks

- Backend: `compileall` OK; `alembic upgrade head` (tenant b19c1d2e3f4a, control plane c19a2b3d4e5f) OK.
- Frontend: `tsc -p tsconfig.app.json` clean; i18n 3919 keys, 0 missing (en/hi/ta); `npm run build` OK.

## Screenshots - pending login proof

The picker, waiting banner, code entry and final menus are signed-in screens. This session could not sign in: token creation and the probe helper were both refused. So no screenshots were taken, as with the earlier "pending login proof" entries. To take them:
1. Sign in as an admin of a demo company, or ctd-techs.
2. Open Settings > Company > Modules.
3. Run `frontend/scripts/take_screenshots.mjs` with `SHOT_ONLY=settings,setup`.

## Left in place for the owner

- **Demo companies:** demo-a and demo-b (control plane + rows on the shared database) and their activation requests. Remove them with `python -m hrctl.tenant delete --slug demo-a --confirm demo-a` (same for demo-b). That deletes data, so it is the owner's call.
- **Platform mailbox:** not configured on this machine (`PLATFORM_SMTP_HOST` empty). Until it is set, a request is saved but its email isn't sent. The page says so, and the console's Resend sends it once the mailbox works.
- **Old passcode table:** `module_access` (Part 18.4) is no longer used and is empty for ctd-techs. Dropping it is a later contract migration.
