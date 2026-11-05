"""Part 20.2b: switching the TEST (dummy) email provider on/off, and moving its mailboxes to a real
provider later (dry run first, never automatic)."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.connection import Connection, ConnectionRoute

NAME = "Test email provider (dummy)"


def _connection(db: Session, tenant) -> Optional[Connection]:
    return db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.provider_code == "test_mailbox").first()


def status(db: Session, tenant) -> dict:
    from app.core.config import settings
    from app.employees import mailboxes, test_inbox

    conn = _connection(db, tenant)
    route = (db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.purpose == mailboxes.PURPOSE,
                                              ConnectionRoute.connection_id == conn.id).first() if conn else None)
    real = [{"id": str(c.id), "name": c.name, "provider": c.provider_code, "status": c.status}
            for c in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.provider_code.in_(("google_workspace", "microsoft_365"))).all()]
    return {"exists": conn is not None, "active": mailboxes.active_provider(db, tenant) == "test", "routed": bool(route and route.enabled),
            "connection_id": str(conn.id) if conn else None, "domain": mailboxes.domain(db, tenant), "mailboxes": test_inbox.mailboxes(db, tenant),
            "real_connections": real, "production": settings.ENV == "production", "dev_capture": bool(settings.DEV_MAIL_CAPTURE)}


def switch(db: Session, tenant, *, on: bool, actor: str) -> dict:
    """On: the TEST provider becomes the email-admin connection (its route first). Off: its route is
    disabled -- new employees then go through the real connection, or the IT to-do."""
    from app.employees import mailboxes

    conn = _connection(db, tenant)
    if conn is None:
        conn = Connection(tenant_id=tenant.tenant_id, name=NAME, provider_code="test_mailbox", capability=["MailboxAdmin"],
                          config_json={"note": "No real mailboxes - for testing until Google Workspace / Microsoft 365 is connected"},
                          status="active", last_tested_at=datetime.now(timezone.utc), last_test_result={"success": True, "error": None}, created_by=actor[:120])
        db.add(conn)
        db.flush()
    conn.status = "active"
    route = db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.purpose == mailboxes.PURPOSE,
                                             ConnectionRoute.connection_id == conn.id).first()
    if route is None:
        route = ConnectionRoute(tenant_id=tenant.tenant_id, purpose=mailboxes.PURPOSE, connection_id=conn.id, priority=1, enabled=on)
        db.add(route)
    route.enabled = on
    if on:  # first in line
        for other in db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.purpose == mailboxes.PURPOSE,
                                                      ConnectionRoute.connection_id != conn.id).all():
            other.priority = max(other.priority or 1, 2)
        route.priority = 1
    db.commit()
    log_action(db, "connection", conn.id, "test_email_provider_on" if on else "test_email_provider_off", actor[:50], {})
    return status(db, tenant)


def move_to_real(db: Session, tenant, *, apply: bool, actor: str) -> dict:
    """Creates real mailboxes (the routed real provider) for ACTIVE employees on test mailboxes and drops
    the TEST chip. Dry run lists who would move. The real provider's first passwords are returned ONCE
    (shown to HR on screen), never stored."""
    from app.employees import mailboxes
    from app.models.core_hr import Employee

    real = [c for c in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.provider_code.in_(("google_workspace", "microsoft_365")),
                                                   Connection.status == "active").all()]
    people = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.company_email_provider == "test",
                                       Employee.status.in_(("active", "on_notice"))).order_by(Employee.employee_code).all()
    plan = [{"employee_id": str(e.id), "code": e.employee_code, "name": " ".join(p for p in (e.first_name, e.last_name) if p), "address": e.company_email}
            for e in people]
    if not apply:
        return {"dry_run": True, "would_move": plan, "real_provider": real[0].name if real else None,
                "blocked": None if real else "Connect Google Workspace or Microsoft 365 first (Settings > Integrations > Connections)."}
    if not real:
        raise ValueError("Connect Google Workspace or Microsoft 365 first (Settings > Integrations > Connections).")
    switch(db, tenant, on=False, actor=actor)  # the real connection now answers directory.mailboxes
    results = []
    for e in people:
        try:
            out = mailboxes.adapter(db, tenant).create_mailbox(address=e.company_email, first_name=e.first_name, last_name=e.last_name or "",
                                                               display_name=" ".join(p for p in (e.first_name, e.last_name) if p), employee_ref=e.employee_code, actor=actor)
            e.company_email_provider = mailboxes.active_provider(db, tenant) or "manual"
            db.commit()
            results.append({"code": e.employee_code, "address": e.company_email, "ok": True, "one_time_password": out.get("temp_password")})
        except Exception as exc:  # noqa: BLE001 -- listed, the others carry on
            results.append({"code": e.employee_code, "address": e.company_email, "ok": False, "error": str(exc)[:200]})
    log_action(db, "connection", None, "test_mailboxes_moved_to_real", actor[:50],
               {"moved": [r["code"] for r in results if r["ok"]], "failed": [r["code"] for r in results if not r["ok"]]})
    return {"dry_run": False, "results": results}
