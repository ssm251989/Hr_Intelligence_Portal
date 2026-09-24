"""platform/iam/action_tokens.py (generic one-time action links, Part 5B section 3) and
platform/iam/magic_links.py (candidate/pre-hire login, Part 5A section 1). Part 5's own
CHECKS/TESTS list."""

import uuid

import pytest

from app.platform.iam.action_tokens import (
    ActionTokenError,
    create_action_token,
    invalidate_action_token,
    invalidate_action_tokens_for,
    mark_action_token_responded,
    resolve_action_token,
)
from app.platform.iam.magic_links import MagicLinkError, consume_magic_link, create_magic_link
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


# ---- action_tokens ----


def test_create_and_resolve_action_token(db_session):
    entity_id = uuid.uuid4()
    row = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=entity_id, action="approve", payload={"note": "go ahead"})

    resolved = resolve_action_token(db_session, TENANT, row.token)
    assert resolved.id == row.id
    assert resolved.action == "approve"
    assert resolved.payload_json == {"note": "go ahead"}


def test_resolve_unknown_token_raises_invalid(db_session):
    with pytest.raises(ActionTokenError, match="invalid"):
        resolve_action_token(db_session, TENANT, "not-a-real-token")


def test_resolve_expired_token_raises_expired(db_session):
    from datetime import datetime, timedelta, timezone

    row = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=uuid.uuid4(), action="approve")
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    with pytest.raises(ActionTokenError, match="expired"):
        resolve_action_token(db_session, TENANT, row.token)


def test_resolve_already_responded_token_raises_already_handled(db_session):
    row = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=uuid.uuid4(), action="approve")
    mark_action_token_responded(db_session, row)

    with pytest.raises(ActionTokenError, match="already_handled"):
        resolve_action_token(db_session, TENANT, row.token)


def test_resolve_invalidated_token_raises_already_handled(db_session):
    row = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=uuid.uuid4(), action="approve")
    invalidate_action_token(db_session, row)

    with pytest.raises(ActionTokenError, match="already_handled"):
        resolve_action_token(db_session, TENANT, row.token)


def test_invalidate_action_tokens_for_supersedes_every_live_token_on_that_entity(db_session):
    entity_id = uuid.uuid4()
    approve_token = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=entity_id, action="approve")
    reject_token = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=entity_id, action="reject")

    invalidate_action_tokens_for(db_session, TENANT, entity_type="workflow_step", entity_id=entity_id)

    with pytest.raises(ActionTokenError, match="already_handled"):
        resolve_action_token(db_session, TENANT, approve_token.token)
    with pytest.raises(ActionTokenError, match="already_handled"):
        resolve_action_token(db_session, TENANT, reject_token.token)


def test_invalidate_action_tokens_for_does_not_touch_other_entities(db_session):
    this_entity = uuid.uuid4()
    other_entity = uuid.uuid4()
    this_token = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=this_entity, action="approve")
    other_token = create_action_token(db_session, TENANT, entity_type="workflow_step", entity_id=other_entity, action="approve")

    invalidate_action_tokens_for(db_session, TENANT, entity_type="workflow_step", entity_id=this_entity)

    with pytest.raises(ActionTokenError):
        resolve_action_token(db_session, TENANT, this_token.token)
    resolve_action_token(db_session, TENANT, other_token.token)  # does not raise


# ---- magic_links ----


def test_create_and_consume_magic_link(db_session):
    candidate_id = uuid.uuid4()
    link = create_magic_link(db_session, TENANT, candidate_id=candidate_id, email="jane@example.com")

    consumed = consume_magic_link(db_session, TENANT, link.token)
    assert consumed.candidate_id == candidate_id


def test_consume_unknown_magic_link_raises_invalid(db_session):
    with pytest.raises(MagicLinkError, match="invalid"):
        consume_magic_link(db_session, TENANT, "not-a-real-token")


def test_consume_magic_link_twice_raises_already_used(db_session):
    link = create_magic_link(db_session, TENANT, candidate_id=uuid.uuid4(), email="jane@example.com")
    consume_magic_link(db_session, TENANT, link.token)

    with pytest.raises(MagicLinkError, match="already_used"):
        consume_magic_link(db_session, TENANT, link.token)


def test_consume_expired_magic_link_raises_expired(db_session):
    from datetime import datetime, timedelta, timezone

    link = create_magic_link(db_session, TENANT, candidate_id=uuid.uuid4(), email="jane@example.com")
    link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    with pytest.raises(MagicLinkError, match="expired"):
        consume_magic_link(db_session, TENANT, link.token)
