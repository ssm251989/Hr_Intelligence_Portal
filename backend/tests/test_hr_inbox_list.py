"""The "HR Inbox" list view (app/hr_inbox/router.py list_hr_inbox/export_hr_inbox) --
same Dashboard+List architecture already used elsewhere in this app, and the same
role gating as POST /applications/{id}/message (recruiter/hiring_manager/admin can view;
configuring the mailbox itself, tested in test_integrations.py, stays admin-only)."""

import uuid
from datetime import datetime, timezone

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.job_role import JobRole


def _make_email(db_session, **kwargs) -> HrInboundEmail:
    defaults = dict(
        from_address=f"{uuid.uuid4().hex[:8]}@example.com",
        subject="Following up",
        body="body",
        received_at=datetime.now(timezone.utc),
        message_id=f"<{uuid.uuid4().hex}@example.com>",
    )
    defaults.update(kwargs)
    row = HrInboundEmail(**defaults)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_hr_inbox_list_requires_authentication(anonymous_client):
    response = anonymous_client.get("/hr-inbox/list")
    assert response.status_code == 401


def test_hr_inbox_list_denies_interviewer_role(client, make_auth_headers):
    headers = make_auth_headers(role="interviewer", email="interviewer-inbox@example.com")
    response = client.get("/hr-inbox/list", headers=headers)
    assert response.status_code == 403


def test_hr_inbox_list_allows_recruiter(client, db_session, make_auth_headers):
    _make_email(db_session)
    headers = make_auth_headers(role="recruiter", email="recruiter-inbox@example.com")
    response = client.get("/hr-inbox/list", headers=headers)
    assert response.status_code == 200


def test_hr_inbox_list_returns_matched_and_unmatched_rows(client, db_session):
    job = JobRole(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    candidate = Candidate(full_name="Jane Doe", email="jane@example.com")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status="received")
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    matched = _make_email(
        db_session, from_address="jane@example.com",
        matched_candidate_id=candidate.id, matched_application_id=application.id,
    )
    unmatched = _make_email(db_session, from_address="stranger@example.com")

    response = client.get("/hr-inbox/list")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(matched.id)]["matched_candidate_name"] == "Jane Doe"
    assert by_id[str(matched.id)]["matched_job_title"] == "Backend Engineer"
    assert by_id[str(unmatched.id)]["matched_candidate_name"] is None


def test_hr_inbox_list_filters_by_matched(client, db_session):
    job = JobRole(title="Filter Job")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    candidate = Candidate(full_name="Matched Candidate", email="matched@example.com")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    matched = _make_email(db_session, from_address="matched@example.com", matched_candidate_id=candidate.id)
    unmatched = _make_email(db_session, from_address="unmatched@example.com")

    only_matched = client.get("/hr-inbox/list", params={"matched": "true"}).json()
    only_unmatched = client.get("/hr-inbox/list", params={"matched": "false"}).json()

    assert {item["id"] for item in only_matched["items"]} == {str(matched.id)}
    assert {item["id"] for item in only_unmatched["items"]} == {str(unmatched.id)}


def test_hr_inbox_list_filters_by_search(client, db_session):
    target = _make_email(db_session, from_address="specific-sender@example.com", subject="Unique Subject Line")
    _make_email(db_session, from_address="other@example.com", subject="Something else")

    response = client.get("/hr-inbox/list", params={"search": "specific-sender"})

    assert {item["id"] for item in response.json()["items"]} == {str(target.id)}


def test_hr_inbox_list_paginates(client, db_session):
    for _ in range(3):
        _make_email(db_session)

    page_1 = client.get("/hr-inbox/list", params={"page": 1, "page_size": 2}).json()
    page_2 = client.get("/hr-inbox/list", params={"page": 2, "page_size": 2}).json()

    assert page_1["total"] == 3
    assert len(page_1["items"]) == 2
    assert len(page_2["items"]) == 1


def test_hr_inbox_export_requires_authentication(anonymous_client):
    response = anonymous_client.get("/hr-inbox/export")
    assert response.status_code == 401


def test_hr_inbox_export_denies_interviewer_role(client, make_auth_headers):
    headers = make_auth_headers(role="interviewer", email="interviewer-export@example.com")
    response = client.get("/hr-inbox/export", headers=headers)
    assert response.status_code == 403


def test_hr_inbox_export_allows_hiring_manager_and_returns_every_matching_row(client, db_session, make_auth_headers):
    for _ in range(3):
        _make_email(db_session)
    headers = make_auth_headers(role="hiring_manager", email="hiring-manager-export@example.com")

    response = client.get("/hr-inbox/export", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 3
