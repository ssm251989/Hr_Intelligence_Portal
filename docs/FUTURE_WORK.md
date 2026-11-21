# Future work

Items the owner has decided to do later, with where they came from. Each needs its own part when its time comes.

## Cloud / AWS phase

Logged 2026-11-21 (owner decisions after the Part 30 proofs, docs/ui/PART30.md 30.2h).

1. **One-row settings tables per company.** `interview_scheduling_settings`, `hr_integrations` (the HR mailbox) and
   `local_import_settings` hold one row per installation (`id = 1`). A second company on the same database (isolation
   `shared_rls`) cannot see tenant #1's row through RLS, and "create it if missing" then hits the primary key
   (`UniqueViolation`), so such a company cannot schedule interviews, has no HR mailbox settings and no local import
   settings. Fix: key each table by company (migration: `tenant_id` into the primary key / a unique key, one row per
   company) and change the three getters (`app/interview_scheduling/storage.py`, `app/integrations/hr_email.py`,
   `app/local_import/storage.py`) to read/create the current company's row. Take care with `hr_integrations`: it holds
   the HR mailbox credentials. Until then: test keys (sandbox company) cover screening, jobs, applications and cards;
   interview scheduling works with live keys only (docs/PUBLIC_API.md).
2. **Separate-database companies are not reachable by the app.** Isolation `dedicated_db` creates a company database
   (`hrctl tenant create`), but the app opens every request on the one installation database (`app/core/database.py`:
   one engine, `get_db` = `SessionLocal`), so a dedicated-db company's data is never served. Fix for AWS hosting: pick
   the engine per request from the resolved company (its DSN from the control plane / secrets), with a small pool per
   company, and the same for the scheduler's per-company jobs. Until then companies beside tenant #1 on one installation
   must use `shared_rls` (Part 28.5 cloud sign-up provisions `dedicated_db` - it needs this before it goes live).
