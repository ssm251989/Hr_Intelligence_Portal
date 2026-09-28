# Part 18 -- owner change list: fixes and proof

Each item: problem, change, how verified, screenshot. Proof calls run through the real app
(`backend/scripts/probe.py`, TestClient, signed-in user by role) or inside a rolled-back transaction.
Signed-in screenshots are marked **pending login proof** until a login is available.

## 18.1 Remove 2-step verification

**Problem:** people were asked about 2-step verification. It appeared in Settings > People & access and in Home/health warnings ("admins sign in without 2-step verification").

**Change:**
- New setting `iam.auth.two_step_available` (Settings > Advanced > All settings, group "Advanced"), **off**.
- While it is off:
  - sign-in never asks for a code or to enrol, even if "Require 2-step" was on (`mfa.is_mfa_required` returns false);
  - the 2-step warnings are not produced;
  - the 2-step settings page is hidden from the Settings menu (bootstrap sends `two_step: false`).
- The code is kept; switching the setting on brings everything back.

**Verified:**
```
GET /api/v1/setup/config-health  before: ADMIN_WITHOUT_2FA, USERS_WITHOUT_2FA, COPILOT_NO_KNOWLEDGE, UNROUTED_PURPOSE x2
                                 after : COPILOT_NO_KNOWLEDGE, UNROUTED_PURPOSE x2   (2-step warnings gone)
GET /api/me/bootstrap            -> "two_step": false  (Settings hides the 2-step page)
rolled back: mfa_required=on, feature off -> asked for code: False
             mfa_required=on, feature on  -> asked for code: True
```
(`UNROUTED_PURPOSE` is fixed in 18.2.) Setup checklist had no 2-step step. **Screenshot:** settings menu -- pending login proof.

## 18.2 One company email for everything

**Problem:** the company has one mailbox, but each purpose needed its own route. Helpdesk and candidate-application inbound mail showed as "not connected", so health warned about them.

**Change:**
- Every inbound purpose now falls back to `email.inbound.default`.
- `ConnectorRouter` gained a "company mailbox" fallback: an email purpose with no route of its own uses the connection already routed in the same direction (reading = IMAP, sending = SMTP).
- The health check and the Settings > Connections purpose list now ask the router itself (fallbacks included) instead of looking for a row per exact purpose.
- The Settings > Communication > Mailbox card now says in plain words that it is the one mailbox used for every module (en/hi/ta).
- Per-purpose email routing is no longer shown anywhere for normal users. The routing API is still there for advanced use.

**Verified:**
```
config-health: UNROUTED_PURPOSE for helpdesk email -> gone (only "e-sign" left, fixed in 18.3)
GET /api/v1/connectors/purposes: all 12 email.* purposes routed=True (before: helpdesk, candidate_applications inbound etc. False)
router (rolled back): email.inbound.helpdesk            -> imap dbc7bdb9 via email.inbound.negotiation_replies
                      email.inbound.candidate_applications -> imap dbc7bdb9
                      email.outbound.helpdesk / reports -> smtp 64664ee5 via email.outbound.default
tsc clean, i18n 0 missing
```
**Screenshot:** mailbox card -- pending login proof.

## 18.3 Health checks read the real status

**Problem:** DocuSign is connected, but Home said "Offer letters can't be e-signed yet - connect DocuSign". The check only looked for a company connection row. This app connects DocuSign per person (OAuth sign-in, `app/integrations/docusign.py`), and offers are sent through that person's account. Connections that had never been tested also counted as fine.

**Change:**
- E-sign counts as connected when a company e-sign connection is routed, or when the app has DocuSign keys and someone in the company has signed in to DocuSign.
- Every purpose check asks the router, including fallbacks (18.2).
- A connection is healthy only when it is active **and** its last test passed. A failing one shows its real error (for example "535 login failed"); a never-tested one shows "hasn't been tested yet".
- New `POST /api/v1/setup/config-health/recheck` really tests every connection. It saves the result and time; a failed test does not switch the connection off.
- The Home "Configuration health" card has a **Re-check now** button and shows when it last checked (en/hi/ta).

**Verified:**
```
before (Home):  UNROUTED_PURPOSE "Offer letters can't be e-signed yet - connect DocuSign"
after:          no e-sign issue (DocuSign signed in by a user); "Anthropic / Interview Tracker hasn't been tested yet"
POST recheck -> 200: tested anthropic True, excel_file True, imap True, smtp True -> only COPILOT_NO_KNOWLEDGE left
rolled back: smtp last test failed -> CONNECTION_FAILING "HR Mailbox (SMTP) isn't working" fix "535 login failed"
             no DocuSign sign-in  -> UNROUTED_PURPOSE e-sign warning comes back
```
**Screenshot:** Home health card -- pending login proof.
