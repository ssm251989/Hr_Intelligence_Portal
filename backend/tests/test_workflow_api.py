"""platform/workflow/api_router.py -- definitions CRUD/publish/simulate, instances,
act-on-step, the Unified Inbox, and the action-token one-click email-link page (Part 5B
CHECKS)."""

import uuid

from app.core.security import hash_password
from app.models.user import User

_SIMPLE_GRAPH = {
    "start_node": "n1",
    "nodes": {
        "n1": {"type": "action", "action": "set_field", "params": {"field": "touched", "value": True}, "next": "end"},
        "end": {"type": "end", "outcome": "approved"},
    },
}


def _make_user(db_session, email=None) -> User:
    user = User(email=email or f"wfapi-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_create_and_publish_a_definition(client):
    created = client.post("/api/v1/workflow/definitions", json={"key": "test.api.def1", "name": "Test Def", "graph": _SIMPLE_GRAPH})
    assert created.status_code == 201
    assert created.json()["status"] == "draft"

    published = client.post(f"/api/v1/workflow/definitions/{created.json()['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"


def test_publish_rejects_a_graph_missing_an_end_node(client):
    bad_graph = {"start_node": "n1", "nodes": {"n1": {"type": "action", "action": "set_field", "params": {"field": "x", "value": 1}, "next": "n1"}}}
    created = client.post("/api/v1/workflow/definitions", json={"key": "test.api.badgraph", "name": "Bad", "graph": bad_graph})
    response = client.post(f"/api/v1/workflow/definitions/{created.json()['id']}/publish")
    assert response.status_code == 400


def test_simulate_returns_the_dry_run_path(client):
    created = client.post("/api/v1/workflow/definitions", json={"key": "test.api.simulate", "name": "Sim", "graph": _SIMPLE_GRAPH})
    response = client.post(f"/api/v1/workflow/definitions/{created.json()['id']}/simulate", json={"sample_context": {}})
    assert response.status_code == 200
    assert [n["node_id"] for n in response.json()["path"]] == ["n1", "end"]


def test_list_and_get_instances(client, db_session):
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext
    from app.platform.workflow import definitions, engine

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    draft = definitions.create_draft(db_session, TENANT_1_ID, key="test.api.instances", name="I", trigger={}, graph=_SIMPLE_GRAPH)
    published = definitions.publish(db_session, draft, actor="test")
    instance = engine.start_instance(db_session, tenant, published, entity_type="test.entity", entity_id=uuid.uuid4(), context={})

    listed = client.get("/api/v1/workflow/instances", params={"entity_type": "test.entity"})
    assert listed.status_code == 200
    assert any(i["id"] == str(instance.id) for i in listed.json())

    fetched = client.get(f"/api/v1/workflow/instances/{instance.id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "completed"


def test_act_on_step_via_api(client, db_session):
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext
    from app.platform.workflow import definitions, engine

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    approver = _make_user(db_session)
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    draft = definitions.create_draft(db_session, TENANT_1_ID, key="test.api.act", name="A", trigger={}, graph=graph)
    published = definitions.publish(db_session, draft, actor="test")
    instance = engine.start_instance(db_session, tenant, published, entity_type="test.entity", entity_id=uuid.uuid4(), context={})

    from app.models.workflow import WorkflowStep

    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    response = client.post(f"/api/v1/workflow/steps/{step.id}/act", json={"action": "approve"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    fetched = client.get(f"/api/v1/workflow/instances/{instance.id}")
    assert fetched.json()["status"] == "completed"


def test_unified_inbox_lists_pending_steps_for_the_caller(client, db_session):
    from app.core.security import create_access_token
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext
    from app.platform.workflow import definitions, engine

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    approver = _make_user(db_session, email="inbox-target@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    draft = definitions.create_draft(db_session, TENANT_1_ID, key="test.api.inbox", name="Inbox", trigger={}, graph=graph)
    published = definitions.publish(db_session, draft, actor="test")
    engine.start_instance(db_session, tenant, published, entity_type="test.entity", entity_id=uuid.uuid4(), context={})

    token = create_access_token(subject=str(approver.id), extra_claims={"tid": str(TENANT_1_ID)})
    response = client.get("/api/v1/inbox", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["definition_name"] == "Inbox"


def test_action_link_approves_via_a_public_html_page(client, db_session):
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext
    from app.platform.workflow import definitions, engine

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    approver = _make_user(db_session, email="actionlink@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    draft = definitions.create_draft(db_session, TENANT_1_ID, key="test.api.actionlink", name="AL", trigger={}, graph=graph)
    published = definitions.publish(db_session, draft, actor="test")
    instance = engine.start_instance(db_session, tenant, published, entity_type="test.entity", entity_id=uuid.uuid4(), context={})

    from app.models.workflow import WorkflowStep

    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    link_response = client.post(f"/api/v1/workflow/steps/{step.id}/action-link", params={"action": "approve"})
    assert link_response.status_code == 200
    token = link_response.json()["token"]

    resolved = client.get(f"/api/v1/public/workflow/action/{token}")
    assert resolved.status_code == 200
    assert "approved" in resolved.text.lower()

    db_session.refresh(instance)
    assert instance.status == "completed"

    # the link is one-time-use
    reused = client.get(f"/api/v1/public/workflow/action/{token}")
    assert "already been handled" in reused.text.lower() or "already handled" in reused.text.lower()
