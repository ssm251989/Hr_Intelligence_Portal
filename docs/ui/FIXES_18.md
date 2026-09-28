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
