# Backup and restore

## What is backed up

`hrctl backup run` (Part 17.13) makes, in `backups/` next to the repo (git-ignored because it contains personal data):

| File | What |
|---|---|
| `hrms-app-YYYYMMDD-HHMM.dump` | the application database (all companies' data), PostgreSQL custom format |
| `hrms-control-YYYYMMDD-HHMM.dump` | the control-plane database (tenants, licences, domains) |
| `hrms-uploads-YYYYMMDD-HHMM.zip` | `backend/uploads/` - resumes, photos, logos, media, import files |

The newest 14 sets are kept (`--keep N` to change). Older `hrms-*` files the command made are removed; nothing else is touched.

## Run it

```powershell
cd backend
.venv\Scripts\python.exe -m hrctl.backup run            # now
.venv\Scripts\python.exe -m hrctl.backup list           # what's there
```

`pg_dump` is found on PATH, in `C:\Program Files\PostgreSQL\1x\bin`, or set `PG_DUMP` to its full path.

### Every night

- **Windows (local server):** Task Scheduler -> Create Basic Task -> Daily 02:00 -> Start a program:
  `C:\Users\<you>\Documents\hr-automation\backend\.venv\Scripts\python.exe`, arguments `-m hrctl.backup run`,
  start in `C:\Users\<you>\Documents\hr-automation\backend`.
- **Linux / Docker:** cron `0 2 * * * cd /app/backend && python -m hrctl.backup run --dir /backups` (mount `/backups` on a separate disk).
- **AWS:** use RDS automated backups (7-35 days) + a daily snapshot; put uploads in S3 (the `storage.documents` connection) with
  versioning and a lifecycle rule. `hrctl backup run` is then an extra, portable copy - copy `backups/` to S3:
  `aws s3 sync backups s3://<bucket>/hrms-backups/ --storage-class STANDARD_IA`.

Copy backups off the server (another disk, S3, or a NAS). A backup on the same disk as the database protects against mistakes, not against losing the disk.

## Restore

> A restore replaces the database's contents. Do it on a new/empty database first, check it, then switch over.

1. Stop the backend (and the background worker).
2. Create empty databases (or drop the broken ones):
   ```sql
   CREATE DATABASE hr_automation_restore;
   CREATE DATABASE hr_control_restore;
   ```
3. Restore:
   ```powershell
   pg_restore --no-owner --role=<app_owner_role> -d hr_automation_restore backups\hrms-app-YYYYMMDD-HHMM.dump
   pg_restore --no-owner --role=<app_owner_role> -d hr_control_restore  backups\hrms-control-YYYYMMDD-HHMM.dump
   ```
4. Unzip `hrms-uploads-...zip` into `backend/uploads/`.
5. Point `DATABASE_URL` / `APP_DATABASE_URL` / `CONTROL_PLANE_DATABASE_URL` in `backend/.env` at the restored databases,
   run `alembic upgrade head` (brings an older backup up to the current schema), start the backend, sign in and check the
   admin **System health** page (Settings > Data & privacy > System health).

Row-level security policies are part of the dump; the runtime role must exist on the target server
(`hrctl tenant ...` / the provisioning docs create it).

### AWS RDS

Restore a snapshot or point-in-time to a NEW instance (RDS console -> Snapshots -> Restore), then change the connection
strings to it. For S3 uploads, restore object versions if needed.

## Check a backup is usable

```powershell
pg_restore --list backups\hrms-app-YYYYMMDD-HHMM.dump | Select-String "TABLE DATA" | Measure-Object
```
(Last check: 150 tables listed in `hrms-app-20260927-1600.dump`.)
