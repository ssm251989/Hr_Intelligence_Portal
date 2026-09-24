"""Candidate/pre-hire magic-link login (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 1) --
greenfield: no candidate portal exists yet to actually consume the token this issues (Part
8 builds that), so this is the mechanism seeded ahead of its own real caller, same pattern
as several of Part 4's own seeded-ahead message_templates. Modeled directly on
interview_scheduling/negotiation_token.py's own token shape (unique opaque string,
expires_at, one-time consumed_at) -- deliberately NOT reusing the generic ActionToken
table below, since a magic link's own semantics (WHO it logs in as) are different enough
from a workflow action token's (WHAT it lets someone do) to deserve their own table, same
reasoning as this file's sibling action_tokens.py explains for why IT genericizes
NegotiationToken instead of also being folded into this one.
"""

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.iam import MagicLink
from app.platform.tenancy.context import TenantContext

MAGIC_LINK_TTL_MINUTES = 15


def create_magic_link(db: Session, tenant: TenantContext, *, candidate_id: UUID, email: str) -> MagicLink:
    link = MagicLink(
        tenant_id=tenant.tenant_id, candidate_id=candidate_id, email=email.lower(),
        token=secrets.token_urlsafe(32), expires_at=datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


class MagicLinkError(Exception):
    pass


def consume_magic_link(db: Session, tenant: TenantContext, token: str) -> MagicLink:
    """Raises MagicLinkError("invalid"|"expired"|"already_used") -- one-time use, the same
    "flip a timestamp, never delete the row" pattern NegotiationToken already established."""
    link = db.query(MagicLink).filter(MagicLink.tenant_id == tenant.tenant_id, MagicLink.token == token).first()
    if link is None:
        raise MagicLinkError("invalid")
    if link.consumed_at is not None:
        raise MagicLinkError("already_used")
    if link.expires_at < datetime.now(timezone.utc):
        raise MagicLinkError("expired")
    link.consumed_at = datetime.now(timezone.utc)
    db.commit()
    return link
