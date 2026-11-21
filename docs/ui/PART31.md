# PART 31 - Settings screen fixes (colleague's work, merged safely) - check (2026-11-21)

Source: the colleague's files in `Claude outputs/colleague-settings-fixes/` (made on an older copy). Each file was
compared with the current one and only the listed changes were brought over:

| File | Taken | Left out (would have undone newer work) |
|---|---|---|
| registry.py | `validate()` + `_check_type` / `_check_schema` (applied as the colleague's own hunks) | - |
| resolver.py | `resolve()` -> (value, source scope); `get()` calls it | - |
| router.py | `is_default` on the list | - (PUT / revert 400s were already there) |
| test_settings_resolver.py | renamed key + validation tests | - |
| settingValue.ts / .test.ts | new files, as they are | - |
| PlatformSettingsPanel.tsx | startEditing, parse-error message, isDefault from `is_default`, Revert through the revert route | the switch back to `toLocaleString()` (kept `formatDateTime`) |
| client.ts | `is_default?`, `platformSettingsApi.revert` | the removal of `tours_off` (Part 27) and the super-admin `signups` (Part 28.5) |
| settingsHome.ts | `settings.invalid_*` (EN/HI/TA) | - |

Added here: import is all or nothing (one bad value -> 400 with every problem, nothing saved; unknown keys are still
skipped); revert matches `scope_id` as well as version + scope type; history ties broken by version (two writes in the
same Windows clock tick came back in the wrong order - `test_history_records_every_write_in_order` was flaky); the
panel in EN/HI/TA (Edit, History, Save, Cancel, Revert to this, Reverting..., No changes recorded yet., (empty),
(current), unknown, the history title - now the setting's name instead of its key -, the "could not ..." messages,
Yes / No instead of true / false); an empty JSON box saves the built-in default (null when the default is null).

## 31.4 Proof on screen (Settings > Advanced > All settings, sandbox company `ctd-techs-sandbox`)

Proof stack: API :8011 (`TENANCY_MODE=multi`, `DEV_MAIL_CAPTURE`), web `http://sandbox.localhost:5175`, sandbox admin.
The sandbox was used so no live company setting was changed.

| # | Step | Result | OK |
|---|---|---|---|
| 1 | `recruitment.shortlisting.undo_hours` (whole number, never changed) | "Default" chip shown (`p31-1-default`) | yes |
| 2 | Edit, type `abc`, Save | red "Enter a whole number."; nothing sent, nothing saved (`p31-2-abc-refused`) | yes |
| 3 | Save 6, then 8 | the "Default" chip is gone (`p31-3-changed-no-default-chip`) | yes |
| 4 | History -> Revert to this (v1) | first try: **the History dialog closed itself**, so the new entry was never seen -> fix; after it the dialog stays open and shows "v3 - sandbox.admin@example.com (revert to v1) ... (current)" (`p31-4-history-revert`) | yes (fix) |
| 5 | The app in Hindi, then Tamil (the user's language preference, as the language picker saves it), Edit + History | no English word of the panel left (`p31-5-hi-edit`, `p31-6-hi-history`, `p31-5-ta-edit`, `p31-6-ta-history`); the admin set back to English after | yes |

### Bug found and fixed

- **History closed after Revert.** Every reload after a save / revert replaced the list with a spinner, which unmounted
  each row and its open History dialog. Now only the first load shows the spinner. Test (fails on the old code):
  `PlatformSettingsPanel.test.tsx` "the history stays open after Revert and shows the new entry".

### Still English (outside the panel's own words)

- Each setting's name and "Changes: ..." line come from the server's setting texts (`help_catalog.py`), which are
  English for every setting; a setting without help text shows a name made from its key ("Undo hours").
- The "(revert to vN)" marker is stored text in the history's "updated by".
- Dates use the shared `formatDateTime` (English month names).

## Checks

- Backend: `tests/test_settings_resolver.py` 34 passed (5 runs in a row); the 35 other files that mention settings:
  119 failures, all in the 165-test baseline (none new).
- Frontend: i18n 0 missing, tsc + vite build OK; vitest 59 passed / 3 failed (the 3 known old ones).
