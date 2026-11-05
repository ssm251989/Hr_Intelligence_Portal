"""Generic one-time action links (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 3 -- "reuse
NegotiationToken pattern generically as action_tokens") -- the mechanism the Unified
Inbox's "approve/reject from email via signed one-time action links" uses. Same shape and
one-time-use-by-timestamp-flip semantics as interview_scheduling/negotiation_token.py's
own table, genericized: `entity_type`/`entity_id` name what this token acts ON (almost
always a `workflow_steps` row), `action` is a free-form verb a caller defines (never a
fixed 2-value enum the way NegotiationToken's own `role` column was, since a workflow step
can be approved, rejected, sent back, ...).
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.iam import ActionToken
from app.platform.tenancy.context import TenantContext

DEFAULT_ACTION_TOKEN_TTL_DAYS = 14


def create_action_token(
    db: Session, tenant: TenantContext, *, entity_type: str, entity_id: UUID, action: str,
    payload: Optional[dict] = None, created_by: Optional[str] = None, ttl_days: int = DEFAULT_ACTION_TOKEN_TTL_DAYS,
) -> ActionToken:
    row = ActionToken(
        tenant_id=tenant.tenant_id, entity_type=entity_type, entity_id=entity_id, action=action,
        token=secrets.token_urlsafe(32), payload_json=payload, created_by=created_by,
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class ActionTokenError(Exception):
    pass


def resolve_action_token(db: Session, tenant: TenantContext, token: str) -> ActionToken:
    """Raises ActionTokenError("invalid"|"expired"|"already_handled") -- never returns an
    unusable token silently, the same fail-loud convention negotiation.py's own
    get_negotiation_form established for its status strings."""
    row = db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.token == token).first()
    if row is None:
        raise ActionTokenError("invalid")
    if row.invalidated_at is not None or row.responded_at is not None:
        raise ActionTokenError("already_handled")
    if row.expires_at < datetime.now(timezone.utc):
        raise ActionTokenError("expired")
    return row


def mark_action_token_responded(db: Session, row: ActionToken) -> None:
    row.responded_at = datetime.now(timezone.utc)
    db.commit()


def invalidate_action_token(db: Session, row: ActionToken) -> None:
    row.invalidated_at = datetime.now(timezone.utc)
    db.commit()


def invalidate_action_tokens_for(db: Session, tenant: TenantContext, *, entity_type: str, entity_id: UUID) -> None:
    """Invalidates every still-live token for one entity -- e.g. once a workflow step is
    resolved by ANY means (someone acted in the UI, not just via the email link), every
    other outstanding action_token for that same step must stop working, the same
    "supersede, don't just ignore" rule negotiation.py's own re-prompt flow already
    follows for negotiation tokens."""
    now = datetime.now(timezone.utc)
    db.query(ActionToken).filter(
        ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == entity_type, ActionToken.entity_id == entity_id,
        ActionToken.invalidated_at.is_(None), ActionToken.responded_at.is_(None),
    ).update({"invalidated_at": now})
    db.commit()
