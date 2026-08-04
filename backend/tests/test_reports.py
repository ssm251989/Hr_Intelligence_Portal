import uuid
from datetime import datetime, timedelta, timezone

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole

_BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(db_session, **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, full_name="Jane Doe") -> Candidate:
    candidate = Candidate(full_name=full_name)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="received", **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_audit_entry(db_session, entity_type, entity_id, action, actor="system", details=None, created_at=None):
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=details,
        created_at=created_at or _BASE_TIME,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _by_status_map(body):
    return {row["status"]: row["count"] for row in body["by_status"]}


# --- /reports/pipeline ---


def test_pipeline_counts_without_job_filter(client, db_session):
    # Delta against a before-snapshot, since this endpoint has no filter to scope out
    # unrelated rows that may already exist in the database.
    before_by_status = _by_status_map(client.get("/reports/pipeline").json())

    job1 = _make_job(db_session)
    job2 = _make_job(db_session)
    candidate = _make_candidate(db_session)

    _make_application(db_session, job1, candidate, status="received")
    _make_application(db_session, job1, candidate, status="received")
    _make_application(db_session, job1, candidate, status="screened")
    _make_application(db_session, job2, candidate, status="received")
    _make_application(db_session, job2, candidate, status="hr_selected")

    response = client.get("/reports/pipeline")

    assert response.status_code == 200
    body = response.json()
    after_by_status = _by_status_map(body)
    added = {
        status: after_by_status.get(status, 0) - before_by_status.get(status, 0)
        for status in ("received", "screened", "hr_selected")
    }
    assert added == {"received": 3, "screened": 1, "hr_selected": 1}
    # Ordered per the application lifecycle, not insertion or alphabetical order.
    statuses = [row["status"] for row in body["by_status"] if row["status"] in added]
    assert statuses == ["received", "screened", "hr_selected"]


def test_pipeline_counts_with_job_filter(client, db_session):
    job1 = _make_job(db_session)
    job2 = _make_job(db_session)
    candidate = _make_candidate(db_session)

    _make_application(db_session, job1, candidate, status="received")
    _make_application(db_session, job1, candidate, status="received")
    _make_application(db_session, job1, candidate, status="screened")
    _make_application(db_session, job2, candidate, status="hr_selected")

    response = client.get(f"/reports/pipeline?job_role_id={job1.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert _by_status_map(body) == {"received": 2, "screened": 1}


def test_pipeline_empty(client):
    # Filter to a job_role_id no application can reference, so this is robust
    # against unrelated rows already present in the database.
    response = client.get(f"/reports/pipeline?job_role_id={uuid.uuid4()}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["by_status"] == []


# --- /reports/jobs/{id}/summary ---


def test_job_summary_computes_counts_and_averages(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    _make_application(db_session, job, candidate, status="received")
    _make_application(db_session, job, candidate, status="screened", match_score=80.0, ranking_score=None)
    _make_application(db_session, job, candidate, status="screened", match_score=90.0, ranking_score=85.0)

    response = client.get(f"/reports/jobs/{job.id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["job_role_id"] == str(job.id)
    assert body["total_applications"] == 3
    assert _by_status_map(body) == {"received": 1, "screened": 2}
    # Average only over non-null scores: (80 + 90) / 2 and a single ranking_score of 85.
    assert body["average_match_score"] == 85.0
    assert body["average_ranking_score"] == 85.0
    assert isinstance(body["average_match_score"], float)


def test_job_summary_zero_applications(client, db_session):
    job = _make_job(db_session)

    response = client.get(f"/reports/jobs/{job.id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_applications"] == 0
    assert body["by_status"] == []
    assert body["average_match_score"] is None
    assert body["average_ranking_score"] is None


def test_job_summary_not_found(client):
    response = client.get(f"/reports/jobs/{uuid.uuid4()}/summary")
    assert response.status_code == 404


# --- /reports/audit ---


def test_audit_filter_by_entity_type(client, db_session):
    app_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    _make_audit_entry(db_session, "application", app_id, "application_created")
    _make_audit_entry(db_session, "application", app_id, "salary_validated")
    _make_audit_entry(db_session, "bgv_document", doc_id, "bgv_document_uploaded")

    # Combined with entity_id so this is scoped to rows this test created, robust
    # against unrelated "application" audit_log rows already in the database.
    response = client.get(f"/reports/audit?entity_type=application&entity_id={app_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["entity_type"] == "application" for item in body["items"])


def test_audit_filter_by_entity_id(client, db_session):
    app_id_a = uuid.uuid4()
    app_id_b = uuid.uuid4()
    _make_audit_entry(db_session, "application", app_id_a, "application_created")
    _make_audit_entry(db_session, "application", app_id_a, "salary_validated")
    _make_audit_entry(db_session, "application", app_id_b, "application_created")

    response = client.get(f"/reports/audit?entity_id={app_id_a}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["entity_id"] == str(app_id_a) for item in body["items"])


def test_audit_filter_by_action(client, db_session):
    app_id = uuid.uuid4()
    _make_audit_entry(db_session, "application", app_id, "salary_validated")
    _make_audit_entry(db_session, "application", app_id, "salary_approval_decision")
    _make_audit_entry(db_session, "application", uuid.uuid4(), "salary_validated")

    # Combined with entity_id so this is scoped to rows this test created, robust
    # against unrelated "salary_approval_decision" audit_log rows already in the database.
    response = client.get(f"/reports/audit?action=salary_approval_decision&entity_id={app_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "salary_approval_decision"


def test_audit_filter_combination_narrows_to_exact_match(client, db_session):
    app_id = uuid.uuid4()
    _make_audit_entry(db_session, "application", app_id, "salary_validated")
    _make_audit_entry(db_session, "application", app_id, "salary_approval_decision")
    _make_audit_entry(db_session, "bgv_document", app_id, "salary_validated")

    response = client.get(f"/reports/audit?entity_type=application&entity_id={app_id}&action=salary_validated")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "application"
    assert body["items"][0]["action"] == "salary_validated"


def test_audit_ordered_by_created_at_descending(client, db_session):
    entity_id = uuid.uuid4()
    # Insert out of chronological order to prove the endpoint sorts, not just returns insertion order.
    _make_audit_entry(db_session, "application", entity_id, "middle", created_at=_BASE_TIME + timedelta(minutes=5))
    _make_audit_entry(db_session, "application", entity_id, "oldest", created_at=_BASE_TIME)
    _make_audit_entry(db_session, "application", entity_id, "newest", created_at=_BASE_TIME + timedelta(minutes=10))

    response = client.get(f"/reports/audit?entity_id={entity_id}")

    assert response.status_code == 200
    actions = [item["action"] for item in response.json()["items"]]
    assert actions == ["newest", "middle", "oldest"]


def test_audit_pagination(client, db_session):
    entity_id = uuid.uuid4()
    for i in range(5):
        _make_audit_entry(
            db_session, "application", entity_id, f"event_{i}", created_at=_BASE_TIME + timedelta(minutes=i)
        )

    first_page = client.get(f"/reports/audit?entity_id={entity_id}&limit=2&offset=0").json()
    second_page = client.get(f"/reports/audit?entity_id={entity_id}&limit=2&offset=2").json()

    assert first_page["total"] == 5
    assert second_page["total"] == 5
    assert [item["action"] for item in first_page["items"]] == ["event_4", "event_3"]
    assert [item["action"] for item in second_page["items"]] == ["event_2", "event_1"]


# --- /applications/{id}/timeline ---


def test_timeline_returns_chronological_order_for_this_application_only(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    other_application = _make_application(db_session, job, candidate)

    # Inserted out of order to prove the endpoint sorts ascending, not just echoes insertion order.
    _make_audit_entry(
        db_session, "application", application.id, "screened", created_at=_BASE_TIME + timedelta(minutes=10)
    )
    _make_audit_entry(
        db_session, "application", application.id, "application_created", created_at=_BASE_TIME
    )
    _make_audit_entry(
        db_session, "application", application.id, "hr_shortlisting_decision",
        created_at=_BASE_TIME + timedelta(minutes=5),
    )
    _make_audit_entry(
        db_session, "application", other_application.id, "application_created", created_at=_BASE_TIME
    )

    response = client.get(f"/applications/{application.id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == str(application.id)
    actions = [event["action"] for event in body["events"]]
    assert actions == ["application_created", "hr_shortlisting_decision", "screened"]


def test_timeline_empty_for_application_with_no_audit_entries(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    response = client.get(f"/applications/{application.id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == str(application.id)
    assert body["events"] == []


def test_timeline_not_found(client):
    response = client.get(f"/applications/{uuid.uuid4()}/timeline")
    assert response.status_code == 404
