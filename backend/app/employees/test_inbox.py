"""Part 20.2b: emails to TEST (dummy) mailbox addresses never leave the server.

Every send path calls `split()` / `intercept_single()` before handing a message to a real mailbox:
- the copy is kept in `test_mailbox_messages` (Settings > Integrations > Test email provider -> open a
  mailbox -> its emails), so invites, set-password links and interview invites can be followed;
- in development (DEV_MAIL_CAPTURE, e.g. 127.0.0.1:1025) it is also delivered to mailpit;
- a SUSPENDED test mailbox does not receive anything (like a real suspended account).
A real address in the same message is sent normally.
"""

import smtplib
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session


def _addresses(db: Session, tenant_id) -> dict:
    from app.models.test_mailbox import TestMailbox

    return {r.address: r for r in db.query(TestMailbox).filter(TestMailbox.tenant_id == tenant_id, TestMailbox.status != "deleted").all()}


def split(db: Session, tenant, recipients: list[str]) -> tuple[list[str], list[str]]:
    """-> (test addresses, real addresses)."""
    if not recipients:
        return [], []
    known = _addresses(db, tenant.tenant_id)
    test = [a for a in recipients if (a or "").strip().lower() in known]
    return test, [a for a in recipients if a not in test]


def deliver(db: Session, tenant, addresses: list[str], *, subject: str, text: Optional[str], html: Optional[str], from_address: Optional[str] = None,
            template_key: Optional[str] = None, outbound_id=None) -> int:
    from app.core.config import settings
    from app.models.test_mailbox import TestMailboxMessage

    known = _addresses(db, tenant.tenant_id)
    n = 0
    for a in addresses:
        box = known.get(a.strip().lower())
        if box is None or box.status != "active":
            continue
        db.add(TestMailboxMessage(tenant_id=tenant.tenant_id, mailbox_id=box.id, to_address=box.address, from_address=from_address, subject=subject,
                                  body_text=text, body_html=html, template_key=template_key, outbound_message_id=outbound_id))
        n += 1
        if settings.DEV_MAIL_CAPTURE:  # development: the copy also lands in mailpit
            try:
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = subject or "", from_address or "hr-app@test.local", box.address
                msg["X-HR-Test-Mailbox"] = "TEST provider (dummy mailbox)"
                msg.set_content(text or "")
                if html:
                    msg.add_alternative(html, subtype="html")
                host, _, port = settings.DEV_MAIL_CAPTURE.partition(":")
                with smtplib.SMTP(host, int(port or 1025), timeout=10) as s:
                    s.send_message(msg)
            except (smtplib.SMTPException, OSError):
                pass  # the in-app test inbox still has it
    db.commit()
    return n


def intercept_single(to: str, *, subject: str, text: str, html: Optional[str], from_address: Optional[str]) -> bool:
    """For send paths without a session (the HR mailbox, app/integrations/hr_email.py). True = it was a test
    address: delivered to the test inbox, the caller must NOT send it anywhere."""
    from app.core.database import SessionLocal
    from app.platform.tenancy.context import get_current_tenant

    try:
        tenant = get_current_tenant()
    except Exception:  # noqa: BLE001 -- no tenant context: nothing to check
        return False
    db = SessionLocal()
    try:
        test, _real = split(db, tenant, [to])
        if not test:
            return False
        deliver(db, tenant, test, subject=subject, text=text, html=html, from_address=from_address, template_key="hr_mailbox")
        return True
    finally:
        db.close()


def mailboxes(db: Session, tenant) -> list[dict]:
    from sqlalchemy import func

    from app.models.test_mailbox import TestMailbox, TestMailboxMessage

    counts = dict(db.query(TestMailboxMessage.mailbox_id, func.count(TestMailboxMessage.id)).filter(TestMailboxMessage.tenant_id == tenant.tenant_id)
                  .group_by(TestMailboxMessage.mailbox_id).all())
    rows = db.query(TestMailbox).filter(TestMailbox.tenant_id == tenant.tenant_id, TestMailbox.status != "deleted").order_by(TestMailbox.created_at).all()
    return [{"id": str(r.id), "address": r.address, "display_name": r.display_name, "employee_id": str(r.employee_id) if r.employee_id else None,
             "employee_code": r.employee_code, "status": r.status, "quota": r.quota, "provider": r.provider, "password": "managed by app invite",
             "created_at": r.created_at.isoformat() if r.created_at else None, "created_by": r.created_by, "messages": counts.get(r.id, 0)} for r in rows]


def messages(db: Session, tenant, mailbox_id) -> list[dict]:
    from app.models.test_mailbox import TestMailboxMessage

    rows = (db.query(TestMailboxMessage).filter(TestMailboxMessage.tenant_id == tenant.tenant_id, TestMailboxMessage.mailbox_id == mailbox_id)
            .order_by(TestMailboxMessage.received_at.desc()).limit(200).all())
    return [{"id": str(m.id), "to": m.to_address, "from": m.from_address, "subject": m.subject, "text": m.body_text, "html": m.body_html,
             "template_key": m.template_key, "received_at": m.received_at.isoformat() if m.received_at else None} for m in rows]
