# PART 27 - fresh-install fixes, one-step setup, the 39 test-report issues (2026-11-19)

Branch `KG-Development`. Inputs: `docs/ui/Hr_Inteligence_Portal_Issues_By_Pages.pdf` (E2E report, 5 Nov) and the
colleague's configuration notes. All mail went to Mailpit (`DEV_MAIL_CAPTURE=127.0.0.1:1025`).

## 27.0 One-step install + fresh-install fixes (code came in with `ed3efbf`)

| Check | Result |
|---|---|
| a. `pytest tests/test_install.py` | 20 passed |
| b. Throwaway install on this PC (`--answers %TEMP%\a.json --env %TEMP%\fi.env --delete-answers`, databases `t27_main` / `t27_cp`, login `t27_app`, app password with `@ #` and spaces) | all 9 steps "done" (PostgreSQL, login + databases, .env, tables, grants, company, base data, admin created, 11 modules on); answers file deleted. Run again: all 9 done, admin `created: false`, modules `switched_on: []` (re-run safe). `hr_automation` not touched. Then dropped `t27_main`, `t27_cp`, role `t27_app`. |
| c. `--check` with a line break in the admin password | "Please fix: - Admin password must not contain line breaks, tabs or other invisible characters." exit 2 |
| d. `backend/.env.example` | already `postgresql+psycopg2://`, `hr_app` login, "run `python -m app.platform.install` instead of editing this by hand" |
| e. `grant_app.py`, `dev_make_admin.py` | not in the repo or anywhere under it - nothing to delete |
