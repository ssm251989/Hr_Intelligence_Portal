"""InboundRouter (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 4) -- maps a thread_key to a
handler registered by a module (e.g. "recruitment.negotiation_reply"). Threading itself
(plus-addressing when the mailbox supports it, else Message-ID/References headers) is the
caller's job (whatever polls a connection's EmailReceiver.poll()) -- this module is only
the handler registry + dispatch once a thread_key is known.
"""

from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.comms import InboundMessage
from app.platform.connectors.capabilities import InboundEmail
from app.platform.tenancy.context import TenantContext

InboundHandler = Callable[[Session, TenantContext, InboundEmail, InboundMessage], None]

_HANDLERS: dict[str, InboundHandler] = {}


def register_inbound_handler(name: str, handler: InboundHandler) -> None:
    _HANDLERS[name] = handler


def extract_thread_key(message: InboundEmail, *, plus_address_domain: str | None = None) -> str | None:
    """Plus-addressing (`local+THREADKEY@domain`) when the mailbox supports it, else
    falls back to In-Reply-To (section 4's own priority order)."""
    if plus_address_domain and "+" in message.to_address.split("@")[0]:
        local = message.to_address.split("@")[0]
        return local.split("+", 1)[1]
    if message.in_reply_to:
        return message.in_reply_to
    return None


def route_inbound(db: Session, tenant: TenantContext, connection_id: UUID, message: InboundEmail, *, plus_address_domain: str | None = None) -> InboundMessage:
    thread_key = extract_thread_key(message, plus_address_domain=plus_address_domain)
    row = InboundMessage(
        tenant_id=tenant.tenant_id, connection_id=connection_id, from_address=message.from_address,
        to_address=message.to_address, subject=message.subject, message_id=message.message_id,
        in_reply_to=message.in_reply_to, thread_key=thread_key, body_ref=message.body_text,
        status="unmatched",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if thread_key is None:
        return row  # no way to route it -- HR inbox queue UI picks up "unmatched" rows

    for name, handler in _HANDLERS.items():
        try:
            handler(db, tenant, message, row)
            row.routed_handler = name
            row.status = "routed"
            db.commit()
            return row
        except _NotMyThreadError:
            continue
    return row  # every handler declined it -- stays "unmatched"


class _NotMyThreadError(Exception):
    """A handler raises this to say "not my thread_key format" -- route_inbound tries the
    next registered handler rather than treating it as a real processing failure."""
