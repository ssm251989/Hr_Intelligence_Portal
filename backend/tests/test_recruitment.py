"""Part 8 (docs/HRMS_COMPLETE_SPEC.txt): pipeline templates, job requisitions, hiring
team, offer CTC breakup, prompt registry, career-site knockout questions. `client` is
bridged to "Super Admin" via conftest.py's own bridge_single_user call."""

from datetime import date

import pytest

from app.models.application import APPLICATION_STATUSES
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.recruitment import career_site, ctc, hiring_team, pipeline, prompt_registry, requisitions

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title=kwargs.pop("title", "Backend Engineer"), status=kwargs.pop("status", "draft"), **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# ---- pipeline template parity ----


def test_seed_default_template_reproduces_every_application_status(db_session):
    template = pipeline.seed_default_template(db_session, TENANT)
    stages = pipeline.list_stages(db_session, TENANT, template.id)
    assert [s.code for s in stages] == list(APPLICATION_STATUSES)
    assert all(s.category in (
        "applied", "screening", "assessment", "interview", "offer", "preboarding", "hired", "rejected", "withdrawn",
    ) for s in stages)


def test_seed_default_template_is_idempotent(db_session):
    first = pipeline.seed_default_template(db_session, TENANT)
    second = pipeline.seed_default_template(db_session, TENANT)
    assert first.id == second.id
    assert len(pipeline.list_stages(db_session, TENANT, first.id)) == len(APPLICATION_STATUSES)


def test_create_template_with_is_default_unsets_the_previous_default(db_session):
    first = pipeline.create_template(db_session, TENANT, name="First", is_default=True)
    second = pipeline.create_template(db_session, TENANT, name="Second", is_default=True)
    db_session.refresh(first)
    assert first.is_default is False
    assert second.is_default is True


# ---- job requisitions ----


def test_request_approval_applies_immediately_when_no_workflow_is_published(db_session, monkeypatch):
    """This build's real tenant #1 always has `recruitment.job_requisition_approval`
    published (hrctl.seed_workflows) -- the un-gated fallback branch is exercised here by
    simulating "nothing published" directly, the same DefinitionNotFoundError
    core_hr.lifecycle's own equivalent test relies on the mechanism for."""
    from app.platform.workflow import definitions as workflow_definitions

    def _raise_not_found(db, tenant_id, key):
        raise workflow_definitions.DefinitionNotFoundError(key)

    monkeypatch.setattr(workflow_definitions, "get_published_definition", _raise_not_found)

    requisition = requisitions.create_requisition(db_session, TENANT, title="Backend Engineer", headcount=2)
    result = requisitions.request_approval(db_session, TENANT, requisition.id, actor_email="tester")
    assert result["applied"] is True
    assert result["status"] == "approved"


def test_request_approval_gates_behind_the_seeded_requisition_approval_workflow(db_session):
    """hrctl.seed_workflows already publishes a real `recruitment.job_requisition_
    approval` definition (v1) for tenant #1, gated on the Hiring Manager role -- this test
    publishes a v2 under the SAME key with a real, directly-assigned user approver (create_
    draft's own versioning means get_published_definition resolves the latest version), so
    the approver pool is deterministic regardless of which real users happen to hold the
    Hiring Manager role in whichever environment this test runs in."""
    import uuid

    from app.core.security import hash_password
    from app.models.user import User
    from app.platform.workflow import definitions
    from app.recruitment.requisitions import REQUISITION_APPROVAL_WORKFLOW_KEY

    approver = User(email=f"req-approver-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="Approver", role="recruiter")
    db_session.add(approver)
    db_session.commit()
    db_session.refresh(approver)

    graph = {
        "start_node": "n1",
        "nodes": {
            "n1": {"type": "approval", "approvers": [{"type": "user", "user_id": str(approver.id)}], "mode": "quorum", "quorum": 1, "on_approve": "end_ok", "on_reject": "end_bad"},
            "end_ok": {"type": "end", "outcome": "approved"},
            "end_bad": {"type": "end", "outcome": "rejected"},
        },
    }
    draft = definitions.create_draft(db_session, TENANT.tenant_id, key=REQUISITION_APPROVAL_WORKFLOW_KEY, name="Requisition approval v2", trigger={}, graph=graph)
    definitions.publish(db_session, draft, actor="test")

    requisition = requisitions.create_requisition(db_session, TENANT, title="Data Engineer")
    result = requisitions.request_approval(db_session, TENANT, requisition.id, actor_email="tester")

    assert result["applied"] is False
    assert result["workflow_instance_id"] is not None
    db_session.refresh(requisition)
    assert requisition.status == "pending_approval"


def test_request_approval_raises_for_unknown_requisition(db_session):
    import uuid

    with pytest.raises(ValueError):
        requisitions.request_approval(db_session, TENANT, uuid.uuid4(), actor_email="tester")


# ---- hiring team ----


def test_add_member_requires_a_user_or_external_name(db_session):
    job = _make_job(db_session)
    with pytest.raises(ValueError):
        hiring_team.add_member(db_session, TENANT, job_role_id=job.id, role_in_hiring="recruiter")


def test_add_and_list_external_hiring_team_member(db_session):
    job = _make_job(db_session)
    member = hiring_team.add_member(
        db_session, TENANT, job_role_id=job.id, role_in_hiring="interviewer_pool",
        external_name="External Panelist", external_email="panelist@example.com",
    )
    listed = hiring_team.list_members(db_session, TENANT, job.id)
    assert [m.id for m in listed] == [member.id]


# ---- CTC breakup / offers ----


def test_compute_ctc_breakup_applies_fixed_and_percentage_components(db_session):
    ctc.create_component(db_session, TENANT, code="basic", name="Basic", type="percentage_of_base", value=0.5)
    ctc.create_component(db_session, TENANT, code="bonus", name="Joining Bonus", type="fixed", value=50000)

    result = ctc.compute_ctc_breakup(db_session, TENANT, base_ctc=1000000)

    assert result["total"] == 550000.0
    by_code = {c["code"]: c["amount"] for c in result["components"]}
    assert by_code["basic"] == 500000.0
    assert by_code["bonus"] == 50000.0


def _make_offer(db_session) -> Offer:
    job = _make_job(db_session)
    from app.models.application import Application
    from app.models.candidate import Candidate

    candidate = Candidate(full_name="Alex Applicant", email="alex@example.com")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status="offer_sent")
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    offer = Offer(application_id=application.id)
    db_session.add(offer)
    db_session.commit()
    db_session.refresh(offer)
    return offer


def test_apply_ctc_breakup_to_offer_persists_the_breakdown(db_session):
    ctc.create_component(db_session, TENANT, code="basic2", name="Basic", type="fixed", value=800000)
    offer = _make_offer(db_session)

    updated = ctc.apply_ctc_breakup_to_offer(db_session, TENANT, offer.id, base_ctc=1000000)

    assert updated.ctc_breakup_json["total"] == 800000.0


def test_record_counter_offer_appends_entries(db_session):
    offer = _make_offer(db_session)
    ctc.record_counter_offer(db_session, TENANT, offer.id, amount=1200000, notes="Wants more")
    updated = ctc.record_counter_offer(db_session, TENANT, offer.id, amount=1300000, notes="Final ask")

    assert len(updated.counter_offer_json) == 2
    assert updated.counter_offer_json[-1]["amount"] == 1300000


def test_set_joining_date(db_session):
    offer = _make_offer(db_session)
    updated = ctc.set_joining_date(db_session, TENANT, offer.id, joining_date=date(2026, 11, 1))
    assert updated.joining_date == date(2026, 11, 1)


# ---- prompt registry ----


def test_prompt_registry_create_draft_and_publish(db_session):
    draft = prompt_registry.create_draft(db_session, TENANT, key="test.prompt", name="Test prompt", system_prompt="You are a test.")
    assert draft.status == "draft"
    with pytest.raises(prompt_registry.PromptNotFoundError):
        prompt_registry.get_published_prompt(db_session, TENANT, "test.prompt")

    published = prompt_registry.publish(db_session, draft)
    assert published.status == "published"
    fetched = prompt_registry.get_published_prompt(db_session, TENANT, "test.prompt")
    assert fetched.id == published.id


def test_get_or_seed_published_prompt_self_heals_a_missing_key(db_session):
    prompt = prompt_registry.get_or_seed_published_prompt(
        db_session, TENANT, key="test.self_heal", name="Self heal", default_system_prompt="Default text",
    )
    assert prompt.status == "published"
    assert prompt.system_prompt == "Default text"
    # Second call reuses the now-published row, doesn't create a v2.
    again = prompt_registry.get_or_seed_published_prompt(
        db_session, TENANT, key="test.self_heal", name="Self heal", default_system_prompt="Different text",
    )
    assert again.id == prompt.id
    assert again.system_prompt == "Default text"


# ---- career site ----


def test_evaluate_knockout_questions_disqualifies_on_matching_answer():
    questions = [{"question": "Willing to relocate?", "disqualify_on": "no"}]
    assert career_site.evaluate_knockout_questions(questions, {"Willing to relocate?": "no"}) is not None
    assert career_site.evaluate_knockout_questions(questions, {"Willing to relocate?": "yes"}) is None
    assert career_site.evaluate_knockout_questions([], {}) is None


def test_job_structured_data_includes_salary_band_when_present(db_session):
    job = _make_job(db_session, title="Senior Engineer", location="Bengaluru", salary_band_min=1000000, salary_band_max=1500000, jd_text="Build things.")
    payload = career_site.job_structured_data(job, "Acme Inc", "https://acme.example.com")

    assert payload["@type"] == "JobPosting"
    assert payload["title"] == "Senior Engineer"
    assert payload["baseSalary"]["value"]["minValue"] == 1000000.0
    assert payload["jobLocation"]["address"]["addressLocality"] == "Bengaluru"


# ---- API router ----


def test_api_seed_and_list_pipeline_templates(client):
    seeded = client.post("/api/v1/recruitment/pipeline-templates/seed-default")
    assert seeded.status_code == 200
    listed = client.get("/api/v1/recruitment/pipeline-templates")
    assert any(t["is_default"] for t in listed.json())

    template_id = seeded.json()["id"]
    stages = client.get(f"/api/v1/recruitment/pipeline-templates/{template_id}/stages")
    assert len(stages.json()) == len(APPLICATION_STATUSES)


def test_api_requisition_create_and_list(client):
    created = client.post("/api/v1/recruitment/requisitions", json={"title": "QA Engineer", "headcount": 1})
    assert created.status_code == 201

    listed = client.get("/api/v1/recruitment/requisitions")
    assert any(r["title"] == "QA Engineer" for r in listed.json())


def test_api_hiring_team_add_and_list(client, db_session):
    job = _make_job(db_session, title="API Hiring Team Role")
    added = client.post(f"/api/v1/recruitment/jobs/{job.id}/hiring-team", json={"role_in_hiring": "interviewer_pool", "external_name": "Panelist", "external_email": "p@example.com"})
    assert added.status_code == 201

    listed = client.get(f"/api/v1/recruitment/jobs/{job.id}/hiring-team")
    assert len(listed.json()) == 1


def test_api_interviewer_availability_upsert_and_list(client):
    upserted = client.put("/api/v1/recruitment/interviewer-availability", json={"interviewer_email": "api-interviewer@example.com", "interviewer_name": "API Interviewer"})
    assert upserted.status_code == 200

    listed = client.get("/api/v1/recruitment/interviewer-availability")
    assert any(r["interviewer_email"] == "api-interviewer@example.com" for r in listed.json())


def test_api_offer_components_and_ctc_breakup(client, db_session):
    created = client.post("/api/v1/recruitment/offer-components", json={"code": "api-basic", "name": "Basic", "type": "fixed", "value": 600000})
    assert created.status_code == 201

    offer = _make_offer(db_session)
    breakup = client.post(f"/api/v1/recruitment/offers/{offer.id}/ctc-breakup", json={"base_ctc": 1000000})
    assert breakup.status_code == 200
    assert breakup.json()["total"] >= 600000.0

    counter = client.post(f"/api/v1/recruitment/offers/{offer.id}/counter-offer", json={"amount": 1100000, "notes": "test"})
    assert counter.status_code == 200

    joining = client.post(f"/api/v1/recruitment/offers/{offer.id}/joining-date", json={"joining_date": "2026-12-01"})
    assert joining.status_code == 200
    assert joining.json()["joining_date"] == "2026-12-01"


def test_api_prompt_create_publish_and_list(client):
    created = client.post("/api/v1/recruitment/prompts", json={"key": "api.test.prompt", "name": "API Test Prompt", "system_prompt": "You are an API test."})
    assert created.status_code == 201
    prompt_id = created.json()["id"]

    published = client.post(f"/api/v1/recruitment/prompts/{prompt_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    listed = client.get("/api/v1/recruitment/prompts")
    assert any(p["key"] == "api.test.prompt" for p in listed.json())


def test_api_knockout_questions_and_structured_data(client, db_session):
    job = _make_job(db_session, title="Structured Data Role", status="published", jd_text="Build things.")
    updated = client.put(f"/api/v1/recruitment/jobs/{job.id}/knockout-questions", json={"questions": [{"question": "Relocate?", "disqualify_on": "no"}]})
    assert updated.status_code == 200
    assert len(updated.json()["questions"]) == 1

    structured = client.get(f"/api/v1/public/recruitment/jobs/{job.id}/structured-data")
    assert structured.status_code == 200
    assert structured.json()["title"] == "Structured Data Role"
