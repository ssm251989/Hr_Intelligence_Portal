"""Clear test data and keep the setup (owner request 2026-10-04).

    .venv/Scripts/python.exe -m hrctl.data reset --keep-setup --dry-run      (default: shows what would go)
    .venv/Scripts/python.exe -m hrctl.data reset --keep-setup --confirm      (backup first, then one transaction)

CLEARED for CTD Techs (the installation owner): jobs, applications, candidates (incl. Recycle bin),
their files, scores / AI results, shortlists, interviews, negotiation / confirmation tokens,
candidate emails, message log + in-app notifications, salary / document / BGV / offer / joining
records, onboarding + pre-joiners, GenAI usage, idempotency + geo caches, demo ("Demo - ") records,
audit entries of the cleared records -- and every row that points at a cleared row (found from the
foreign keys, so nothing is left orphaned). The demo companies (any company other than CTD Techs)
are removed entirely, with their activation requests.

KEPT: company profile, branding/logo (uploads/media), offices, users + roles + logins, mailbox and
other connections (+ secrets), templates, scoring rules (company level), hiring stages, salary
bands, department budgets (their "used" amount comes from commitments, which are cleared),
interviewer list + availability + pools (unlinked from deleted jobs), module status, approver list,
all settings.

Never drops a table or runs a downgrade. Refuses when ENV=production. --confirm always takes a
backup first (pg_dump of both databases + a zip of uploads/) into backups/ and stops if it fails.
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
UPLOADS = BACKEND / "uploads"
FILE_FOLDERS = ("resumes", "candidate-photos", "bgv", "joining-docs", "salary-payslips", "imports", "onboarding")  # media is KEPT

# fully cleared for the owner company (+ everything that points at them)
CLEAR_ALL = (
    "job_roles", "candidates", "applications", "agency_job_assignments", "candidate_documents", "bgv_documents",
    "candidate_removal_runs", "interviews", "negotiation_tokens", "interview_confirmation_tokens", "jd_screenings",
    "jd_screening_results", "offers", "preboarding_cases", "preboarding_documents", "onboarding_plans", "onboarding_tasks",
    "hr_inbound_emails", "outbound_messages", "ai_usage_records", "ai_decision_log", "score_recalc_runs", "idempotency_keys",
    "geo_cache", "consent_records", "user_celebrations", "copilot_conversations", "copilot_messages", "copilot_drafts",
    "agent_suggestions", "data_principal_requests", "budget_commitments",
)
# only some rows (test / demo ones)
CLEAR_WHERE = {
    "action_tokens": "entity_type <> 'user'",  # candidate forms / status pages; users' set-password links stay
    "employees": "status = 'pre_hire' or first_name like 'Demo -%'",  # pre-joiners from onboarding + demo people
    "recruitment_agencies": "name like 'Demo -%'",
}
# kept tables: a pointer to a cleared row is emptied (set NULL) instead of deleting the kept row
KEEP_NULLIFY = {"interviewer_pools", "users", "scoring_rule_sets_company", "pipeline_templates", "workflow_definitions",
                "message_templates", "recruitment_agencies", "departments", "positions", "locations", "legal_entities"}
# kept tables whose rows that point at a cleared row ARE deleted (they belong to the cleared record)
DEPENDENT_DELETE_OK = {"scoring_rule_sets"}  # per-job rule sets go with their job; company-level ones stay
# never touched, whatever points where
NEVER = {"alembic_version", "setting_values", "setting_value_history", "company_modules", "tenant_media", "brand_themes",
         "connections", "connection_routes", "secrets", "secret_scopes", "users", "roles", "role_assignments", "hr_integrations",
         "interviewer_availability", "master_types", "master_values", "sequences", "department_budgets", "user_devices",
         "refresh_tokens", "user_integrations", "local_import_settings", "interview_scheduling_settings"}


class Refused(SystemExit):
    pass


def _engine(url):
    from sqlalchemy import create_engine

    return create_engine(url)


def _fk_graph(conn):
    """[(child_table, child_col, parent_table, parent_col, nullable)] for single-column FKs."""
    from sqlalchemy import text

    rows = conn.execute(text("""
        select c.relname, a.attname, p.relname, pa.attname, not a.attnotnull
        from pg_constraint k
        join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid
        join pg_attribute a on a.attrelid = k.conrelid and a.attnum = k.conkey[1]
        join pg_attribute pa on pa.attrelid = k.confrelid and pa.attnum = k.confkey[1]
        join pg_namespace n on n.oid = c.relnamespace
        where k.contype = 'f' and n.nspname = 'public' and array_length(k.conkey, 1) = 1
    """)).all()
    return [tuple(r) for r in rows]


def _has_col(conn, table, col):
    from sqlalchemy import text

    return conn.execute(text("select 1 from information_schema.columns where table_schema='public' and table_name=:t and column_name=:c"),
                        {"t": table, "c": col}).first() is not None


def _tables(conn):
    from sqlalchemy import text

    return [r[0] for r in conn.execute(text("select tablename from pg_tables where schemaname='public'")).all()]


def plan(conn, owner_id: str, other_tenant_ids: list[str], extra_employees: tuple = ()) -> dict:
    """Fills temp tables _del_<table>(id) with the rows to delete; returns counts. Read-only otherwise."""
    from sqlalchemy import text

    tables = set(_tables(conn))
    graph = _fk_graph(conn)
    marked: dict[str, int] = {}
    nullify: list[tuple] = []

    def ensure(t):
        idtype = conn.execute(text("select format_type(a.atttypid, a.atttypmod) from pg_attribute a where a.attrelid = cast(:t as regclass) and a.attname = 'id'"),
                              {"t": f'public."{t}"'}).scalar()
        conn.execute(text(f'create temp table if not exists "_del_{t}" (id {idtype} primary key) on commit drop'))

    def add(t, where, params=None):
        if t not in tables or not _has_col(conn, t, "id"):
            return 0
        ensure(t)
        n = conn.execute(text(f'insert into "_del_{t}" select id from "{t}" where {where} on conflict do nothing'), params or {}).rowcount
        return n

    # 1. starting points (owner company)
    for t in CLEAR_ALL:
        if t in tables:
            where = "tenant_id = cast(:o as uuid)" if _has_col(conn, t, "tenant_id") else "true"
            add(t, where, {"o": owner_id})
    for t, cond in CLEAR_WHERE.items():
        if t in tables:
            add(t, f"tenant_id = cast(:o as uuid) and ({cond})", {"o": owner_id})
    # 1b. employee records named on the command line (--also-employee "First Last"); their user logins are never touched
    for full in extra_employees:
        add("employees", "tenant_id = cast(:o as uuid) and trim(first_name || ' ' || coalesce(last_name, '')) = :n", {"o": owner_id, "n": full.strip()})
    # 2. other (demo) companies: everything
    for tid in other_tenant_ids:
        for t in tables:
            if t in ("alembic_version",) or not _has_col(conn, t, "tenant_id") or not _has_col(conn, t, "id"):
                continue
            add(t, "tenant_id = cast(:o as uuid)", {"o": tid})
    # 3. follow the foreign keys to a fixpoint
    changed = True
    while changed:
        changed = False
        for child, ccol, parent, pcol, nullable in graph:
            if pcol != "id" or not conn.execute(text("select to_regclass(:n)"), {"n": f"pg_temp._del_{parent}"}).scalar():
                continue
            if child in NEVER or child in KEEP_NULLIFY:
                continue
            if not _has_col(conn, child, "id"):
                continue
            n = add(child, f'"{ccol}" in (select id from "_del_{parent}")')
            if n:
                changed = True
    # 4. kept rows that point at cleared rows -> emptied
    for child, ccol, parent, pcol, nullable in graph:
        if pcol == "id" and (child in NEVER or child in KEEP_NULLIFY) and conn.execute(text("select to_regclass(:n)"), {"n": f"pg_temp._del_{parent}"}).scalar():
            del_child = conn.execute(text("select to_regclass(:n)"), {"n": f"pg_temp._del_{child}"}).scalar()
            extra = f' and id not in (select id from "_del_{child}")' if del_child and _has_col(conn, child, "id") else ""
            n = conn.execute(text(f'select count(*) from "{child}" where "{ccol}" in (select id from "_del_{parent}"){extra}')).scalar()
            if n:
                if not nullable:
                    raise Refused(f"Can't keep {child}: {n} row(s) must point at a cleared {parent} ({ccol} is required). Nothing was changed.")
                nullify.append((child, ccol, parent, n))
    split = {}
    for t in tables:
        if conn.execute(text("select to_regclass(:n)"), {"n": f"pg_temp._del_{t}"}).scalar():
            marked[t] = conn.execute(text(f'select count(*) from "_del_{t}"')).scalar()
            if marked[t] and _has_col(conn, t, "tenant_id"):
                own = conn.execute(text(f'select count(*) from "{t}" where id in (select id from "_del_{t}") and tenant_id = cast(:o as uuid)'), {"o": owner_id}).scalar()
                split[t] = {"ctd_techs": own, "demo_companies": marked[t] - own}
    # 5. audit entries of the cleared records
    ids_union = " union all ".join(f'select id::text from "_del_{t}"' for t in marked)
    audit = conn.execute(text(f"select count(*) from audit_log where entity_id::text in ({ids_union})")).scalar() if marked and "audit_log" in tables else 0
    demo_audit = sum(conn.execute(text("select count(*) from audit_log where tenant_id = cast(:o as uuid)"), {"o": tid}).scalar() for tid in other_tenant_ids)
    return {"delete": {t: n for t, n in sorted(marked.items()) if n}, "split": split, "nullify": nullify, "audit": audit, "demo_audit": demo_audit, "graph": graph}


def _order(tables: set, graph) -> list:
    """Children before parents (cycles: whatever is left, after nullable FKs inside it are emptied)."""
    deps = {t: set() for t in tables}
    for child, _c, parent, _p, _n in graph:
        if child in tables and parent in tables and child != parent:
            deps[parent].add(child)  # parent must wait for child
    order, done = [], set()
    while len(done) < len(tables):
        ready = [t for t in tables if t not in done and deps[t] <= done]
        if not ready:  # cycle
            ready = [min((t for t in tables if t not in done), key=lambda t: len(deps[t] - done))]
        for t in sorted(ready):
            order.append(t)
            done.add(t)
    return order


def execute(conn, owner_id, other_tenant_ids, p) -> dict:
    from sqlalchemy import text

    graph = p["graph"]
    tables = set(p["delete"])
    # kept rows: empty the pointers
    for child, ccol, parent, _n in p["nullify"]:
        conn.execute(text(f'update "{child}" set "{ccol}" = null where "{ccol}" in (select id from "_del_{parent}")'))
    # pointers between rows that are all being deleted (self-references / cycles): empty nullable ones first
    for child, ccol, parent, pcol, nullable in graph:
        if pcol == "id" and child in tables and parent in tables and nullable and child != parent or (child == parent and child in tables and nullable):
            conn.execute(text(f'update "{child}" set "{ccol}" = null where id in (select id from "_del_{child}") and "{ccol}" is not null'))
    ids_union = " union all ".join(f'select id::text from "_del_{t}"' for t in tables)
    audit = conn.execute(text(f"delete from audit_log where entity_id::text in ({ids_union})")).rowcount if tables else 0
    for tid in other_tenant_ids:
        audit += conn.execute(text("delete from audit_log where tenant_id = cast(:o as uuid)"), {"o": tid}).rowcount
    deleted = {}
    for t in _order(tables, graph):
        deleted[t] = conn.execute(text(f'delete from "{t}" where id in (select id from "_del_{t}")')).rowcount
    # serial id sequences of tables now empty
    for t in tables:
        for (col,) in conn.execute(text("select column_name from information_schema.columns where table_name=:t and column_default like 'nextval%'"), {"t": t}).all():
            if conn.execute(text(f'select count(*) from "{t}"')).scalar() == 0:
                conn.execute(text("select setval(pg_get_serial_sequence(:t, :c), 1, false)"), {"t": t, "c": col})
    return {"deleted": deleted, "audit": audit}


def _files() -> list[Path]:
    out = []
    for folder in FILE_FOLDERS:
        d = UPLOADS / folder
        if d.is_dir():
            out += [p for p in d.rglob("*") if p.is_file()]
    return out


def _control_plane_plan(cp, other_tenant_ids):
    from sqlalchemy import text

    return {
        "activation_events": cp.execute(text("select count(*) from activation_events")).scalar(),
        "activation_requests": cp.execute(text("select count(*) from activation_requests")).scalar(),
        "demo companies": [tuple(r) for r in cp.execute(text("select slug, display_name from tenants where id::text = any(:ids)"), {"ids": other_tenant_ids}).all()],
    }


def _control_plane_execute(cp, other_tenant_ids):
    """Activation requests (all test) + the demo companies' control-plane rows."""
    from sqlalchemy import text

    out = {"activation_events": cp.execute(text("delete from activation_events")).rowcount,
           "activation_requests": cp.execute(text("delete from activation_requests")).rowcount}
    cp.execute(text("alter sequence activation_request_number_seq restart with 1"))
    from app.platform.tenancy.models_cp import ControlPlaneSecret  # the codes kept for the requests go with them

    out["activation code secrets"] = cp.execute(text(f"delete from {ControlPlaneSecret.__tablename__} where ref like 'activation-code-%'")).rowcount
    if other_tenant_ids:
        graph = _fk_graph(cp)
        children = sorted({c for c, _cc, p, _pc, _n in graph if p == "tenants" and c != "tenants"})
        for c in children:
            col = next(cc for cc_t, cc, p, _pc, _n in graph if cc_t == c and p == "tenants")
            if col in ("tenant_id",) or True:
                out[c] = cp.execute(text(f'delete from "{c}" where "{col}"::text = any(:ids)'), {"ids": other_tenant_ids}).rowcount
        out["tenants"] = cp.execute(text("delete from tenants where id::text = any(:ids)"), {"ids": other_tenant_ids}).rowcount
    return out


def backup() -> list[Path]:
    from dotenv import dotenv_values

    env = dotenv_values(BACKEND / ".env")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (ROOT / "backups").mkdir(exist_ok=True)
    pg_dump = shutil.which("pg_dump") or next((str(p) for p in Path(r"C:\Program Files\PostgreSQL").glob("*/bin/pg_dump.exe")), None)
    if not pg_dump:
        raise Refused("pg_dump not found -- no backup, so nothing was changed.")
    made = []
    for key, name in (("DATABASE_URL", f"before_clear_{stamp}.dump"), ("CONTROL_PLANE_DATABASE_URL", f"before_clear_control_plane_{stamp}.dump")):
        u = urlparse(env.get(key) or os.environ.get(key, ""))
        target = ROOT / "backups" / name
        r = subprocess.run([pg_dump, "-Fc", "-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", unquote(u.username or ""),
                            "-d", u.path.lstrip("/"), "-f", str(target)], env=dict(os.environ, PGPASSWORD=unquote(u.password or "")),
                           capture_output=True, text=True)
        if r.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            raise Refused(f"Backup of {key} failed -- nothing was changed. {r.stderr[:300]}")
        made.append(target)
    zpath = ROOT / "backups" / f"files_before_clear_{stamp}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in (UPLOADS, BACKEND / "storage"):
            if folder.is_dir():
                for p in folder.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(BACKEND))
    made.append(zpath)
    return made


def main(argv=None) -> int:
    import hrctl  # noqa: F401
    from sqlalchemy import text

    from app.core.config import settings
    from app.platform.tenancy.context import TENANT_1_ID

    parser = argparse.ArgumentParser(prog="hrctl data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset", help="clear test data, keep the setup")
    r.add_argument("--keep-setup", action="store_true", required=True, help="required: the setup (company, users, settings ...) is always kept")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="show what would be removed (default)")
    g.add_argument("--confirm", action="store_true", help="backup, then delete")
    r.add_argument("--also-employee", action="append", default=[], metavar="FULL NAME",
                   help="also remove this employee record (exact 'First Last'); user logins are never touched")
    args = parser.parse_args(argv)

    if settings.ENV.lower() == "production":
        print("refused: ENV=production -- this command never runs on a production installation.", file=sys.stderr)
        return 2
    owner = str(TENANT_1_ID)
    cp_engine = _engine(settings.CONTROL_PLANE_DATABASE_URL)
    with cp_engine.connect() as cp:
        others = [str(r[0]) for r in cp.execute(text("select id from tenants where id <> cast(:o as uuid)"), {"o": owner}).all()]
    files = _files()
    try:
        if args.confirm:
            made = backup()
            print("backup:")
            for m in made:
                print(f"  {m.relative_to(ROOT)}  {m.stat().st_size:,} bytes")
        engine = _engine(settings.DATABASE_URL)  # admin role: sees every company (RLS doesn't apply)
        with engine.connect() as conn:
            trans = conn.begin()
            p = plan(conn, owner, others, tuple(args.also_employee))
            with cp_engine.connect() as cp:
                cp_trans = cp.begin()
                cpp = _control_plane_plan(cp, others)
                report = {"to_delete": {t: (f"{n}  (CTD Techs {p['split'][t]['ctd_techs']}, demo companies {p['split'][t]['demo_companies']})" if t in p["split"] else n)
                                        for t, n in p["delete"].items()}, "audit_entries": p["audit"] + p["demo_audit"],
                          "kept_rows_unlinked": [f"{c}.{col} -> {par}: {n} row(s) kept, link emptied" for c, col, par, n in p["nullify"]],
                          "files": {"count": len(files), "bytes": sum(f.stat().st_size for f in files),
                                    "folders": {f: len([x for x in files if f"uploads{os.sep}{f}{os.sep}" in str(x)]) for f in FILE_FOLDERS}},
                          "control_plane": cpp}
                if not args.confirm:
                    trans.rollback()
                    cp_trans.rollback()
                    report["mode"] = "DRY RUN -- nothing changed"
                    _print(report)
                    return 0
                done = execute(conn, owner, others, p)
                cp_done = _control_plane_execute(cp, others)
                trans.commit()
                cp_trans.commit()
        removed = 0
        for f in files:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        report.update(mode="DONE", deleted=done["deleted"], audit_deleted=done["audit"], control_plane_deleted=cp_done, files_deleted=removed)
        _clear_queues(settings)
        _print(report)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _clear_queues(settings) -> None:
    if settings.REDIS_URL:
        try:
            from app.platform.jobs.celery_app import celery_app

            print("queued jobs purged:", celery_app.control.purge())
        except Exception as exc:  # noqa: BLE001
            print("queue purge skipped:", exc)
    else:
        print("no Redis / job queue configured -- nothing to purge (in-process caches clear on restart)")


def _print(report: dict) -> None:
    import json

    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
