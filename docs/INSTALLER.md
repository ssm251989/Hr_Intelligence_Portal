# Installing HR Automation - design (Parts 27-28)

Owner decision (2026-11-06): two ways for a client to get HR Automation, both ending in the same
first-run result -- databases, tables, company, first admin, modules requested -- with no manual
setup and passwords the client chooses.

| | Windows installer (on-prem) | Cloud sign-up (SaaS) |
|---|---|---|
| Client clicks | unzip `HR-Automation-x.y.z.zip`, double-click `HRAutomation.exe` | "Create my company" on the CTD Techs website |
| Runs where | the client's Windows PC / server | CTD Techs' server (AWS once access is given) |
| Database | PostgreSQL installed by the setup (or an existing one) | the platform's PostgreSQL; one database per company |
| Engine | `python -m app.platform.install --answers ... --json` | `provisioning.create_tenant(...)` + the same answer checks |
| Address | `http://<pc>:8080` (one port: API + web app) | `https://<company>.<platform-domain>` |
| Status | engine, setup screen, launcher, build script done; Windows test = Part 28 | Part 28 |

## The engine (done): `app/platform/install`

- **validate.py**: every typed value is checked first, and all problems come back together so a form can
  mark every field. Passwords are 10-128 characters with a letter and a digit. They may contain no line
  breaks, tabs or invisible characters, no leading or trailing spaces, and must not be the email.
  `@ # : / %` are allowed.
- **envfile.py**: builds the database URLs with the password URL-encoded and the psycopg2 driver named.
  - Writes `.env` atomically: a temp file is swapped in, one `KEY=value` per line, the person's other lines
    are kept and duplicate keys removed.
  - Reads the file back to prove every value, then makes it readable only by the app account.
- **provision.py**: 9 steps, each safe to run again:
  1. postgres (version ≥ 13, a superuser)
  2. app login `hr_app` (NOSUPERUSER NOBYPASSRLS, so row-level security applies) and 2 databases
  3. `.env` (MASTER_KEY and SECRET_KEY generated once, never replaced)
  4. migrations (repairs a database "stamped but empty")
  5. grants
  6. company
  7. base data
  8. first admin (bcrypt hash only)
  9. modules: an activation request to CTD Techs, or switched on with `activate_modules` for dev
- **CLI**: `python -m app.platform.install`. It works before `.env` exists, asks questions (passwords typed
  twice, hidden), or reads `--answers file.json` (`--delete-answers`, `--json` progress lines, `--check`).

Where each secret lives:

| Secret | Chosen by | Stored |
|---|---|---|
| Admin sign-in password | client | only as a bcrypt hash (cannot be read back; reset via Forgot password / admin) |
| App DB password (hr_app) | client | `backend/.env` (ACL: service account + Administrators) |
| PostgreSQL superuser password | client (new install) / existing | `backend/.env` `DATABASE_URL` (needed for upgrades) |
| MASTER_KEY, SECRET_KEY | generated | `backend/.env`; MASTER_KEY also shown once in the finish page for safe keeping (backup restore needs it) |
| Mailbox / API keys added later | client in Settings | encrypted in the database (envelope encryption under MASTER_KEY) |

## Windows package: unzip -> double-click (Part 28, owner decision 2026-11-06)

The client gets **one zip**. They unzip it and double-click **HRAutomation.exe**. Nothing else is
installed by hand.

```
HR-Automation-1.0.0.zip
  HR-Automation\
    HRAutomation.exe          launcher (Go, standard library only; asks for admin rights)
    README.txt, VERSION.txt
    runtime\python\          embeddable Python 3.13 + every package (python313._pth adds app\backend)
    runtime\pgsql\           PostgreSQL 16 binaries (bin, lib, share)
    runtime\winsw\           WinSW-x64.exe (runs the app as a Windows service)
    app\backend\             code (no .env, no uploads)
    app\frontend\dist\      built web app (VITE_API_BASE_URL=/_api)
```

**What happens when the client double-clicks HRAutomation.exe**

1. Windows asks "allow changes?" (administrator rights).
2. **First time:** the launcher starts the setup screen
   (`runtime\python\python.exe -m app.platform.install.wizard`).
   - It runs on `http://127.0.0.1:<random>/?t=<one-time token>`, so only this PC can reach it, and only
     with the token. It opens in the browser.
   - It asks for company, admin (name, email, password ×2), database (install new — default — or use an
     existing PostgreSQL), the app's database password ×2, install folder and port, plus an optional
     firewall rule.
   - Every field is checked by `validate.py` before anything happens. All problems show in red at once.
3. **Install** runs `windows.install`, showing each step:
   1. **files:** copies the package to `C:\Program Files\HR Automation`. `.env` and uploads are kept on
      a re-run.
   2. **postgres_server** (new database only): `initdb` with the chosen password (temp file, deleted at
      once, scram-sha-256). It uses port 5432 or the next free one, `listen_addresses=localhost`, and
      registers the service `HRAutomation-PostgreSQL` (automatic).
   3. **the engine:** runs with the installed Python — databases, `.env`, tables, company, base data,
      admin, modules requested.
   4. **service:** WinSW service `HRAutomation-App` runs `uvicorn app.web:app` on the chosen port
      (8080). It depends on PostgreSQL, restarts on failure, and logs to
      `%ProgramData%\HRAutomation\logs`.
   5. **finish:** optional firewall rule (private and domain networks), "HR Automation" shortcuts on the
      desktop and Start menu, and `%ProgramData%\HRAutomation\installed.json`.
4. **Done:** "Open HR Automation" goes to `http://localhost:8080`, where the admin signs in.
5. **Later double-clicks:** the launcher starts both services if they're stopped and opens the app.
   - A newer package shows "run with --setup to upgrade". The upgrade flow comes later (backup first,
     then the same steps; it's safe to re-run).

**One port** (`app/web.py`): `/_api/*` is the API, the same as the nginx set-up, so tenant Host headers
and `APP_BASE_URL` links work. `/assets` holds the web app files, and everything else returns
`index.html`.

**Building the zip** (CTD Techs, on a Windows build PC, once per release):
`powershell -ExecutionPolicy Bypass -File installer\build_zip.ps1 -Version 1.0.0`. It produces
`installer\build\HR-Automation-1.0.0.zip` plus a `.sha256` file. It needs Python 3.13, Node 20+ and
internet access on the build PC only.

Tested in the cloud (Linux): the setup screen (token, checks, install, progress), the "existing
PostgreSQL" path end to end, the "new PostgreSQL" step (chosen password works, re-run safe, port 5432
busy → 5433), and the one-port app (`/jobs` → web app, `/_api` login 200). Still to test on a clean
Windows PC: the Windows services, firewall and shortcuts (PART28 28.4).

## Cloud sign-up (Part 28)

1. **Website form:** company, short name (becomes `<slug>.<domain>`), admin name, email, password (the
   same `validate.py` rules) and the modules wanted. It is protected by a captcha, a rate limit and
   reserved slugs.
2. **Email check:** a one-time link (30 min) confirms the email before anything is created.
3. **Provisioning job:** `provisioning.create_tenant` creates the company database (dedicated_db) and
   runs migrations, grants, seed, admin (with the chosen password, hashed), modules requested and the
   tenant domain. A progress page shows each step; on failure a person at CTD Techs is told and the
   client sees "We're finishing your setup - we'll email you".
4. **Activation:** CTD Techs approves the module request (existing activation flow), then a welcome
   email is sent with the sign-in link.

Needs before go-live: hosting (AWS: RDS PostgreSQL, ECS/EC2, S3 for uploads), a wildcard DNS name + TLS
certificate, and the platform mailbox (`PLATFORM_SMTP_*`).
