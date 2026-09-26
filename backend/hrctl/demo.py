"""hrctl demo seed-two-tenants -- the docker-compose demo (docs/HRMS_COMPLETE_SPEC.txt
Part 13 CHECKS: "`docker compose up` brings up full stack with 2 demo tenants on different
subdomains with different branding/settings/mailboxes").

Everything here is DEMO DATA for a local stack, created through the same provisioning
code a real client gets (`hrctl tenant create`) -- this script only adds the per-tenant
differences on top: brand colours, timezone/locale settings, and an SMTP mailbox pointing
at the compose `mailpit` service with a distinct From address. It lives in hrctl/ (never
imported by the app), which is why its literals don't trip the hardcode guard.

    python -m hrctl.demo seed-two-tenants [--mail-host mailpit] [--mail-port 1025]

Part 15.8 review data ("Demo - " records for the new modules; see hrctl/demo_data.py):

    python -m hrctl.demo seed  --tenant <slug> [--demo-categories]
    python -m hrctl.demo clear --tenant <slug> [--yes]      # dry run unless --yes
"""

import argparse
import json
import sys

DEMO_TENANTS = (
    {"slug": "acme", "name": "Acme Demo Ltd", "domain": "acme.localhost", "primary": "#0f766e", "secondary": "#134e4a",
     "timezone": "Asia/Kolkata", "locale": "en-IN", "from": "hr@acme.localhost"},
    {"slug": "globex", "name": "Globex Demo Pvt", "domain": "globex.localhost", "primary": "#7c2d12", "secondary": "#431407",
     "timezone": "Asia/Kolkata", "locale": "hi-IN", "from": "people@globex.localhost"},
)


def _seed_extras(tenant, spec: dict, mail_host: str, mail_port: int) -> None:
    from app.models.comms import BrandTheme
    from app.models.connection import Connection, ConnectionRoute
    from app.models.secret import Secret, SecretScope
    from app.platform.connectors.registry import get_provider
    from app.platform.secrets.store import get_secret_store
    from app.platform.settings.resolver import SettingsService
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.provisioning import tenant_session

    ctx = TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)
    with tenant_context(tenant.id):
        db = tenant_session(tenant)
        try:
            if db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.id, BrandTheme.is_default.is_(True)).first() is None:
                db.add(BrandTheme(tenant_id=tenant.id, name=f"{spec['name']} theme", primary_color=spec["primary"], secondary_color=spec["secondary"],
                                  gradient_from=spec["primary"], gradient_to=spec["secondary"], is_default=True))
            service = SettingsService(db)
            service.set("org.timezone", spec["timezone"], scope_type="tenant", scope_id=None, actor="hrctl-demo", tenant=ctx)
            service.set("org.locale", spec["locale"], scope_type="tenant", scope_id=None, actor="hrctl-demo", tenant=ctx)

            connection = db.query(Connection).filter(Connection.tenant_id == tenant.id, Connection.name == "Demo mailbox").first()
            if connection is None:
                store = get_secret_store(db, Secret, SecretScope, str(tenant.id))
                ref = f"demo-smtp-{tenant.slug}"
                store.put(ref, json.dumps({"password": "demo"}), created_by="hrctl-demo")
                connection = Connection(tenant_id=tenant.id, name="Demo mailbox", provider_code="smtp", capability=list(get_provider("smtp").capabilities),
                                        config_json={"host": mail_host, "port": mail_port, "use_tls": False, "username": spec["from"], "from_address": spec["from"]},
                                        secret_ref=ref, status="active", created_by="hrctl-demo")
                db.add(connection)
                db.flush()
                for purpose in ("email.outbound.default", "email.outbound.system"):
                    db.add(ConnectionRoute(tenant_id=tenant.id, purpose=purpose, connection_id=connection.id, priority=1, enabled=True))
            db.commit()
        finally:
            db.close()


def seed_two_tenants(mail_host: str, mail_port: int) -> list[dict]:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import create_tenant

    results = []
    for spec in DEMO_TENANTS:
        cp_db = ControlPlaneSessionLocal()
        try:
            tenant = cp_db.query(Tenant).filter(Tenant.slug == spec["slug"]).first()
        finally:
            cp_db.close()
        if tenant is None:
            created = create_tenant(slug=spec["slug"], name=spec["name"], isolation="shared_rls", domain=spec["domain"],
                                    admin_email=f"admin@{spec['domain']}", notify=lambda _m: None)
            results.append({"slug": spec["slug"], "created": True, "admin_invite_token": created.get("admin_invite_token")})
            cp_db = ControlPlaneSessionLocal()
            try:
                tenant = cp_db.query(Tenant).filter(Tenant.slug == spec["slug"]).first()
            finally:
                cp_db.close()
        else:
            results.append({"slug": spec["slug"], "created": False})
        _seed_extras(tenant, spec, mail_host, mail_port)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl demo")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-two-tenants")
    seed.add_argument("--mail-host", default="mailpit")
    seed.add_argument("--mail-port", type=int, default=1025)
    demo_seed = sub.add_parser("seed", help="add clearly marked 'Demo - ' records for reviewing the screens")
    demo_seed.add_argument("--tenant", required=True, help="tenant slug")
    demo_seed.add_argument("--demo-categories", action="store_true", help="add 'Demo - ' ticket/asset categories if the company has none")
    demo_clear = sub.add_parser("clear", help="remove ONLY the demo records (dry run unless --yes)")
    demo_clear.add_argument("--tenant", required=True, help="tenant slug")
    demo_clear.add_argument("--yes", action="store_true", help="actually delete (default: report only)")
    args = parser.parse_args(argv)
    if args.command == "seed":
        from hrctl.demo_data import run_seed

        print(json.dumps(run_seed(args.tenant, args.demo_categories), indent=2, default=str))
    elif args.command == "clear":
        from hrctl.demo_data import run_clear

        print(json.dumps(run_clear(args.tenant, args.yes), indent=2, default=str))
    else:
        print(json.dumps(seed_two_tenants(args.mail_host, args.mail_port), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
