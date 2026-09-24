"""platform/comms/inbound.py's InboundRouter -- threading + handler dispatch (Part 4
CHECKS)."""

import uuid

from app.models.comms import InboundMessage
from app.models.connection import Connection
from app.platform.comms.inbound import _HANDLERS, _NotMyThreadError, extract_thread_key, register_inbound_handler, route_inbound
from app.platform.connectors.capabilities import InboundEmail
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _msg(**overrides) -> InboundEmail:
    defaults = dict(from_address="candidate@example.com", to_address="hr@example.com", subject="Re: Interview", body_text="I accept", message_id="<abc@example.com>")
    defaults.update(overrides)
    return InboundEmail(**defaults)


def _connection_id(db_session) -> uuid.UUID:
    """route_inbound's connection_id FK requires a real connections row."""
    conn = Connection(tenant_id=TENANT_1_ID, name="test inbound mailbox", provider_code="smtp_imap", capability=["email.receive"])
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn.id


def test_extract_thread_key_prefers_plus_addressing(db_session):
    msg = _msg(to_address="hr+thread123@example.com", in_reply_to="<ignored@example.com>")
    assert extract_thread_key(msg, plus_address_domain="example.com") == "thread123"


def test_extract_thread_key_falls_back_to_in_reply_to(db_session):
    msg = _msg(to_address="hr@example.com", in_reply_to="<parent-message-id@example.com>")
    assert extract_thread_key(msg) == "<parent-message-id@example.com>"


def test_extract_thread_key_none_when_neither_is_present(db_session):
    msg = _msg(to_address="hr@example.com", in_reply_to=None)
    assert extract_thread_key(msg) is None


def test_route_inbound_always_logs_the_message_even_when_unmatched(db_session):
    msg = _msg(in_reply_to=None)
    row = route_inbound(db_session, TENANT, _connection_id(db_session), msg)

    assert row.status == "unmatched"
    stored = db_session.query(InboundMessage).filter(InboundMessage.id == row.id).first()
    assert stored is not None
    assert stored.from_address == "candidate@example.com"


def test_route_inbound_dispatches_to_a_matching_registered_handler(db_session):
    calls = []

    def _handler(db, tenant, message, row):
        calls.append((message.from_address, row.id))

    register_inbound_handler("test.thread_handler", _handler)
    try:
        msg = _msg(in_reply_to="<some-thread@example.com>")
        row = route_inbound(db_session, TENANT, _connection_id(db_session), msg)

        assert row.status == "routed"
        assert row.routed_handler == "test.thread_handler"
        assert calls == [("candidate@example.com", row.id)]
    finally:
        del _HANDLERS["test.thread_handler"]


def test_route_inbound_tries_the_next_handler_when_one_declines(db_session):
    def _declining_handler(db, tenant, message, row):
        raise _NotMyThreadError

    accepted = []

    def _accepting_handler(db, tenant, message, row):
        accepted.append(row.id)

    register_inbound_handler("test.declining_handler", _declining_handler)
    register_inbound_handler("test.accepting_handler", _accepting_handler)
    try:
        msg = _msg(in_reply_to="<another-thread@example.com>")
        row = route_inbound(db_session, TENANT, _connection_id(db_session), msg)

        assert row.status == "routed"
        assert row.routed_handler == "test.accepting_handler"
        assert accepted == [row.id]
    finally:
        del _HANDLERS["test.declining_handler"]
        del _HANDLERS["test.accepting_handler"]
