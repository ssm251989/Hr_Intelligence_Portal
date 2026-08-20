import uuid
from datetime import datetime, timedelta, timezone

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User
from app.reports import stats

_NOW = datetime.now(timezone.utc)


def _months_ago(n: int, day: int = 10) -> datetime:
    month_start_boundary = stats.shift_months(stats.month_start(_NOW), -n)
    return month_start_boundary + timedelta(days=day - 1, hours=12)


def _make_job(db_session, title="Backend Engineer") -> JobRole:
    job = JobRole(title=title)
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


def _make_application(db_session, job, candidate, status="interview_scheduled") -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_interviewer(db_session, full_name="Some Interviewer") -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name=full_name, role="interviewer"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_interview(
    db_session, application, *, scheduled_at=None, decision=None, scheduling_method="manual",
    interviewer=None, created_at=None,
) -> Interview:
    interview = Interview(
        application_id=application.id,
        interviewer_id=interviewer.id if interviewer else None,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        decision=decision,
        scheduling_method=scheduling_method,
    )
    db_session.add(interview)
    db_session.commit()
    db_session.refresh(interview)
    if created_at is not None:
        db_session.query(Interview).filter(Interview.id == interview.id).update({"created_at": created_at})
        db_session.commit()
        db_session.refresh(interview)
    return interview


def _labeled_map(rows):
    return {row["label"]: row["count"] for row in rows}


# --- total_interviews_scheduled_this_month ---


def test_interviews_dashboard_stats_total_this_month(client, db_session):
    before = client.get("/reports/interviews-dashboard-stats").json()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    this_month_app = _make_application(db_session, job, candidate)
    _make_interview(db_session, this_month_app, created_at=_months_ago(0))

    last_month_app = _make_application(db_session, job, candidate)
    _make_interview(db_session, last_month_app, created_at=_months_ago(1))

    after = client.get("/reports/interviews-dashboard-stats").json()

    assert after["total_interviews_scheduled_this_month"] - before["total_interviews_scheduled_this_month"] == 1


# --- upcoming (live backlog) ---


def test_interviews_dashboard_stats_upcoming_count(client, db_session):
    before = client.get("/reports/interviews-dashboard-stats").json()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    upcoming_app = _make_application(db_session, job, candidate)
    _make_interview(db_session, upcoming_app, scheduled_at=datetime.now(timezone.utc) + timedelta(days=2))

    past_no_decision_app = _make_application(db_session, job, candidate)
    _make_interview(db_session, past_no_decision_app, scheduled_at=datetime.now(timezone.utc) - timedelta(days=2))

    decided_app = _make_application(db_session, job, candidate, status="interview_selected")
    _make_interview(
        db_session, decided_app, scheduled_at=datetime.now(timezone.utc) + timedelta(days=2), decision="selected"
    )

    after = client.get("/reports/interviews-dashboard-stats").json()

    assert after["upcoming"] - before["upcoming"] == 1


# --- completed / selected / rejected ---


def test_interviews_dashboard_stats_completed_selected_rejected_counts(client, db_session):
    before = client.get("/reports/interviews-dashboard-stats").json()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    selected_app = _make_application(db_session, job, candidate, status="interview_selected")
    _make_interview(db_session, selected_app, decision="selected")

    rejected_app = _make_application(db_session, job, candidate, status="interview_rejected")
    _make_interview(db_session, rejected_app, decision="rejected")

    pending_app = _make_application(db_session, job, candidate)
    _make_interview(db_session, pending_app, decision=None)

    after = client.get("/reports/interviews-dashboard-stats").json()

    assert after["completed"] - before["completed"] == 2
    assert after["selected"] - before["selected"] == 1
    assert after["rejected"] - before["rejected"] == 1


# --- outcome_breakdown ---


def test_interviews_dashboard_stats_outcome_breakdown_always_three_buckets(client, db_session):
    before = client.get("/reports/interviews-dashboard-stats").json()
    before_breakdown = _labeled_map(before["outcome_breakdown"])

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_interview(db_session, _make_application(db_session, job, candidate, status="interview_selected"), decision="selected")
    _make_interview(db_session, _make_application(db_session, job, candidate, status="interview_rejected"), decision="rejected")
    _make_interview(db_session, _make_application(db_session, job, candidate), decision=None)
    _make_interview(db_session, _make_application(db_session, job, candidate), decision=None)

    after = client.get("/reports/interviews-dashboard-stats").json()
    after_breakdown = _labeled_map(after["outcome_breakdown"])

    assert set(after_breakdown.keys()) == {"Selected", "Rejected", "Pending decision"}
    assert after_breakdown["Selected"] - before_breakdown.get("Selected", 0) == 1
    assert after_breakdown["Rejected"] - before_breakdown.get("Rejected", 0) == 1
    assert after_breakdown["Pending decision"] - before_breakdown.get("Pending decision", 0) == 2


# --- interviewer_workload ---


def test_interviews_dashboard_stats_interviewer_workload_and_unassigned(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    interviewer = _make_interviewer(db_session, full_name="zzWorkloadInterviewer")

    before = client.get("/reports/interviews-dashboard-stats").json()
    before_workload = _labeled_map(before["interviewer_workload"])
    before_unassigned = before_workload.get("Unassigned", 0)

    for _ in range(3):
        _make_interview(db_session, _make_application(db_session, job, candidate), interviewer=interviewer)
    _make_interview(db_session, _make_application(db_session, job, candidate), interviewer=None)

    after = client.get("/reports/interviews-dashboard-stats").json()
    after_workload = _labeled_map(after["interviewer_workload"])

    assert after_workload.get("zzWorkloadInterviewer", 0) == 3
    assert after_workload.get("Unassigned", 0) - before_unassigned == 1


# --- scheduling_method_breakdown (auto vs manual) ---


def test_interviews_dashboard_stats_scheduling_method_breakdown(client, db_session):
    before = client.get("/reports/interviews-dashboard-stats").json()
    before_breakdown = _labeled_map(before["scheduling_method_breakdown"])

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_interview(db_session, _make_application(db_session, job, candidate), scheduling_method="manual")
    _make_interview(db_session, _make_application(db_session, job, candidate), scheduling_method="auto")
    _make_interview(db_session, _make_application(db_session, job, candidate), scheduling_method="auto")

    after = client.get("/reports/interviews-dashboard-stats").json()
    after_breakdown = _labeled_map(after["scheduling_method_breakdown"])

    assert set(after_breakdown.keys()) == {"Manually-Scheduled", "Auto-Scheduled"}
    assert after_breakdown["Manually-Scheduled"] - before_breakdown.get("Manually-Scheduled", 0) == 1
    assert after_breakdown["Auto-Scheduled"] - before_breakdown.get("Auto-Scheduled", 0) == 2


# --- recent_interviews ---


def test_interviews_dashboard_stats_recent_interviews_shape(client, db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, full_name="zzRecentInterviewCandidate")
    interviewer = _make_interviewer(db_session, full_name="zzRecentInterviewer")
    application = _make_application(db_session, job, candidate)
    interview = _make_interview(db_session, application, interviewer=interviewer, scheduling_method="auto")

    after = client.get("/reports/interviews-dashboard-stats").json()
    row = next(r for r in after["recent_interviews"] if r["interview_id"] == str(interview.id))

    assert row["candidate_name"] == "zzRecentInterviewCandidate"
    assert row["interviewer_name"] == "zzRecentInterviewer"
    assert row["job_title"] == job.title
    assert row["scheduling_method"] == "auto"
    assert row["status"] in ("upcoming", "awaiting_feedback")


def test_interviews_dashboard_stats_compare_month_out_of_range_rejected(client):
    response = client.get("/reports/interviews-dashboard-stats", params={"compare_month": "1999-01"})
    assert response.status_code == 400


def test_interviews_dashboard_stats_requires_auth(anonymous_client):
    response = anonymous_client.get("/reports/interviews-dashboard-stats")
    assert response.status_code == 401
