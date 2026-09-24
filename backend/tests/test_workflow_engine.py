"""platform/workflow/engine.py -- condition/switch/action nodes, sequential/parallel/any/
quorum approval modes, send-back, reject, auto-approve, wait timers, parallel branches,
sub_workflow, simulation (Part 5B CHECKS)."""

import uuid

import pytest

from app.core.security import hash_password
from app.models.user import User
from app.models.workflow import WorkflowInstance, WorkflowStep
from app.platform.workflow import definitions, engine
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session, email=None) -> User:
    user = User(email=email or f"wf-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _publish(db_session, key, graph, trigger=None):
    draft = definitions.create_draft(db_session, TENANT_1_ID, key=key, name=key, trigger=trigger or {}, graph=graph)
    return definitions.publish(db_session, draft, actor="test")


# ---- condition / switch / action, no human steps at all ----


def test_condition_node_branches_and_completes(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "condition", "jsonlogic": {">": [{"var": "amount"}, 100]}, "on_true": "big", "on_false": "small"},
            "big": {"type": "end", "outcome": "approved"},
            "small": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.condition", graph)

    high = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={"amount": 500})
    assert high.status == "completed"
    assert high.context_json["outcome"] == "approved"

    low = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={"amount": 10})
    assert low.status == "cancelled"
    assert low.context_json["outcome"] == "rejected"


def test_switch_node_picks_the_first_matching_case(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "switch", "cases": [
                {"jsonlogic": {"==": [{"var": "tier"}, "gold"]}, "next": "gold_end"},
                {"jsonlogic": {"==": [{"var": "tier"}, "silver"]}, "next": "silver_end"},
            ], "default": "default_end"},
            "gold_end": {"type": "end", "outcome": "approved"},
            "silver_end": {"type": "end", "outcome": "approved"},
            "default_end": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.switch", graph)

    silver = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={"tier": "silver"})
    assert silver.current_node_id is None
    assert silver.context_json["outcome"] == "approved"

    bronze = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={"tier": "bronze"})
    assert bronze.context_json["outcome"] == "rejected"


def test_set_field_action_mutates_context(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "action", "action": "set_field", "params": {"field": "reviewed", "value": True}, "next": "end"},
            "end": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.set_field", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    assert instance.context_json["reviewed"] is True


# ---- approval: single approver ----


def test_single_approver_approval_completes_on_approve(db_session):
    approver = _make_user(db_session)
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.single_approver", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    assert instance.status == "running"

    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").one()
    engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="approve")

    db_session.refresh(instance)
    assert instance.status == "completed"


def test_single_approver_approval_ends_on_reject(db_session):
    approver = _make_user(db_session)
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.single_reject", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="reject", comment="no")
    db_session.refresh(instance)
    assert instance.status == "cancelled"


def test_acting_on_an_already_resolved_step_raises(db_session):
    approver = _make_user(db_session)
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.double_act", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()
    engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="approve")

    with pytest.raises(engine.WorkflowStateError):
        engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="approve")


# ---- sequential gates ----


def test_sequential_mode_advances_through_gates_in_order(db_session):
    first = _make_user(db_session, email="first@example.com")
    second = _make_user(db_session, email="second@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "sequential",
                "approvers": [{"type": "user", "user_id": str(first.id)}, {"type": "user", "user_id": str(second.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.sequential", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})

    first_step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").one()
    assert first_step.assignee_user_id == first.id

    engine.act_on_step(db_session, TENANT, first_step.id, actor=first.email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "running"  # gate 2 not yet resolved

    second_step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").one()
    assert second_step.assignee_user_id == second.id

    engine.act_on_step(db_session, TENANT, second_step.id, actor=second.email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "completed"


def test_sequential_mode_stops_at_first_rejection(db_session):
    first = _make_user(db_session, email="seqrej1@example.com")
    second = _make_user(db_session, email="seqrej2@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "sequential",
                "approvers": [{"type": "user", "user_id": str(first.id)}, {"type": "user", "user_id": str(second.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.sequential_reject", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    first_step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").one()

    engine.act_on_step(db_session, TENANT, first_step.id, actor=first.email, action="reject", comment="no")
    db_session.refresh(instance)
    assert instance.status == "cancelled"
    # second gate never opened
    assert db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.assignee_user_id == second.id).count() == 0


# ---- parallel/any/quorum pool modes ----


def test_parallel_mode_requires_every_approver(db_session):
    a = _make_user(db_session, email="par-a@example.com")
    b = _make_user(db_session, email="par-b@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "parallel",
                "approvers": [{"type": "user", "user_id": str(a.id)}, {"type": "user", "user_id": str(b.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.parallel", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    steps = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).all()
    assert len(steps) == 2

    step_a = next(s for s in steps if s.assignee_user_id == a.id)
    engine.act_on_step(db_session, TENANT, step_a.id, actor=a.email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "running"  # still waiting on b

    step_b = next(s for s in steps if s.assignee_user_id == b.id)
    engine.act_on_step(db_session, TENANT, step_b.id, actor=b.email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "completed"


def test_parallel_mode_single_reject_fails_the_whole_node(db_session):
    a = _make_user(db_session, email="par2-a@example.com")
    b = _make_user(db_session, email="par2-b@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "parallel",
                "approvers": [{"type": "user", "user_id": str(a.id)}, {"type": "user", "user_id": str(b.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.parallel_reject", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step_a = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.assignee_user_id == a.id).one()

    engine.act_on_step(db_session, TENANT, step_a.id, actor=a.email, action="reject", comment="no")
    db_session.refresh(instance)
    assert instance.status == "cancelled"

    step_b = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.assignee_user_id == b.id).one()
    assert step_b.status == "skipped"


def test_any_mode_first_approval_wins_and_supersedes_the_rest(db_session):
    a = _make_user(db_session, email="any-a@example.com")
    b = _make_user(db_session, email="any-b@example.com")
    c = _make_user(db_session, email="any-c@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "any",
                "approvers": [{"type": "user", "user_id": str(a.id)}, {"type": "user", "user_id": str(b.id)}, {"type": "user", "user_id": str(c.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.any", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step_a = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.assignee_user_id == a.id).one()

    engine.act_on_step(db_session, TENANT, step_a.id, actor=a.email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "completed"

    others = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.assignee_user_id != a.id).all()
    assert all(s.status == "skipped" for s in others)


def test_quorum_mode_needs_exactly_n_approvals(db_session):
    users = [_make_user(db_session, email=f"quorum-{i}@example.com") for i in range(4)]
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 2,
                "approvers": [{"type": "user", "user_id": str(u.id)} for u in users],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.quorum", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    steps = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).all()
    assert len(steps) == 4

    engine.act_on_step(db_session, TENANT, steps[0].id, actor=users[0].email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "running"

    engine.act_on_step(db_session, TENANT, steps[1].id, actor=users[1].email, action="approve")
    db_session.refresh(instance)
    assert instance.status == "completed"

    # the remaining two get superseded
    remaining = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id, WorkflowStep.status == "pending").count()
    assert remaining == 0


def test_quorum_mode_fails_once_unreachable(db_session):
    users = [_make_user(db_session, email=f"quorumfail-{i}@example.com") for i in range(4)]
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 3,
                "approvers": [{"type": "user", "user_id": str(u.id)} for u in users],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.quorum_fail", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    steps = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).all()

    # quorum=3 of 4 -- 2 rejects makes it mathematically impossible (only 2 possible approvals left)
    engine.act_on_step(db_session, TENANT, steps[0].id, actor=users[0].email, action="reject", comment="no")
    db_session.refresh(instance)
    assert instance.status == "running"
    engine.act_on_step(db_session, TENANT, steps[1].id, actor=users[1].email, action="reject", comment="no")
    db_session.refresh(instance)
    assert instance.status == "cancelled"


# ---- send-back ----


def test_send_back_routes_to_on_send_back_when_allowed(db_session):
    approver = _make_user(db_session, email="sendback@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 1, "allow_send_back": True,
                "approvers": [{"type": "user", "user_id": str(approver.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad", "on_send_back": "end_sent_back",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
            "end_sent_back": {"type": "end", "outcome": "sent_back"},
        },
    }
    definition = _publish(db_session, "test.send_back", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="send_back", comment="fix this")
    db_session.refresh(instance)
    assert instance.context_json["outcome"] == "sent_back"


def test_send_back_rejected_when_node_does_not_allow_it(db_session):
    approver = _make_user(db_session, email="nosendback@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 1,
                "approvers": [{"type": "user", "user_id": str(approver.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.no_send_back", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    with pytest.raises(engine.WorkflowConfigError):
        engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="send_back")


def test_comment_required_on_reject_is_enforced(db_session):
    approver = _make_user(db_session, email="needcomment@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 1, "comments_required_on_reject": True,
                "approvers": [{"type": "user", "user_id": str(approver.id)}],
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.require_comment", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()

    with pytest.raises(engine.WorkflowConfigError):
        engine.act_on_step(db_session, TENANT, step.id, actor=approver.email, action="reject")


# ---- auto-approve ----


def test_auto_approve_condition_skips_the_human_step(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {
                "type": "approval", "mode": "quorum", "quorum": 1,
                "auto_approve_condition": {"<": [{"var": "amount"}, 1000]},
                "approvers": [{"type": "user", "user_id": str(uuid.uuid4())}],  # never actually resolved
                "on_approve": "end_ok", "on_reject": "end_bad",
            },
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.auto_approve", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={"amount": 50})
    assert instance.status == "completed"

    step = db_session.query(WorkflowStep).filter(WorkflowStep.instance_id == instance.id).one()
    assert step.acted_by == "system:auto-approve"


# ---- misconfiguration ----


def test_zero_resolved_approvers_raises_config_error(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "mode": "quorum", "quorum": 1, "approvers": [{"type": "role-in-scope", "role_id": str(uuid.uuid4())}], "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    definition = _publish(db_session, "test.zero_approvers", graph)
    entity_id = uuid.uuid4()
    with pytest.raises(engine.WorkflowConfigError):
        engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=entity_id, context={})

    # no half-done state (Part 5B section 2's own requirement): the instance is marked
    # failed, not left stuck "running" forever with no step anyone could ever act on.
    instance = db_session.query(WorkflowInstance).filter(WorkflowInstance.entity_id == entity_id).one()
    assert instance.status == "failed"
    assert instance.ended_at is not None


# ---- wait / timers ----


def test_wait_node_creates_a_timer_and_process_due_timers_resumes_it(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "wait", "duration_hours": 0, "next": "n2"},
            "n2": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.wait", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    assert instance.status == "running"
    assert instance.current_node_id == "n1"

    from datetime import datetime, timedelta, timezone

    processed = engine.process_due_timers(db_session, TENANT, now=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert processed == 1

    db_session.refresh(instance)
    assert instance.status == "completed"


def test_process_due_timers_does_not_fire_before_due(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "wait", "duration_hours": 100, "next": "n2"},
            "n2": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.wait_not_due", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})

    from datetime import datetime, timezone

    processed = engine.process_due_timers(db_session, TENANT, now=datetime.now(timezone.utc))
    assert processed == 0
    db_session.refresh(instance)
    assert instance.status == "running"


# ---- parallel branches (non-pausing) ----


def test_parallel_branches_of_actions_run_and_rejoin(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "parallel", "branches": ["b1", "b2"], "next": "end"},
            "b1": {"type": "action", "action": "set_field", "params": {"field": "b1_done", "value": True}, "next": "b1_end"},
            "b1_end": {"type": "branch_end"},
            "b2": {"type": "action", "action": "set_field", "params": {"field": "b2_done", "value": True}, "next": "b2_end"},
            "b2_end": {"type": "branch_end"},
            "end": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.parallel_branches", graph)
    instance = engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})
    assert instance.status == "completed"
    assert instance.context_json["b1_done"] is True
    assert instance.context_json["b2_done"] is True


def test_parallel_branch_hitting_a_pausing_node_raises_config_error(db_session):
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "parallel", "branches": ["b1"], "next": "end"},
            "b1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(uuid.uuid4())}], "mode": "quorum", "quorum": 1, "on_approve": "end", "on_reject": "end"},
            "end": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.parallel_pausing", graph)
    with pytest.raises(engine.WorkflowConfigError):
        engine.start_instance(db_session, TENANT, definition, entity_type="test", entity_id=uuid.uuid4(), context={})


# ---- sub_workflow ----


def test_sub_workflow_starts_a_child_instance(db_session):
    child_graph = {"start_node": "n1", "nodes": {"n1": {"type": "action", "action": "set_field", "params": {"field": "child_ran", "value": True}, "next": "end"}, "end": {"type": "end", "outcome": "approved"}}}
    child = _publish(db_session, "test.sub_child", child_graph)

    parent_graph = {"start_node": "n1", "nodes": {"n1": {"type": "sub_workflow", "definition_key": "test.sub_child", "next": "end"}, "end": {"type": "end", "outcome": "approved"}}}
    parent_def = _publish(db_session, "test.sub_parent", parent_graph)

    entity_id = uuid.uuid4()
    parent = engine.start_instance(db_session, TENANT, parent_def, entity_type="test", entity_id=entity_id, context={"x": 1})
    assert parent.status == "completed"

    child_instance = db_session.query(WorkflowInstance).filter(WorkflowInstance.definition_id == child.id, WorkflowInstance.entity_id == entity_id).first()
    assert child_instance is not None
    assert child_instance.context_json["child_ran"] is True


# ---- simulate() ----


def test_simulate_returns_the_path_up_to_the_first_human_step(db_session):
    approver = _make_user(db_session, email="simulate@example.com")
    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "condition", "jsonlogic": {">": [{"var": "amount"}, 100]}, "on_true": "n2", "on_false": "n3"},
            "n2": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end", "on_reject": "end"},
            "n3": {"type": "end", "outcome": "approved"},
            "end": {"type": "end", "outcome": "approved"},
        },
    }
    definition = _publish(db_session, "test.simulate", graph)

    path = engine.simulate(definition, {"amount": 500})
    assert [p["node_id"] for p in path] == ["n1", "n2"]
    assert path[-1]["type"] == "approval"

    other_path = engine.simulate(definition, {"amount": 10})
    assert [p["node_id"] for p in other_path] == ["n1", "n3"]
