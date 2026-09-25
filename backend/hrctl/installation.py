"""hrctl installation init -- first-install database bootstrap for a managed Postgres (RDS)
where there is no docker-entrypoint init script: creates the control-plane database and the
NON-superuser runtime role the app connects as (credentials taken from APP_DATABASE_URL),
with default privileges on both databases. Idempotent -- safe to run before every
migration (the ECS migrate task and Helm hook do exactly that).

    python -m hrctl.installation init
"""

import argparse
import sys
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


def _grant_defaults(admin_dsn: str, role: str) -> None:
    engine = create_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{role}"'))
    engine.dispose()


def init() -> None:
    from app.core.config import settings

    runtime = urlparse(settings.APP_DATABASE_URL)
    admin = urlparse(settings.DATABASE_URL)
    control_plane_db = urlparse(settings.CONTROL_PLANE_DATABASE_URL).path.lstrip("/")
    if not runtime.username or runtime.username == admin.username:
        raise SystemExit("APP_DATABASE_URL must use a separate non-superuser role (RLS does not apply to superusers)")

    engine = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": runtime.username}).scalar():
            # Postgres quotes the identifier/password itself (format %I/%L) -- never Python string-interpolated
            statement = conn.execute(text("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', :r, :p)"), {"r": runtime.username, "p": runtime.password}).scalar()
            conn.execute(text(statement))
            print(f"created role {runtime.username}")
        if control_plane_db and not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": control_plane_db}).scalar():
            conn.execute(text(f'CREATE DATABASE "{control_plane_db}"'))
            print(f"created database {control_plane_db}")
        for database in {admin.path.lstrip("/"), control_plane_db} - {""}:
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO "{runtime.username}"'))
    engine.dispose()
    _grant_defaults(settings.DATABASE_URL, runtime.username)
    _grant_defaults(settings.CONTROL_PLANE_DATABASE_URL, runtime.username)
    print("installation databases ready")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl installation")
    parser.add_argument("command", choices=("init",))
    parser.parse_args(argv)
    init()
    return 0


if __name__ == "__main__":
    sys.exit(main())
