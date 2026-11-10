"""The installation steps, in order. Every step is safe to run again (an interrupted install is
simply started again), reports progress through `say`, and fails with a plain message.

    1 postgres   connect as the PostgreSQL admin
    2 databases  the app login (hr_app, never a superuser: row-level security needs that) with the
                 chosen password, and the two databases
    3 env        backend/.env (URLs encoded, keys generated once and never replaced)
    4 migrate    control plane, then company tables (repairs a database stamped "up to date" but empty)
    5 grants     the app login may read/write every table
    6 company    the company row + its name
    7 base data  master lists, approval workflows, hiring pipeline
    8 admin      the first administrator (password stored only as a bcrypt hash)
    9 modules    request activation from CTD Techs (normal) or switch on (dev / CTD-internal)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import create_engine, text

from app.platform.install import envfile
from app.platform.install.validate import Answers, check

BACKEND = Path(__file__).resolve().parents[3]
STEPS = ("postgres", "databases", "env", "migrate", "grants", "company", "base_data", "admin", "modules")


class StepFailed(RuntimeError):
    def __init__(self, step: str, message: str, detail: str = ""):
        super().__init__(f"{step}: {message}")
        self.step, self.message, self.detail = step, message, detail


def _admin_dsn(a: Answers, database: str = "postgres") -> str:
    return envfile.dsn(a.pg_superuser, a.pg_superuser_password, a.pg_host, a.pg_port, database)


def _plain(exc: Exception) -> str:
    msg = str(exc)
    if "password authentication failed" in msg:
        return "The PostgreSQL password is not right for user '{}'."
    if "Connection refused" in msg or "could not connect" in msg or "timeout expired" in msg:
        return "PostgreSQL is not running or not reachable at that address/port. Start the PostgreSQL service and try again."
    if "does not exist" in msg and "role" in msg:
        return "That PostgreSQL user does not exist."
    return msg.splitlines()[0][:300]


def step_postgres(a: Answers) -> dict:
    try:
        with create_engine(_admin_dsn(a), isolation_level="AUTOCOMMIT").connect() as c:
            version = c.execute(text("SHOW server_version")).scalar()
            superuser = c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
    except Exception as exc:  # noqa: BLE001
        raise StepFailed("postgres", _plain(exc).format(a.pg_superuser)) from exc
    major = int(str(version).split(".")[0])
    if major < 13:
        raise StepFailed("postgres", f"PostgreSQL {version} is too old; version 13 or newer is needed (16 recommended).")
    if not superuser:
        raise StepFailed("postgres", f"'{a.pg_superuser}' is not a PostgreSQL superuser; use the 'postgres' admin login.")
    return {"version": version}


def step_databases(a: Answers) -> dict:
    eng = create_engine(_admin_dsn(a), isolation_level="AUTOCOMMIT")
    done = []
    with eng.connect() as c:
        verb = "ALTER" if c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": a.app_db_user}).scalar() else "CREATE"
        # PostgreSQL quotes the name and password itself (%I / %L) -- never Python string building
        sql = c.execute(text(f"SELECT format('{verb} ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', :r, :p)"),
                        {"r": a.app_db_user, "p": a.app_db_password}).scalar()
        c.execute(text(sql))
        done.append(f"{verb.lower()}d login {a.app_db_user}")
        for db in (a.db_name, a.control_plane_db_name):
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db}).scalar():
                c.execute(text(f'CREATE DATABASE "{db}"'))
                done.append(f"created database {db}")
            c.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO "{a.app_db_user}"'))
    eng.dispose()
    return {"done": done}


def env_values(a: Answers, existing: dict) -> dict[str, str]:
    d = lambda user, pw, db: envfile.dsn(user, pw, a.pg_host, a.pg_port, db)  # noqa: E731
    extra = {"APP_BASE_URL": a.app_base_url} if a.app_base_url else {}
    return {**extra,
        "DATABASE_URL": d(a.pg_superuser, a.pg_superuser_password, a.db_name),
        "CONTROL_PLANE_DATABASE_URL": d(a.pg_superuser, a.pg_superuser_password, a.control_plane_db_name),
        "APP_DATABASE_URL": d(a.app_db_user, a.app_db_password, a.db_name),
        "APP_CONTROL_PLANE_DATABASE_URL": d(a.app_db_user, a.app_db_password, a.control_plane_db_name),
        "SECRET_BACKEND": "db_encrypted",
        "TENANCY_MODE": "single",
        "FRONTEND_URL": a.frontend_url,
        # generated once: replacing MASTER_KEY would make every stored secret unreadable
        "MASTER_KEY": existing.get("MASTER_KEY") or envfile.new_master_key(),
        "SECRET_KEY": existing.get("SECRET_KEY") or envfile.new_secret_key(),
    }


def step_env(a: Answers, env_path: Path) -> dict:
    if not env_path.exists() and (BACKEND / ".env.example").exists():
        env_path.write_text((BACKEND / ".env.example").read_text(encoding="utf-8-sig"), encoding="utf-8", newline="\n")
    existing = {k: v for k, v in envfile.read(env_path).items() if v} if env_path.exists() else {}
    values = env_values(a, existing)
    envfile.write(env_path, values)
    return {"path": str(env_path), "kept_keys": [k for k in ("MASTER_KEY", "SECRET_KEY") if existing.get(k)]}


def _run(args: list[str], env: dict, step: str, stdin: Optional[str] = None) -> str:
    proc = subprocess.run([sys.executable, *args], cwd=BACKEND, env=env, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
        raise StepFailed(step, (tail[-1] if tail else "failed")[:300], "\n".join(tail))
    return proc.stdout


def _child_env(env_path: Path) -> dict:
    """The subprocesses read exactly this installation's values, never stale Windows variables."""
    env = {k: v for k, v in os.environ.items() if k not in envfile.read(env_path)}
    env.update({k: v for k, v in envfile.read(env_path).items() if v is not None})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def step_migrate(a: Answers, env: dict) -> dict:
    _run(["-m", "alembic", "-c", "alembic_control_plane.ini", "upgrade", "head"], env, "migrate")
    with create_engine(_admin_dsn(a, a.db_name)).connect() as c:
        stamped = c.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        tables = c.execute(text("SELECT to_regclass('public.job_roles')")).scalar()
    if stamped and not tables:  # "up to date" on paper but empty: start the chain again
        _run(["-m", "alembic", "stamp", "base"], env, "migrate")
    _run(["-m", "alembic", "upgrade", "head"], env, "migrate")
    return {"ok": True}


def step_grants(env: dict) -> dict:
    _run(["-m", "hrctl.installation", "init"], env, "grants")
    return {"ok": True}


def step_company(a: Answers, env: dict) -> dict:
    _run(["-m", "hrctl.tenant", "bootstrap-existing", "--slug", a.company_slug, "--name", a.company_name], env, "company")
    return {"slug": a.company_slug}


def step_base_data(env: dict) -> dict:
    for mod in ("hrctl.seed_masters", "hrctl.seed_workflows", "hrctl.seed_pipeline"):
        _run(["-m", mod], env, "base_data")
    return {"ok": True}


def step_admin(a: Answers, env: dict) -> dict:
    # the password goes through stdin, never the command line (visible in the process list)
    out = _run(["-m", "hrctl.setup", "_admin"], env, "admin",
               stdin=json.dumps({"email": a.admin_email.strip().lower(), "name": a.admin_name.strip(), "password": a.admin_password,
                                 "slug": a.company_slug}))
    return json.loads(out.strip().splitlines()[-1])


def step_modules(a: Answers, env: dict) -> dict:
    out = _run(["-m", "hrctl.setup", "_modules"], env, "modules",
               stdin=json.dumps({"email": a.admin_email.strip().lower(), "modules": a.modules, "activate": a.activate_modules, "slug": a.company_slug}))
    return json.loads(out.strip().splitlines()[-1])


def run(a: Answers, *, env_path: Optional[Path] = None, say: Callable[[str, str, dict], None] = lambda *_: None,
        only: Optional[tuple[str, ...]] = None) -> dict:
    """Validate, then run every step. Returns {step: result}. Raises InvalidInput / StepFailed."""
    check(a)
    env_path = Path(env_path or BACKEND / ".env")
    results: dict = {}
    for step in STEPS:
        if only and step not in only:
            continue
        say(step, "start", {})
        if step == "postgres":
            r = step_postgres(a)
        elif step == "databases":
            r = step_databases(a)
        elif step == "env":
            r = step_env(a, env_path)
        else:
            env = _child_env(env_path)
            r = {"migrate": lambda: step_migrate(a, env), "grants": lambda: step_grants(env), "company": lambda: step_company(a, env),
                 "base_data": lambda: step_base_data(env), "admin": lambda: step_admin(a, env), "modules": lambda: step_modules(a, env)}[step]()
        results[step] = r
        say(step, "done", r)
    return results
