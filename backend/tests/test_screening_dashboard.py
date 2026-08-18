from datetime import datetime, timedelta, timezone

from sqlalchemy import func

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
        entity_type="application",
        entity_id=entity_id,
        action=action,
        actor="system",
        details=details,
        created_at=created_at or _BASE_TIME,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def _labeled_map(rows):
    return {row["label"]: row["count"] for row in rows}


# --- awaiting_screening / awaiting_ranking (live backlog counts) ---


def test_screening_dashboard_stats_awaiting_screening_and_ranking_counts(client, db_session):
    before = client.get("/reports/screening-dashboard-stats").json()

    job = _make_job(db_session)
    received_candidate = _make_candidate(db_session, full_name="Awaiting Screen")
    _make_application(db_session, job, received_candidate, status="received")

    screened_unranked_candidate = _make_candidate(db_session, full_name="Awaiting Rank")
    _make_application(
        db_session, job, screened_unranked_candidate, status="screened", match_score=80, ranking_score=None
    )

    screened_ranked_candidate = _make_candidate(db_session, full_name="Already Ranked")
    _make_application(
        db_session, job, screened_ranked_candidate, status="screened", match_score=80, ranking_score=75
    )

    decided_candidate = _make_candidate(db_session, full_name="Already Decided")
    _make_application(db_session, job, decided_candidate, status="hr_selected")

    after = client.get("/reports/screening-dashboard-stats").json()

    assert after["awaiting_screening"] - before["awaiting_screening"] == 1
    assert after["awaiting_ranking"] - before["awaiting_ranking"] == 1


# --- avg_composite_score / composite_score_distribution ---


def test_screening_dashboard_stats_avg_composite_score(client, db_session):
    prior_count, prior_sum = (
        db_session.query(func.count(Application.composite_score), func.coalesce(func.sum(Application.composite_score), 0))
        .filter(Application.composite_score.isnot(None))
        .one()
    )

    job = _make_job(db_session)
    candidate_a = _make_candidate(db_session, full_name="Composite A")
    candidate_b = _make_candidate(db_session, full_name="Composite B")
    uncomposited_candidate = _make_candidate(db_session, full_name="Uncomposited")
    _make_application(db_session, job, candidate_a, composite_score=90.0)
    _make_application(db_session, job, candidate_b, composite_score=50.0)
    _make_application(db_session, job, uncomposited_candidate, composite_score=None)

    body = client.get("/reports/screening-dashboard-stats").json()

    expected_avg = (float(prior_sum) + 90.0 + 50.0) / (prior_count + 2)
    assert abs(body["avg_composite_score"] - expected_avg) < 0.05


def test_screening_dashboard_stats_composite_score_distribution_buckets(client, db_session):
    before = client.get("/reports/screening-dashboard-stats").json()
    before_buckets = _labeled_map(before["composite_score_distribution"])

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_application(db_session, job, candidate, composite_score=95)
    _make_application(db_session, job, candidate, composite_score=75)
    _make_application(db_session, job, candidate, composite_score=55)
    _make_application(db_session, job, candidate, composite_score=35)
    _make_application(db_session, job, candidate, composite_score=15)
    _make_application(db_session, job, candidate, composite_score=None)  # never bucketed

    after = client.get("/reports/screening-dashboard-stats").json()
    after_buckets = _labeled_map(after["composite_score_distribution"])

    assert [row["label"] for row in after["composite_score_distribution"]] == list(stats.MATCH_SCORE_BUCKETS)
    for bucket in ("90-100", "70-89", "50-69", "30-49", "0-29"):
        assert after_buckets[bucket] - before_buckets.get(bucket, 0) == 1


# --- recommendation_breakdown (latest ai_screening_scored entry per application) ---


def test_screening_dashboard_stats_recommendation_breakdown_uses_latest_entry_only(client, db_session):
    before = client.get("/reports/screening-dashboard-stats").json()
    before_breakdown = _labeled_map(before["recommendation_breakdown"])

    job = _make_job(db_session)

    strong_candidate = _make_candidate(db_session, full_name="Strong Fit")
    strong_app = _make_application(db_session, job, strong_candidate, status="screened")
    _make_audit_entry(db_session, strong_app.id, "ai_screening_scored", {"recommendation": "strong_fit"})

    # Re-screened: the OLDER entry says weak_fit, but the latest (newer created_at) says
    # possible_fit -- only the latest may count.
    rescored_candidate = _make_candidate(db_session, full_name="Re-scored")
    rescored_app = _make_application(db_session, job, rescored_candidate, status="screened")
    _make_audit_entry(
        db_session, rescored_app.id, "ai_screening_scored", {"recommendation": "weak_fit"}, created_at=_BASE_TIME
    )
    _make_audit_entry(
        db_session,
        rescored_app.id,
        "ai_screening_scored",
        {"recommendation": "possible_fit"},
        created_at=_BASE_TIME + timedelta(hours=1),
    )

    # Never screened at all -- must not appear in any bucket.
    never_screened_candidate = _make_candidate(db_session, full_name="Never Screened")
    _make_application(db_session, job, never_screened_candidate, status="received")

    # Latest entry is a FAILURE, not a scored result -- must not appear in any bucket either.
    failed_candidate = _make_candidate(db_session, full_name="Failed Only")
    failed_app = _make_application(db_session, job, failed_candidate, status="received")
    _make_audit_entry(db_session, failed_app.id, "ai_screening_failed", {"error": "boom"})

    after = client.get("/reports/screening-dashboard-stats").json()
    after_breakdown = _labeled_map(after["recommendation_breakdown"])

    assert after_breakdown["Strong fit"] - before_breakdown.get("Strong fit", 0) == 1
    assert after_breakdown["Possible fit"] - before_breakdown.get("Possible fit", 0) == 1
    assert after_breakdown["Weak fit"] - before_breakdown.get("Weak fit", 0) == 0
    assert set(after_breakdown.keys()) == {"Strong fit", "Possible fit", "Weak fit"}


# --- top_missing_skills ---


def test_screening_dashboard_stats_top_missing_skills_frequency(client, db_session):
    before = client.get("/reports/screening-dashboard-stats").json()
    before_skills = _labeled_map(before["top_missing_skills"])

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    for _ in range(20):
        _make_application(
            db_session, job, _make_candidate(db_session), missing_skills=["QaZzMissingAlpha", "QaZzMissingBeta"]
        )
    for _ in range(12):
        _make_application(db_session, job, _make_candidate(db_session), missing_skills=["QaZzMissingAlpha"])
    _make_application(db_session, job, candidate, missing_skills=None)

    after = client.get("/reports/screening-dashboard-stats").json()
    after_skills = _labeled_map(after["top_missing_skills"])

    assert len(after["top_missing_skills"]) <= 5
    assert after_skills.get("QaZzMissingAlpha", 0) - before_skills.get("QaZzMissingAlpha", 0) == 32
    assert after_skills.get("QaZzMissingBeta", 0) - before_skills.get("QaZzMissingBeta", 0) == 20


# --- auto_advanced_this_month / failed_this_month ---


def test_screening_dashboard_stats_auto_advanced_and_failed_this_month(client, db_session):
    before = client.get("/reports/screening-dashboard-stats").json()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    this_month = _months_ago(0)

    advanced_app = _make_application(db_session, job, candidate, status="screened")
    _make_audit_entry(
        db_session, advanced_app.id, "ai_screening_scored", {"advanced": True, "recommendation": "strong_fit"},
        created_at=this_month,
    )

    not_advanced_app = _make_application(db_session, job, candidate, status="received")
    _make_audit_entry(
        db_session, not_advanced_app.id, "ai_screening_scored", {"advanced": False, "recommendation": "weak_fit"},
        created_at=this_month,
    )

    failed_app = _make_application(db_session, job, candidate, status="received")
    _make_audit_entry(db_session, failed_app.id, "ai_screening_failed", {"error": "timeout"}, created_at=this_month)

    # Last month -- must not count toward "this month".
    last_month_app = _make_application(db_session, job, candidate, status="screened")
    _make_audit_entry(
        db_session, last_month_app.id, "ai_screening_scored", {"advanced": True, "recommendation": "strong_fit"},
        created_at=_months_ago(1),
    )

    after = client.get("/reports/screening-dashboard-stats").json()

    assert after["auto_advanced_this_month"] - before["auto_advanced_this_month"] == 1
    assert after["failed_this_month"] - before["failed_this_month"] == 1


def test_screening_dashboard_stats_compare_month_out_of_range_rejected(client):
    response = client.get("/reports/screening-dashboard-stats", params={"compare_month": "1999-01"})
    assert response.status_code == 400


def test_screening_dashboard_stats_requires_auth(anonymous_client):
    response = anonymous_client.get("/reports/screening-dashboard-stats")
    assert response.status_code == 401
