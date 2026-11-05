"""hrctl migrate-connections (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 5): migrates
tenant #1's current HR mailbox (the singleton `hr_integrations` row), Anthropic key, and
Interview Scheduling tracker path into real `connections` + `connection_routes` rows.
Does NOT touch or drop the old `hr_integrations` row/table, and does NOT change what
negotiation.py/hr_email.py/imap_poll.py actually call at runtime -- see
docs/build_log.md's own Part 3 note for why that deeper rewire is scoped out of this pass.
This proves the new framework holds equivalent, resolvable configuration for tenant #1's
real mailbox, not that every consumer has switched to reading it yet.

Usage: python -m hrctl.migrate_connections [--dry-run]
"""

import argparse
import json
import sys

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.database import SessionLocal
from app.integrations.hr_email import is_smtp_configured
from app.integrations.imap_poll import is_imap_configured
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.models.connection import Connection, ConnectionRoute
from app.models.hr_integration import HrIntegration
from app.platform.connectors.providers import register_all as register_providers
from app.platform.secrets.store import get_secret_store
from app.platform.tenancy.context import TENANT_1_ID, tenant_context

register_providers()


def _get_secret_store(db):
    from app.models.secret import Secret, SecretScope

    return get_secret_store(db, Secret, SecretScope, str(TENANT_1_ID))


def _upsert_connection(db, *, name: str, provider_code: str, config: dict, secret_value: dict | None) -> Connection:
    existing = db.query(Connection).filter(Connection.provider_code == provider_code, Connection.name == name).first()
    secret_ref = None
    if secret_value is not None:
        store = _get_secret_store(db)
        secret_ref = f"connection-{provider_code}-{name}".replace(" ", "-").lower()
        try:
            store.rotate(secret_ref, json.dumps(secret_value), created_by="hrctl")
        except Exception:
            store.put(secret_ref, json.dumps(secret_value), created_by="hrctl")

    if existing is not None:
        existing.config_json = config
        existing.secret_ref = secret_ref or existing.secret_ref
        existing.status = "active"
        db.commit()
        db.refresh(existing)
        return existing

    from app.platform.connectors.registry import get_provider

    spec = get_provider(provider_code)
    connection = Connection(
        tenant_id=TENANT_1_ID, name=name, provider_code=provider_code, capability=list(spec.capabilities),
        config_json=config, secret_ref=secret_ref, status="active", created_by="hrctl",
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def _upsert_route(db, *, purpose: str, connection: Connection, priority: int = 1) -> None:
    existing = (
        db.query(ConnectionRoute)
        .filter(ConnectionRoute.purpose == purpose, ConnectionRoute.connection_id == connection.id)
        .first()
    )
    if existing is not None:
        existing.enabled = True
        db.commit()
        return
    db.add(ConnectionRoute(tenant_id=TENANT_1_ID, purpose=purpose, connection_id=connection.id, priority=priority, enabled=True))
    db.commit()


def migrate(dry_run: bool) -> None:
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            hr_integration = db.get(HrIntegration, 1)
            plan: list[str] = []

            if hr_integration and is_smtp_configured(hr_integration):
                plan.append(f"smtp connection from hr_integrations (host={hr_integration.smtp_host})")
            if hr_integration and is_imap_configured(hr_integration):
                plan.append(f"imap connection from hr_integrations (host={hr_integration.imap_host})")
            if settings.ANTHROPIC_API_KEY:
                plan.append("anthropic connection from ANTHROPIC_API_KEY env var")
            tracker_settings = get_interview_scheduling_settings(db)
            if tracker_settings.tracker_path:
                plan.append(f"excel_file connection from interview_scheduling_settings (path={tracker_settings.tracker_path})")

            print("Migration plan:")
            for line in plan:
                print(f"  - {line}")
            if dry_run:
                print("\n--dry-run: nothing written.")
                return
            if not plan:
                print("\nNothing configured yet to migrate.")
                return

            if hr_integration and is_smtp_configured(hr_integration):
                smtp_conn = _upsert_connection(
                    db, name="HR Mailbox (SMTP)", provider_code="smtp",
                    config={
                        "host": hr_integration.smtp_host, "port": hr_integration.smtp_port,
                        "username": hr_integration.smtp_username, "use_tls": bool(hr_integration.use_tls),
                        "from_address": hr_integration.from_address,
                    },
                    secret_value={"password": decrypt(hr_integration.smtp_password)},
                )
                _upsert_route(db, purpose="email.outbound.default", connection=smtp_conn)
                _upsert_route(db, purpose="email.outbound.interview_negotiation", connection=smtp_conn)

            if hr_integration and is_imap_configured(hr_integration):
                imap_conn = _upsert_connection(
                    db, name="HR Mailbox (IMAP)", provider_code="imap",
                    config={"host": hr_integration.imap_host, "port": hr_integration.imap_port, "username": hr_integration.smtp_username},
                    secret_value={"password": decrypt(hr_integration.smtp_password)},
                )
                _upsert_route(db, purpose="email.inbound.negotiation_replies", connection=imap_conn)

            if settings.ANTHROPIC_API_KEY:
                anthropic_conn = _upsert_connection(
                    db, name="Anthropic (platform key)", provider_code="anthropic", config={},
                    secret_value={"api_key": settings.ANTHROPIC_API_KEY},
                )
                for purpose in ("llm.resume_extraction", "llm.scoring", "llm.judgment", "llm.copilot", "llm.embeddings"):
                    _upsert_route(db, purpose=purpose, connection=anthropic_conn)

            if tracker_settings.tracker_path:
                tracker_conn = _upsert_connection(
                    db, name="Interview Tracker", provider_code="excel_file",
                    config={"path": tracker_settings.tracker_path}, secret_value=None,
                )
                _upsert_route(db, purpose="storage.documents", connection=tracker_conn)

            print("\nMigrated successfully.")
        finally:
            db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl migrate-connections")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    migrate(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
