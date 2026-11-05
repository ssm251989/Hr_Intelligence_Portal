# Hardcode Inventory

Part 1, Step 1 of `docs/HRMS_COMPLETE_SPEC.txt` — read-only. Literal grep output below
each heading; table maps each real offender to category and target home. Binary
`__pycache__` matches and lines inside `backend/tests/`/`frontend/src/**/*.test.tsx`
fixtures are noted but not carried into the table (spec explicitly exempts test/fixture
email literals from the guard test).

## Literal grep output

### `grep -rnE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}" backend/app frontend/src`
```
backend/app/interview_scheduling/negotiation.py:17:     hradmin65@gmail.com is the single account of
backend/app/interview_scheduling/negotiation.py:537:    shared HR mailbox (hradmin65@gmail.com) is this app's single account of record for
frontend/src/components/HrMailboxSettingsCard.test.tsx: (4 hits, all "hr@example.com" / "hr-new@example.com" fixture values)
frontend/src/components/UploadCandidateDialog.test.tsx: (2 hits, "jane@example.com" fixture values)
frontend/src/utils/avatar.ts:2: * "jane@example.com" -> "JA".  (a docstring example, not a literal used at runtime)
```

### `grep -rniE "ctd|ctdtechs|hradmin|gmail\.com" backend/app frontend/src`
```
backend/app/integrations/hr_email.py:1,52          "CTDHR" (docstring naming)
backend/app/integrations/ics.py:35                 uid suffix "@ctdtechs.ai"
backend/app/integrations/ics.py:53                 prodid "-//CTD Techs HR Automation//Interview Scheduling//EN"
backend/app/integrations/router.py:102             "CTDHR" (comment)
backend/app/interview_scheduling/negotiation.py:17,339,370,537   "hradmin65@gmail.com", "CTD Techs", "CTD TECHS" (email HTML)
backend/app/interview_scheduling/negotiation_router.py:113,128,130,149   "ctdUpdateSlots" (JS fn name), "CTD TECHS" (picker page HTML)
backend/app/models/hr_integration.py:7,18           "CTDHR" (docstring naming)
frontend/src/careers/CareersLayout.tsx:17,29        "CTD Techs Careers" / "(c) CTD Techs. All rights reserved."
frontend/src/layout/AppLayout.tsx:250,254           "CTD" logo mark / "CTD Techs" wordmark
```

### `grep -rnE "#[0-9a-fA-F]{6}" backend/app`
```
backend/app/interview_scheduling/confirm_router.py    6 hex literals (status colors #1b8a5a/#b8860b/#b23b3b + confirm-page CSS)
backend/app/interview_scheduling/negotiation.py       ~15 hex literals (email HTML: brand gradient #0b1f4d/#1d5fd6/#5b7cff/#4f9dff/#7b5cff + layout greys)
backend/app/interview_scheduling/negotiation_router.py  ~40 hex literals (picker-page CSS: same brand palette + status tones)
```
(No hex literals found elsewhere in `backend/app`.)

### `grep -rnE "\.xlsx|C:\\\\|/Users/|Documents" backend/app`
```
backend/app/candidates/pipeline_actions.py:163   "Manage BGV Documents" (a UI button label string, not a filesystem path)
```
No absolute path or `.xlsx` literal exists anywhere in `backend/app`. The tracker/local-import file paths are already fully admin-configured (values live in DB-backed settings tables, per the existing `local_import_settings` / interview-scheduling settings tables — confirmed by grepping `interview_scheduling/storage.py` and `tracker.py` for `xlsx`/path literals: zero hits). **This category has zero offenders already** — no fix needed in Part 1, just register the existing setting keys formally in Part 2.

### `grep -rnE "smtp\.|imap\.|:587|:993|:465" backend/app`
```
(no hits)
```
Zero offenders: SMTP/IMAP host/port are already only ever user-supplied connection fields (`HrMailboxConnectDialog` / `hr_email.py`), never literals in code.

### `grep -rnE "claude-(3|haiku|sonnet|opus)" backend/app`
```
backend/app/ai_services/candidate_ranker.py:9              MODEL = "claude-sonnet-5"
backend/app/ai_services/document_validator.py:9             MODEL = "claude-haiku-4-5"
backend/app/ai_services/interview_question_generator.py:7   MODEL = "claude-haiku-4-5"
backend/app/ai_services/jd_generator.py:8                   MODEL = "claude-sonnet-5"
backend/app/ai_services/offer_letter_generator.py:7          MODEL = "claude-haiku-4-5"
backend/app/ai_services/resume_matcher.py:9                  MODEL = "claude-haiku-4-5"
backend/app/ai_services/resume_parser.py:9                   MODEL = "claude-haiku-4-5"
backend/app/ai_services/shortlist_feedback_generator.py:21    MODEL = "claude-haiku-4-5"
```

### `grep -rnE "(threshold|weight|score)\s*=\s*[0-9]" backend/app`
```
backend/app/screening/service.py:159   dashboard_min_score=60, dashboard_max_score=100,
backend/app/screening/service.py:160   interview_min_score=75, interview_max_score=100,
```
(These are the seed defaults for the *existing* `ScreeningSettings` singleton row — already
a tenant-editable settings row today, not a literal read at runtime. Flagged for Part 2 so
its defaults become `SettingDef.default` instead of an ORM column default.)

### `grep -rnE "Asia/|timezone\(|tzinfo" backend/app`
```
backend/app/integrations/google_calendar.py:29,144,145   APP_TIMEZONE = ZoneInfo("Asia/Kolkata"); "timeZone": "Asia/Kolkata"
backend/app/interview_scheduling/tracker.py:190,194      uses APP_TIMEZONE
backend/app/interview_scheduling/confirmation.py:91,94   uses APP_TIMEZONE
backend/app/interview_scheduling/negotiation.py:154,158  uses APP_TIMEZONE
backend/app/interview_scheduling/negotiation_router.py:194  uses APP_TIMEZONE
backend/app/reports/stats.py:36                          _IST_OFFSET
(remaining hits: timezone.utc / tzinfo=... on naive datetimes — correct UTC-storage
 discipline already followed everywhere else, not an offender)
```

### `grep -rn "os.getenv\|os.environ\|settings\." backend/app/core`
```
backend/app/core/config.py     DATABASE_URL, ANTHROPIC_API_KEY, SECRET_KEY, ALGORITHM,
                                ACCESS_TOKEN_EXPIRE_MINUTES, GOOGLE_CLIENT_ID/SECRET/
                                REDIRECT_URI, DOCUSIGN_* (5 vars), LINKEDIN_* (4 vars),
                                LINKEDIN_API_VERSION, FRONTEND_URL, APP_BASE_URL
backend/app/core/crypto.py      settings.SECRET_KEY (derives the app's Fernet key)
backend/app/core/database.py    settings.DATABASE_URL
backend/app/core/security.py    settings.ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY, ALGORITHM
```
All already env-driven (correct today: these are per-*installation* deployment config, not
per-tenant data — MODE 1 gives every client their own installation/.env, so this whole
category is allowed to stay as env vars per section A's "what IS allowed in code" carve-out).
The two that become *connections* rather than plain env vars in Part 3 are `GOOGLE_CLIENT_ID/
SECRET` (folded into each tenant's own OAuth app config) and `DOCUSIGN_*`/`LINKEDIN_*`
(become `esign.offer_letters` / `jobboard.linkedin_jobs` connection configs) — the rest
(`DATABASE_URL`, `SECRET_KEY`, `ANTHROPIC_API_KEY` as platform default, `FRONTEND_URL`,
`APP_BASE_URL`) legitimately stay as deployment env vars under MODE 1.

## Inventory table

| File | Line(s) | Literal | Category | Target home |
|------|---------|---------|----------|-------------|
| `interview_scheduling/negotiation.py`, `negotiation_router.py` | 17, 537, 113/128/130/149 | `hradmin65@gmail.com`, `ctdUpdateSlots` | identity / connection | Part 3: migrated mailbox connection (`email.outbound.interview_negotiation`) |
| `integrations/hr_email.py`, `models/hr_integration.py`, `integrations/router.py` | 1, 52, 7, 18, 102 | `"CTDHR"` naming in docstrings/comments | identity (naming only, not data) | Part 3: rename to generic `HrMailboxIntegration`/connection terminology when the table is migrated |
| `integrations/ics.py` | 35, 53 | `@ctdtechs.ai` UID suffix, `-//CTD Techs HR Automation//...` PRODID | identity / branding | Part 4/6: `org.display_name` + a tenant domain setting for the UID suffix |
| `interview_scheduling/negotiation.py`, `negotiation_router.py`, `confirm_router.py` | see hex-colour block above | `#0b1f4d` / `#1d5fd6` / `#5b7cff` / `#4f9dff` / `#7b5cff` gradient + `#1b8a5a`/`#b8860b`/`#b23b3b` status colors + "CTD TECHS" wordmark | branding | Part 4: `brand_themes` (primary/secondary/gradient colors) + `message_layouts` HTML shell |
| `ai_services/*.py` (8 files) | see model-id block above | `MODEL = "claude-sonnet-5"` / `"claude-haiku-4-5"` | model / connection | Part 3 §5 + Part 2 settings `ai.models.scoring` / `ai.models.judgment` / etc., resolved via `ai.gateway.complete(purpose=...)` |
| `screening/service.py` | 159-160 | `dashboard_min_score=60`, `interview_min_score=75`, etc. | business-rule | Part 2 §6: `recruitment.screening.auto_shortlist_threshold` and sibling setting keys (already a tenant-editable row today — becomes a proper `SettingDef`) |
| `integrations/google_calendar.py`, `interview_scheduling/tracker.py`/`confirmation.py`/`negotiation.py`/`negotiation_router.py`, `reports/stats.py` | see timezone block above | `APP_TIMEZONE = ZoneInfo("Asia/Kolkata")`, `_IST_OFFSET`, `"Asia/Kolkata"` string | business-rule (timezone) | Part 2 §6: `org.timezone` (layered setting), Part 7 `locations.timezone` for per-location overrides |
| `candidates/pipeline_actions.py` | 163 | `"Manage BGV Documents"` | wording | Part 4/6: i18n key (button label), not a literal — low priority, swept incidentally during Part 4/6 UI work |
| `frontend/src/layout/AppLayout.tsx` | 250, 254 | `"CTD"` mark, `"CTD Techs"` wordmark | branding | Part 6 §5: `/api/me/bootstrap` branding (logo/product name) |
| `frontend/src/careers/CareersLayout.tsx` | 17, 29 | `"CTD Techs Careers"`, `"© {year} CTD Techs..."` | branding | Part 6 §5 + Part 8 §3 (career-site branding, per-domain) |
| `core/config.py` | `GOOGLE_CLIENT_ID/SECRET`, `DOCUSIGN_*`, `LINKEDIN_*` env vars | connection credentials living in app `.env` | connection | Part 3: each becomes a tenant `connections` row + `SecretStore` entry, config schema per adapter |
| `core/config.py` (remaining) | `DATABASE_URL`, `SECRET_KEY`, `ANTHROPIC_API_KEY`, `FRONTEND_URL`, `APP_BASE_URL` | deployment-level env vars | **not an offender** | stays as per-installation env config under MODE 1 (section A carve-out); `ANTHROPIC_API_KEY` also becomes the *platform-key* fallback connection in Part 3 §5 |

## Already clean (zero offenders found)

- Absolute filesystem paths / `.xlsx` literals in `backend/app` — tracker & local-import
  paths are already DB-setting-driven.
- SMTP/IMAP host or port literals in `backend/app` — already always user-supplied.

## Baseline count for the guard test (Step 3)

The actual `backend/tests/test_no_hardcoded_tenant_values.py` guard (narrower than this
audit -- see its own docstring for exactly which of the categories above it enforces:
email addresses, "gmail.com", "ctdtechs"/"CTD Techs", absolute paths, ".xlsx" literals,
backend-only hex colours, and model IDs) found, as of this Part 1 commit:

**84 offending lines across 15 distinct files**, after `hardcode_allowlist.txt`'s one
genuine exception (a UI placeholder string in `InterviewTrackerSettingsCard.tsx` that
merely illustrates the expected path format, never a real value):

```
model_id:      8   (every backend/app/ai_services/*.py MODEL constant)
ctdtechs:      8   (ics.py, negotiation.py/negotiation_router.py comments+HTML,
                     CareersLayout.tsx, AppLayout.tsx)
email_address: 3   (negotiation.py's hradmin65@gmail.com x2, avatar.ts's docstring example)
gmail.com:     2   (negotiation.py's hradmin65@gmail.com x2)
hex_color:    63   (confirm_router.py, negotiation.py, negotiation_router.py -- the
                     email/confirmation-page HTML builders)
```

Files: `ai_services/{candidate_ranker,document_validator,interview_question_generator,
jd_generator,offer_letter_generator,resume_matcher,resume_parser,
shortlist_feedback_generator}.py`, `integrations/ics.py`,
`interview_scheduling/{confirm_router,negotiation,negotiation_router}.py`,
`frontend/src/careers/CareersLayout.tsx`, `frontend/src/layout/AppLayout.tsx`,
`frontend/src/utils/avatar.ts`.

This is the number Part 2-4 must drive to zero (or allow-list with a reason) before Part 4
flips the guard from `xfail(strict=True)` to a hard pass.
