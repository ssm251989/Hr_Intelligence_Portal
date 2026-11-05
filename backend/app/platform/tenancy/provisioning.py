"""Tenant provisioning & lifecycle (docs/HRMS_COMPLETE_SPEC.txt Part 13 section B), shared
by the `hrctl` CLI and the Super-Admin console.

`create_tenant()` steps (each recorded as a `tenant_provisioning_jobs` row):
  validate -> control-plane row (provisioning) -> database (dedicated: CREATE DATABASE +
  grants; shared_rls: the installation's own DB) -> migrations (alembic -x url=...) ->
  DSN secrets (control-plane SecretStore) -> platform defaults (settings/name, system roles,
  master types, default pipeline) -> optional config pack -> first admin + one-time
  set-password invite -> domain -> active.

Destructive operations are two-step by construction: `delete_tenant()` returns a report
unless called with `confirm=<slug>`, and even then only marks the tenant deleted and
detaches its domains -- dropping a dedicated database additionally needs
`drop_database=True` (the CLI's explicit `--drop-database`).
"""

import json
import re
import secrets
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text as sa_text

from app.core.config import settings
from app.platform.secrets.store import get_secret_store
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import (
    ControlPlaneSecret,
    ControlPlaneSecretScope,
    Plan,
    Tenant,
    TenantDomain,
    TenantProvisioningJob,
)

CONTROL_PLANE_SECRET_SCOPE = "control_plane"
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
BACKEND_ROOT = Path(__file__).resolve().parents[3]


class ProvisioningError(Exception):
    pass


@dataclass
class Report:
    steps: list[dict] = field(default_factory=list)

    def add(self, step: str, status: str, detail: str = "") -> None:
        self.steps.append({"step": step, "status": status, "detail": detail})

    def as_dict(self) -> dict:
        return {"steps": self.steps, "ok": all(s["status"] in ("ok", "planned", "skipped") for s in self.steps)}


# ---- DSN helpers ----


def _with_database(dsn: str, database: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _username(dsn: str) -> str:
    return urlparse(dsn).username or ""


def _store(cp_db):
    return get_secret_store(cp_db, ControlPlaneSecret, ControlPlaneSecretScope, CONTROL_PLANE_SECRET_SCOPE)


def put_or_rotate(store, ref: str, value: str, *, created_by: str = "hrctl") -> None:
    """Idempotent secret write -- re-running a half-finished provisioning must not fail on
    a secret the first attempt already stored."""
    from app.platform.secrets.store import SecretAlreadyExistsError

    try:
        store.put(ref, value, created_by=created_by)
    except SecretAlreadyExistsError:
        store.rotate(ref, value, created_by=created_by)


def runtime_dsn_ref(tenant_id) -> str:
    return "tenant-1-db-dsn" if tenant_id == TENANT_1_ID else f"tenant-{tenant_id}-db-dsn"


def admin_dsn_ref(tenant_id) -> str:
    return f"tenant-{tenant_id}-admin-dsn"


def admin_dsn_for(cp_db, tenant: Tenant) -> str:
    """Migrations need the admin (DDL) DSN. Tenant #1 and every shared_rls tenant live in
    this installation's own database."""
    if tenant.id == TENANT_1_ID or tenant.isolation == "shared_rls":
        return settings.DATABASE_URL
    return _store(cp_db).get(admin_dsn_ref(tenant.id))


def run_migrations(admin_dsn: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={admin_dsn}", "upgrade", "head"],
        cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        raise ProvisioningError(f"alembic upgrade failed: {result.stderr[-2000:]}")
    return result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "up to date"


def _grant_runtime_role(admin_dsn: str, database: str) -> None:
    role = _username(settings.APP_DATABASE_URL)
    if not role or role == _username(settings.DATABASE_URL):
        return
    engine = create_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sa_text(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"'))
        conn.execute(sa_text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        conn.execute(sa_text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        conn.execute(sa_text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
        conn.execute(sa_text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'))
        conn.execute(sa_text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{role}"'))
    engine.dispose()


def _job(cp_db, tenant_id, step: str, status: str, log: str = "") -> None:
    cp_db.add(TenantProvisioningJob(tenant_id=tenant_id, step=step, status=status, log=log[:4000]))
    cp_db.commit()


def tenant_session(tenant: Tenant):
    """A session on the tenant's own database with the runtime (RLS-subject) role."""
    from sqlalchemy.orm import sessionmaker

    cp_db = ControlPlaneSessionLocal()
    try:
        dsn = settings.APP_DATABASE_URL if tenant.isolation == "shared_rls" or tenant.id == TENANT_1_ID else _store(cp_db).get(runtime_dsn_ref(tenant.id))
    finally:
        cp_db.close()
    import app.core.database  # noqa: F401 -- its Session "after_begin" hook applies SET LOCAL app.tenant_id to this session too

    engine = create_engine(dsn)
    return sessionmaker(bind=engine)()


# ---- create ----


def create_tenant(
    *, slug: str, name: str, isolation: str = "dedicated_db", region: str = "ap-south-1", plan_code: Optional[str] = None,
    admin_email: Optional[str] = None, domain: Optional[str] = None, config_pack: Optional[dict] = None, dry_run: bool = False,
    notify: Callable[[str], None] = print, tenant_id: Optional[uuid.UUID] = None,
) -> dict:
    """`tenant_id` is only passed by import_tenant() -- a moved client keeps its id, so
    every tenant_id column in its exported rows still matches."""
    report = Report()
    if not SLUG_PATTERN.match(slug):
        raise ProvisioningError("slug must be 3-63 chars, lowercase letters/digits/hyphens, starting with a letter")
    if isolation not in ("dedicated_db", "shared_rls"):
        raise ProvisioningError("isolation is dedicated_db or shared_rls")
    if region not in settings.ALLOWED_REGIONS:
        raise ProvisioningError(f"region {region!r} is not allowed here (data residency: {', '.join(settings.ALLOWED_REGIONS)})")
    database = f"hrms_t_{slug.replace('-', '_')}"

    cp_db = ControlPlaneSessionLocal()
    try:
        if cp_db.query(Tenant).filter(Tenant.slug == slug).first() is not None:
            raise ProvisioningError(f"a tenant with slug {slug!r} already exists")
        if domain and cp_db.query(TenantDomain).filter(TenantDomain.host == domain.lower()).first() is not None:
            raise ProvisioningError(f"domain {domain!r} is already registered")
        plan = cp_db.query(Plan).filter(Plan.code == plan_code).first() if plan_code else None
        if plan_code and plan is None:
            raise ProvisioningError(f"unknown plan {plan_code!r}")
        report.add("validate", "ok", f"slug={slug} isolation={isolation} region={region}")

        if dry_run:
            report.add("control_plane_row", "planned")
            report.add("database", "planned", f"CREATE DATABASE {database}" if isolation == "dedicated_db" else "shared installation database (RLS)")
            report.add("migrations", "planned", "alembic upgrade head")
            report.add("defaults", "planned", "org name, system roles, master types, default pipeline")
            report.add("config_pack", "planned" if config_pack else "skipped")
            report.add("first_admin", "planned" if admin_email else "skipped")
            report.add("domain", "planned" if domain else "skipped", domain or "")
            return {**report.as_dict(), "dry_run": True}

        tenant = Tenant(id=tenant_id or uuid.uuid4(), slug=slug, display_name=name, status="provisioning", isolation=isolation, region=region,
                        data_residency="IN", plan_id=plan.id if plan else None)
        cp_db.add(tenant)
        cp_db.commit()
        report.add("control_plane_row", "ok", str(tenant.id))
        _job(cp_db, tenant.id, "control_plane_row", "succeeded")

        store = _store(cp_db)
        if isolation == "dedicated_db":
            admin_engine = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                exists = conn.execute(sa_text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": database}).scalar()
                if not exists:
                    conn.execute(sa_text(f'CREATE DATABASE "{database}"'))
            admin_engine.dispose()
            tenant_admin_dsn = _with_database(settings.DATABASE_URL, database)
            tenant_runtime_dsn = _with_database(settings.APP_DATABASE_URL, database)
            put_or_rotate(store, admin_dsn_ref(tenant.id), tenant_admin_dsn)
            report.add("database", "ok", database)
        else:
            tenant_admin_dsn, tenant_runtime_dsn = settings.DATABASE_URL, settings.APP_DATABASE_URL
            report.add("database", "ok", "shared installation database")
        put_or_rotate(store, runtime_dsn_ref(tenant.id), tenant_runtime_dsn)
        tenant.db_dsn_secret_ref = runtime_dsn_ref(tenant.id)
        cp_db.commit()
        _job(cp_db, tenant.id, "database", "succeeded")

        notify("running migrations ...")
        report.add("migrations", "ok", run_migrations(tenant_admin_dsn))
        if isolation == "dedicated_db":
            _grant_runtime_role(tenant_admin_dsn, database)
        _job(cp_db, tenant.id, "migrations", "succeeded")

        invite_token = _seed_tenant(tenant, name=name, admin_email=admin_email, config_pack=config_pack, report=report)
        _job(cp_db, tenant.id, "seed", "succeeded")

        if domain:
            cp_db.add(TenantDomain(tenant_id=tenant.id, host=domain.lower(), is_primary=True))
            report.add("domain", "ok", domain.lower())
        tenant.status = "active"
        cp_db.commit()
        _job(cp_db, tenant.id, "activate", "succeeded")
        report.add("activate", "ok")
        return {**report.as_dict(), "tenant_id": str(tenant.id), "admin_invite_token": invite_token}
    except ProvisioningError:
        raise
    except Exception as exc:
        report.add("error", "failed", f"{type(exc).__name__}: {exc}")
        raise ProvisioningError(json.dumps(report.as_dict())) from exc
    finally:
        cp_db.close()


def _seed_tenant(tenant: Tenant, *, name: str, admin_email: Optional[str], config_pack: Optional[dict], report: Report) -> Optional[str]:
    from app.core.security import hash_password
    from app.models.user import User
    from app.platform.iam.action_tokens import create_action_token
    from app.platform.iam.roles import bridge_single_user, sync_system_roles
    from app.platform.metadata.masters import register_master_types
    from app.platform.settings.bootstrap_definitions import register_all as register_settings
    from app.platform.settings.resolver import SettingsService

    register_settings()
    ctx = TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)
    invite_token = None
    with tenant_context(tenant.id):
        db = tenant_session(tenant)
        try:
            service = SettingsService(db)
            for key in ("org.display_name", "org.legal_name"):
                service.set(key, name, scope_type="tenant", scope_id=None, actor="hrctl", tenant=ctx)
            sync_system_roles(db, ctx)
            register_master_types(db)
            try:
                from app.recruitment.pipeline import seed_default_template

                seed_default_template(db, ctx)
            except Exception as exc:  # the pipeline seed is a convenience, never a blocker
                report.add("default_pipeline", "skipped", type(exc).__name__)
            report.add("defaults", "ok", "org name, system roles, master types")
            if config_pack:
                from app.platform.config_pack import import_pack

                result = import_pack(db, ctx, config_pack, actor="hrctl")
                report.add("config_pack", "ok", json.dumps(result["tables"])[:500])
            if admin_email:
                user = db.query(User).filter(User.email == admin_email.lower()).first()
                if user is None:
                    user = User(tenant_id=tenant.id, email=admin_email.lower(), hashed_password=hash_password(secrets.token_urlsafe(32)), full_name=admin_email, role="admin")
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                bridge_single_user(db, ctx, user)
                invite_token = create_action_token(db, ctx, entity_type="user", entity_id=user.id, action="set_password", created_by="hrctl", ttl_days=7).token
                _send_invite(db, ctx, admin_email, invite_token, report)
        finally:
            db.close()
    return invite_token


def _send_invite(db, ctx: TenantContext, email: str, token: str, report: Report) -> None:
    """Through the platform system mailbox (`email.outbound.system`) using the tenant's
    `platform.admin_invite` template. No mailbox/template yet (a brand-new tenant usually
    has neither) -> the one-time link is returned to the operator instead."""
    from app.platform.comms.service import send

    link = f"{settings.FRONTEND_URL.rstrip('/')}/set-password?token={token}"
    try:
        message = send(db, ctx, template_key="platform.admin_invite", to=[email], ctx={"link": link}, purpose="email.outbound.system")
        report.add("first_admin", "ok" if message.status in ("sent", "queued") else "skipped", f"invite {message.status}; link: {link}")
    except Exception as exc:
        report.add("first_admin", "ok", f"created; email not sent ({type(exc).__name__}) -- share this one-time link: {link}")


# ---- lifecycle ----


def set_status(slug: str, status: str, *, reason: Optional[str] = None) -> dict:
    if status not in ("active", "suspended", "archived"):
        raise ProvisioningError("status is active, suspended or archived")
    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None:
            raise ProvisioningError(f"no tenant {slug!r}")
        if tenant.status == "deleted":
            raise ProvisioningError("a deleted tenant cannot change status")
        tenant.status = status
        tenant.suspended_reason = reason if status == "suspended" else None
        cp_db.commit()
        from app.platform.tenancy.middleware import clear_single_tenant_cache

        clear_single_tenant_cache()
        return {"slug": slug, "status": status}
    finally:
        cp_db.close()


def delete_tenant(slug: str, *, confirm: Optional[str] = None, drop_database: bool = False) -> dict:
    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None:
            raise ProvisioningError(f"no tenant {slug!r}")
        if tenant.id == TENANT_1_ID:
            raise ProvisioningError("tenant #1 (this installation's original tenant) cannot be deleted with hrctl")
        counts = _row_counts(cp_db, tenant)
        plan = {"tenant": slug, "isolation": tenant.isolation, "row_counts": counts,
                "will": ["mark tenant deleted", "detach domains"] + (["DROP DATABASE"] if drop_database and tenant.isolation == "dedicated_db" else [])}
        if confirm != slug:
            return {"dry_run": True, **plan, "hint": f"re-run with --confirm {slug} to proceed"}
        cp_db.query(TenantDomain).filter(TenantDomain.tenant_id == tenant.id).delete()
        tenant.status = "deleted"
        cp_db.commit()
        if drop_database and tenant.isolation == "dedicated_db":
            database = urlparse(admin_dsn_for(cp_db, tenant)).path.lstrip("/")
            engine = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
            with engine.connect() as conn:
                conn.execute(sa_text(f'DROP DATABASE IF EXISTS "{database}"'))
            engine.dispose()
        return {"dry_run": False, **plan}
    finally:
        cp_db.close()


def _tenant_tables():
    import app.models  # noqa: F401
    from app.core.database import Base

    return [t for t in Base.metadata.sorted_tables if "tenant_id" in t.c]


def _row_counts(cp_db, tenant: Tenant) -> dict:
    engine = create_engine(admin_dsn_for(cp_db, tenant))
    counts = {}
    with engine.connect() as conn:
        for table in _tenant_tables():
            counts[table.name] = conn.execute(sa_text(f'SELECT count(*) FROM "{table.name}" WHERE tenant_id = :t'), {"t": str(tenant.id)}).scalar()
    engine.dispose()
    return {k: v for k, v in counts.items() if v}


# ---- export / import (move a client between installations) ----


def _alembic_revision(dsn: str) -> Optional[str]:
    engine = create_engine(dsn)
    try:
        with engine.connect() as conn:
            return conn.execute(sa_text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def export_tenant(slug: str, out_path: str) -> dict:
    """Every tenant-owned row, one JSONL file per table, plus a manifest. Secrets travel
    ENCRYPTED under this installation's master key -- the target re-keys or re-enters them
    (see docs/ops/runbook.md). Uploaded files live in object storage under
    tenants/{tenant_id}/ and are copied with the storage tool, not inside this archive."""
    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None:
            raise ProvisioningError(f"no tenant {slug!r}")
        dsn = admin_dsn_for(cp_db, tenant)
        domains = [d.host for d in cp_db.query(TenantDomain).filter(TenantDomain.tenant_id == tenant.id).all()]
    finally:
        cp_db.close()
    engine = create_engine(dsn)
    counts = {}
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive, engine.connect() as conn:
        for table in _tenant_tables():
            rows = conn.execute(table.select().where(table.c.tenant_id == tenant.id)).mappings().all()
            if not rows:
                continue
            counts[table.name] = len(rows)
            archive.writestr(f"tables/{table.name}.jsonl", "\n".join(json.dumps(dict(r), default=str) for r in rows))
        manifest = {"format": "hrms-tenant-export/1", "tenant": {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.display_name, "region": tenant.region},
                    "domains": domains, "alembic_revision": _alembic_revision(dsn), "tables": counts, "exported_at": datetime.now(timezone.utc).isoformat()}
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    engine.dispose()
    return manifest


def import_tenant(archive_path: str, *, isolation: str = "dedicated_db", region: Optional[str] = None, dry_run: bool = False) -> dict:
    """Creates the tenant in THIS installation (same id and slug) and loads every row, in
    FK order, idempotently (ON CONFLICT DO NOTHING). Refuses a schema-revision mismatch --
    migrate one side first."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        info = manifest["tenant"]
        cp_db = ControlPlaneSessionLocal()
        try:
            existing = cp_db.query(Tenant).filter(Tenant.slug == info["slug"]).first()
        finally:
            cp_db.close()
        if dry_run:
            return {"dry_run": True, "manifest": manifest, "tenant_exists_here": existing is not None}
        if existing is None:
            create_tenant(slug=info["slug"], name=info["name"], isolation=isolation, region=region or info.get("region") or "ap-south-1",
                          notify=lambda _m: None, tenant_id=uuid.UUID(info["id"]))
        cp_db = ControlPlaneSessionLocal()
        try:
            tenant = cp_db.query(Tenant).filter(Tenant.slug == info["slug"]).first()
            dsn = admin_dsn_for(cp_db, tenant)
        finally:
            cp_db.close()
        local_revision = _alembic_revision(dsn)
        if manifest.get("alembic_revision") != local_revision:
            raise ProvisioningError(f"schema mismatch: export is at {manifest.get('alembic_revision')}, this installation at {local_revision}")
        engine = create_engine(dsn)
        loaded = {}
        with engine.begin() as conn:
            for table in _tenant_tables():
                name = f"tables/{table.name}.jsonl"
                if name not in archive.namelist():
                    continue
                rows = [json.loads(line) for line in archive.read(name).decode("utf-8").splitlines() if line.strip()]
                for row in rows:
                    conn.execute(pg_insert(table).values(**{k: v for k, v in row.items() if k in table.c}).on_conflict_do_nothing())
                loaded[table.name] = len(rows)
        engine.dispose()
    return {"dry_run": False, "tenant": info["slug"], "loaded": loaded}


# ---- migrate all ----


def migrate_all(*, parallel: int = 1, notify: Callable[[str], None] = print) -> list[dict]:
    """One `alembic upgrade head` per distinct tenant database (shared_rls tenants share
    the installation DB, migrated once). Deleted/archived tenants are skipped."""
    from concurrent.futures import ThreadPoolExecutor

    cp_db = ControlPlaneSessionLocal()
    try:
        tenants = cp_db.query(Tenant).filter(Tenant.status.in_(("active", "suspended", "provisioning"))).all()
        # The installation's own database is always a target -- on a first install there
        # are no tenants yet, but tenant #1 / shared tenants will live there.
        targets: dict[str, list[str]] = {settings.DATABASE_URL: ["(installation)"]}
        for tenant in tenants:
            targets.setdefault(admin_dsn_for(cp_db, tenant), []).append(tenant.slug)
    finally:
        cp_db.close()

    def _one(item):
        dsn, slugs = item
        try:
            return {"tenants": slugs, "status": "ok", "detail": run_migrations(dsn)}
        except ProvisioningError as exc:
            return {"tenants": slugs, "status": "failed", "detail": str(exc)[:500]}

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results = list(pool.map(_one, targets.items()))
    for r in results:
        notify(f"{','.join(r['tenants'])}: {r['status']}")
    return results
