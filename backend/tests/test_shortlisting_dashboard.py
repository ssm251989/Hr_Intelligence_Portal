from datetime import datetime, timedelta, timezone

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.reports import stats

_NOW = datetime.now(timezone.utc)
_BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _months_ago(n: int, day: int = 10) -> datetime:
    month_start_boundary = stats.shift_months(stats.month_start(_NOW), -n)
    return month_start_boundary + timedelta(days=day - 1, hours=12)


def _make_job(db_session, title="Backend Engineer", **kwargs) -> JobRole:
    job = JobRole(title=title, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, full_name="Jane Doe", **kwargs) -> Candidate:
    candidate = Candidate(full_name=full_name, **kwargs)
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


def _make_audit_entry(db_session, entity_id, action, details=None, created_at=None):
    entry = AuditLog(
        entity_type="application", entity_id=entity_id, action=action, actor="system",
        details=details, created_at=created_at or _BASE_TIME,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _labeled_map(rows):
    return {row["label"]: row["count"] for row in rows}


def test_shortlisting_dashboard_requires_auth(anonymous_client):
    response = anonymous_client.get("/reports/shortlisting-dashboard-stats")
    assert response.status_code == 401


def test_shortlisting_dashboard_total_in_shortlisting_is_screened_backlog(client, db_session):
    before = client.get("/reports/shortlisting-dashboard-stats").json()

    job = _make_job(db_session)
    _make_application(db_session, job, _make_candidate(db_session, "Under Review One"), status="screened")
    _make_application(db_session, job, _make_candidate(db_session, "Not Yet Screened"), status="received")
    _make_application(db_session, job, _make_candidate(db_session, "Already Shortlisted"), status="hr_selected")

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    assert after["total_in_shortlisting"] - before["total_in_shortlisting"] == 1


def test_shortlisting_dashboard_funnel_counts_each_real_stage(client, db_session):
    before = client.get("/reports/shortlisting-dashboard-stats").json()
    before_funnel = {stage["label"]: stage["count"] for stage in before["funnel"]}

    job = _make_job(db_session)
    _make_application(db_session, job, _make_candidate(db_session, "Screened Only"), status="screened", composite_score=70)
    _make_application(
        db_session, job, _make_candidate(db_session, "Shortlisted One"), status="hr_selected", composite_score=88
    )
    on_hold_app = _make_application(
        db_session, job, _make_candidate(db_session, "On Hold One"), status="on_hold", composite_score=60
    )
    on_hold_app.previous_status = "screened"
    db_session.commit()
    _make_application(
        db_session, job, _make_candidate(db_session, "Rejected One"), status="hr_rejected", composite_score=40
    )
    # On hold from a DIFFERENT stage entirely -- must not count toward this module's On Hold bucket.
    unrelated_hold = _make_application(
        db_session, job, _make_candidate(db_session, "Unrelated Hold"), status="on_hold", composite_score=None
    )
    unrelated_hold.previous_status = "interview_scheduled"
    db_session.commit()

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    after_funnel = {stage["label"]: stage["count"] for stage in after["funnel"]}

    assert after_funnel["From Screening"] - before_funnel.get("From Screening", 0) == 4  # every composite_score set
    assert after_funnel["Under Review"] - before_funnel.get("Under Review", 0) == 1
    assert after_funnel["Shortlisted"] - before_funnel.get("Shortlisted", 0) == 1
    assert after_funnel["On Hold"] - before_funnel.get("On Hold", 0) == 1
    assert after_funnel["Rejected"] - before_funnel.get("Rejected", 0) == 1
    assert [stage["label"] for stage in after["funnel"]] == [
        "From Screening", "Under Review", "Shortlisted", "On Hold", "Rejected",
    ]


def test_shortlisting_dashboard_avg_composite_score_shortlisted_only_counts_hr_selected(client, db_session):
    from sqlalchemy import func

    prior_count, prior_sum = (
        db_session.query(func.count(Application.composite_score), func.coalesce(func.sum(Application.composite_score), 0))
        .filter(Application.status == "hr_selected", Application.composite_score.isnot(None))
        .one()
    )

    job = _make_job(db_session)
    _make_application(db_session, job, _make_candidate(db_session, "Shortlisted A"), status="hr_selected", composite_score=90.0)
    _make_application(db_session, job, _make_candidate(db_session, "Shortlisted B"), status="hr_selected", composite_score=50.0)
    # Screened but not yet decided -- must not affect the Shortlisted-only average.
    _make_application(db_session, job, _make_candidate(db_session, "Still Under Review"), status="screened", composite_score=10.0)

    after = client.get("/reports/shortlisting-dashboard-stats").json()

    expected_avg = round((float(prior_sum) + 90.0 + 50.0) / (prior_count + 2), 1)
    assert abs(after["avg_composite_score_shortlisted"] - expected_avg) < 0.05


def test_shortlisting_dashboard_moved_from_screening_and_shortlisted_this_month(client, db_session):
    before = client.get("/reports/shortlisting-dashboard-stats").json()

    job = _make_job(db_session)
    this_month = _months_ago(0)

    advanced_app = _make_application(db_session, job, _make_candidate(db_session, "Advanced"), status="screened")
    _make_audit_entry(
        db_session, advanced_app.id, "ai_screening_scored", {"advanced": True, "recommendation": "strong_fit"},
        created_at=this_month,
    )

    decided_app = _make_application(db_session, job, _make_candidate(db_session, "Decided"), status="hr_selected")
    _make_audit_entry(
        db_session, decided_app.id, "shortlist_status_updated",
        {"previous_shortlist_status": "under_review", "new_shortlist_status": "shortlisted", "new_application_status": "hr_selected"},
        created_at=this_month,
    )

    # Last month -- must not count toward "this month" for either metric.
    last_month_advanced = _make_application(db_session, job, _make_candidate(db_session, "Old Advance"), status="screened")
    _make_audit_entry(
        db_session, last_month_advanced.id, "ai_screening_scored", {"advanced": True, "recommendation": "strong_fit"},
        created_at=_months_ago(1),
    )

    after = client.get("/reports/shortlisting-dashboard-stats").json()

    assert after["moved_from_screening_this_month"] - before["moved_from_screening_this_month"] == 1
    assert after["shortlisted_this_month"] - before["shortlisted_this_month"] == 1


def test_shortlisting_dashboard_composite_score_distribution_matches_screening_pattern(client, db_session):
    before = client.get("/reports/shortlisting-dashboard-stats").json()
    before_buckets = _labeled_map(before["composite_score_distribution"])

    job = _make_job(db_session)
    _make_application(db_session, job, _make_candidate(db_session), status="hr_selected", composite_score=95)
    _make_application(db_session, job, _make_candidate(db_session), status="hr_rejected", composite_score=15)

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    after_buckets = _labeled_map(after["composite_score_distribution"])

    assert [row["label"] for row in after["composite_score_distribution"]] == list(stats.MATCH_SCORE_BUCKETS)
    assert after_buckets["90-100"] - before_buckets.get("90-100", 0) == 1
    assert after_buckets["0-29"] - before_buckets.get("0-29", 0) == 1


def test_shortlisting_dashboard_recent_shortlisted_only_includes_hr_selected(client, db_session):
    job = _make_job(db_session)
    shortlisted = _make_application(
        db_session, job, _make_candidate(db_session, "Recent Shortlisted"), status="hr_selected", composite_score=85
    )
    _make_application(db_session, job, _make_candidate(db_session, "Still Reviewing"), status="screened")

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    recent_ids = {row["application_id"] for row in after["recent_shortlisted"]}
    assert str(shortlisted.id) in recent_ids


# --- AI Insights: every sentence traces to a real query ---


def test_shortlisting_dashboard_insight_top_job_by_high_composite_score_pct(client, db_session):
    job = _make_job(db_session, title=f"InsightJob-{_BASE_TIME.timestamp()}")
    # 3 of 4 shortlisted candidates score above 85 -- 75%.
    for score in (90, 88, 86, 40):
        _make_application(db_session, job, _make_candidate(db_session), status="hr_selected", composite_score=score)

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    assert any(job.title in insight and "%" in insight for insight in after["insights"])


def test_shortlisting_dashboard_insight_most_common_rejection_reason(client, db_session):
    job = _make_job(db_session)
    this_month = _months_ago(0)
    for _ in range(3):
        app = _make_application(db_session, job, _make_candidate(db_session), status="hr_rejected")
        _make_audit_entry(
            db_session, app.id, "shortlist_status_updated",
            {"new_application_status": "hr_rejected", "reason": "QaZzInsufficientExperience"},
            created_at=this_month,
        )
    app = _make_application(db_session, job, _make_candidate(db_session), status="hr_rejected")
    _make_audit_entry(
        db_session, app.id, "shortlist_status_updated",
        {"new_application_status": "hr_rejected", "reason": "QaZzOtherReason"},
        created_at=this_month,
    )

    after = client.get("/reports/shortlisting-dashboard-stats").json()
    assert any("QaZzInsufficientExperience" in insight for insight in after["insights"])
