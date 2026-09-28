"""ConnectorRouter (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 4): resolve(purpose, ctx) ->
highest-priority enabled route whose condition passes, walking the purpose's fallback chain
if nothing is routed for the specific purpose. Circuit breaker: a route whose connection
has failed CIRCUIT_BREAKER_THRESHOLD times in a row (most recent connection_attempts for
that connection+purpose) is skipped in favor of the next priority route.
"""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

try:
    import json_logic
except ImportError:  # pragma: no cover -- see requirements.txt note
    json_logic = None

from app.models.connection import Connection, ConnectionRoute
from app.platform.connectors.purposes import fallback_for

CIRCUIT_BREAKER_THRESHOLD = 5


class NoConnectionForPurposeError(Exception):
    """No enabled, passing-condition, non-tripped-breaker route exists for this purpose
    (after walking its whole fallback chain) -- surfaced in the UI as a configuration
    issue (Part 14 section 8: a plain-language fix + link to Integrations), never a 500."""

    def __init__(self, purpose: str):
        self.purpose = purpose
        super().__init__(f"No connection routed for purpose: {purpose}")


@dataclass
class ResolvedConnection:
    connection: Connection
    route: ConnectionRoute
    purpose_resolved: str  # the purpose actually matched -- may differ from the one asked
    # for, if resolution fell through a fallback chain


def _condition_passes(condition: Optional[dict], ctx: dict) -> bool:
    if condition is None:
        return True
    if json_logic is None:
        # jsonlogic library unavailable in this environment -- fail safe: a route with a
        # real condition attached is treated as not matching rather than silently ignoring
        # the condition and matching everything.
        return False
    return bool(json_logic.jsonLogic(condition, ctx))


def _breaker_tripped(db: Session, connection_id: UUID, purpose: str) -> bool:
    from app.models.connection import ConnectionAttempt

    recent = (
        db.query(ConnectionAttempt.status)
        .filter(ConnectionAttempt.connection_id == connection_id, ConnectionAttempt.purpose == purpose)
        .order_by(ConnectionAttempt.created_at.desc())
        .limit(CIRCUIT_BREAKER_THRESHOLD)
        .all()
    )
    if len(recent) < CIRCUIT_BREAKER_THRESHOLD:
        return False
    return all(status == "failed" for (status,) in recent)


class ConnectorRouter:
    def __init__(self, db: Session):
        self.db = db

    def _resolve_one_purpose(self, purpose: str, ctx: dict) -> Optional[ResolvedConnection]:
        routes = (
            self.db.query(ConnectionRoute)
            .filter(ConnectionRoute.purpose == purpose, ConnectionRoute.enabled.is_(True))
            .order_by(ConnectionRoute.priority.asc())
            .all()
        )
        for route in routes:
            if not _condition_passes(route.condition_jsonlogic, ctx):
                continue
            connection = self.db.get(Connection, route.connection_id)
            if connection is None or connection.status not in ("active", "draft"):
                continue
            if _breaker_tripped(self.db, connection.id, purpose):
                continue
            return ResolvedConnection(connection=connection, route=route, purpose_resolved=purpose)
        return None

    def resolve(self, purpose: str, ctx: Optional[dict] = None) -> ResolvedConnection:
        ctx = ctx or {}
        current = purpose
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            resolved = self._resolve_one_purpose(current, ctx)
            if resolved is not None:
                return resolved
            current = fallback_for(current)
        mailbox = self._company_mailbox(purpose)
        if mailbox is not None:
            return mailbox
        raise NoConnectionForPurposeError(purpose)

    # Part 18.2: there is ONE company mailbox. Any email purpose with no route of its own uses
    # the connection already routed for another purpose in the same direction (sending or
    # reading); failing that, the company's only active connection that can do it.
    _MAIL_CAPABILITY = {"outbound": "EmailSender", "inbound": "EmailReceiver"}

    def _company_mailbox(self, purpose: str) -> Optional[ResolvedConnection]:
        parts = purpose.split(".")
        if len(parts) < 2 or parts[0] != "email" or parts[1] not in self._MAIL_CAPABILITY:
            return None
        prefix = f"email.{parts[1]}."
        for route in (self.db.query(ConnectionRoute).filter(ConnectionRoute.purpose.like(prefix + "%"), ConnectionRoute.enabled.is_(True))
                      .order_by(ConnectionRoute.purpose.asc(), ConnectionRoute.priority.asc()).all()):
            if route.condition_jsonlogic:
                continue  # a conditional route was meant for its own purpose only
            connection = self.db.get(Connection, route.connection_id)
            if connection is not None and connection.status == "active" and not _breaker_tripped(self.db, connection.id, purpose):
                return ResolvedConnection(connection=connection, route=route, purpose_resolved=route.purpose)
        return None

    def try_resolve(self, purpose: str, ctx: Optional[dict] = None) -> Optional[ResolvedConnection]:
        try:
            return self.resolve(purpose, ctx)
        except NoConnectionForPurposeError:
            return None
