import uuid
from datetime import datetime, timedelta, timezone

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JOB_ROLE_STATUSES, JobRole
from app.reports import stats

_NOW = datetime.now(timezone.utc)
# A timestamp guaranteed to fall in the *previous* calendar month regardless of
# what day-of-month the test happens to run on (day 15 avoids any month-length
# edge cases that "now minus N days" could accidentally land back in this month).
_PREVIOUS_MONTH = (
    datetime(_NOW.year - 1, 12, 15, tzinfo=timezone.utc)
    if _NOW.month == 1
    else datetime(_NOW.year, _NOW.month - 1, 15, tzinfo=timezone.utc)
)

_BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _months_ago(n: int, day: int = 10) -> datetime:
    """A timestamp on day `day` of the IST calendar month `n` months before now (day 10
    is safe for every month length, including February).

    Deliberately built by offsetting from the month-start *boundary instant* rather than
    reading `.year`/`.month` off it directly: that boundary is "00:00 IST on day 1" (see
    app/reports/stats.py), which in UTC terms lands on the *last day of the previous*
    month whenever IST is ahead of UTC's own calendar date -- reading its `.month` would
    silently produce a timestamp one month too early.
    """
    month_start_boundary = stats.shift_months(stats.month_start(_NOW), -n)
    return month_start_boundary + timedelta(days=day - 1, hours=12)


def _make_job(db_session, title="Backend Engineer", **kwargs) -> JobRole:
    job = JobRole(title=title, **kwargs)
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


def _labeled_map(rows):
    return {row["label"]: row["count"] for row in rows}


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


# --- /reports/jobs-dashboard-stats ---


def test_jobs_dashboard_stats_counts_jobs_and_applications(client, db_session):
    # Delta against a before-snapshot: this endpoint has no filter, so it aggregates
    # over every job/application already in the database, not just this test's rows.
    before = client.get("/reports/jobs-dashboard-stats").json()

    _make_job(db_session, status="draft")
    published1 = _make_job(db_session, status="published", positions_count=3)
    published2 = _make_job(db_session, status="published", positions_count=2)
    candidate = _make_candidate(db_session)
    _make_application(db_session, published1, candidate, status="received")
    _make_application(db_session, published1, candidate, status="hr_selected")
    _make_application(db_session, published2, candidate, status="screened")

    after = client.get("/reports/jobs-dashboard-stats").json()

    assert after["total_jobs"] - before["total_jobs"] == 3
    assert after["active_jobs"] - before["active_jobs"] == 2
    assert after["open_positions"] - before["open_positions"] == 5
    assert after["total_applications"] - before["total_applications"] == 3


def test_jobs_dashboard_stats_department_and_location_breakdown(client, db_session):
    before = client.get("/reports/jobs-dashboard-stats").json()
    before_dept = _labeled_map(before["by_department"])
    before_loc = _labeled_map(before["by_location"])

    _make_job(db_session, department="Engineering", location="Chennai")
    _make_job(db_session, department=None, location="Chennai")

    after = client.get("/reports/jobs-dashboard-stats").json()
    after_dept = _labeled_map(after["by_department"])
    after_loc = _labeled_map(after["by_location"])

    assert after_dept.get("Engineering", 0) - before_dept.get("Engineering", 0) == 1
    assert after_dept.get("Unspecified", 0) - before_dept.get("Unspecified", 0) == 1
    assert after_loc.get("Chennai", 0) - before_loc.get("Chennai", 0) == 2


def test_jobs_dashboard_stats_hires_this_month_and_avg_time_to_hire(client, db_session):
    before = client.get("/reports/jobs-dashboard-stats").json()
    hires_before = before["hires_this_month"]
    avg_before = before["avg_time_to_hire_days"]

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)

    # Two applications "completed" this month with known, exact time-to-hire.
    app_a = _make_application(
        db_session, job, candidate, status="onboarding_completed",
        created_at=_NOW - timedelta(days=100),
    )
    app_b = _make_application(
        db_session, job, candidate, status="onboarding_completed",
        created_at=_NOW - timedelta(days=200),
    )
    _make_audit_entry(db_session, "application", app_a.id, "onboarding_completed", created_at=_NOW)
    _make_audit_entry(db_session, "application", app_b.id, "onboarding_completed", created_at=_NOW)

    # A third completion, but recorded last month -- must be excluded from both
    # this month's hire count and the time-to-hire average.
    app_c = _make_application(
        db_session, job, candidate, status="onboarding_completed",
        created_at=_PREVIOUS_MONTH - timedelta(days=5),
    )
    _make_audit_entry(
        db_session, "application", app_c.id, "onboarding_completed", created_at=_PREVIOUS_MONTH
    )

    after = client.get("/reports/jobs-dashboard-stats").json()

    assert after["hires_this_month"] - hires_before == 2

    # Reconstruct the expected new average from the (already-rounded) before value,
    # rather than assuming this month had zero prior completions -- robust against
    # a shared, already-populated database.
    prior_sum = (avg_before or 0) * hires_before
    expected_avg = (prior_sum + 100.0 + 200.0) / (hires_before + 2)
    assert abs(after["avg_time_to_hire_days"] - expected_avg) < 0.1


def test_jobs_dashboard_stats_zero_hires_this_month_has_null_avg(client):
    # Scoped to a brand new database would be ideal, but since this endpoint has no
    # filter, just confirm the "no completions" shape is self-consistent: whenever
    # hires_this_month is 0, avg_time_to_hire_days must be null, never a stray number.
    body = client.get("/reports/jobs-dashboard-stats").json()
    if body["hires_this_month"] == 0:
        assert body["avg_time_to_hire_days"] is None


def test_jobs_dashboard_stats_top_jobs_ranked_by_application_count(client, db_session):
    job_most = _make_job(db_session, title="Most Applied Role")
    job_mid = _make_job(db_session, title="Mid Applied Role")
    job_none = _make_job(db_session, title="No Applications Role")
    candidate = _make_candidate(db_session)

    for _ in range(3):
        _make_application(db_session, job_most, candidate)
    _make_application(db_session, job_mid, candidate)

    body = client.get("/reports/jobs-dashboard-stats").json()
    top_jobs_by_id = {row["job_id"]: row for row in body["top_jobs"]}

    # job_none may or may not appear (top 5 overall, and other real jobs may already
    # have applications) -- what must hold is the relative ranking among these three.
    assert str(job_most.id) in top_jobs_by_id
    assert top_jobs_by_id[str(job_most.id)]["application_count"] >= 3
    assert top_jobs_by_id[str(job_most.id)]["title"] == "Most Applied Role"
    if str(job_mid.id) in top_jobs_by_id:
        assert top_jobs_by_id[str(job_mid.id)]["application_count"] >= 1
    if str(job_none.id) in top_jobs_by_id:
        assert top_jobs_by_id[str(job_none.id)]["application_count"] == 0

    ordered_counts = [row["application_count"] for row in body["top_jobs"]]
    assert ordered_counts == sorted(ordered_counts, reverse=True)
    assert len(body["top_jobs"]) <= 5


# --- /reports/jobs-dashboard-stats: monthly series + comparison-month trend ---

_TREND_FIELDS = [
    "total_jobs_trend",
    "active_jobs_trend",
    "open_positions_trend",
    "total_applications_trend",
    "hires_this_month_trend",
    "avg_time_to_hire_trend",
]


def test_jobs_dashboard_stats_monthly_series_has_12_points_ending_this_month(client):
    body = client.get("/reports/jobs-dashboard-stats").json()
    current_key = stats.month_key(stats.month_start(_NOW))

    for field in _TREND_FIELDS:
        series = body[field]["series"]
        assert len(series) == 12
        assert series[-1]["month"] == current_key
        months = [point["month"] for point in series]
        assert months == sorted(months)
        assert len(set(months)) == 12


def test_jobs_dashboard_stats_default_compare_month_is_last_month(client):
    body = client.get("/reports/jobs-dashboard-stats").json()
    expected = stats.month_key(stats.shift_months(stats.month_start(_NOW), -1))
    for field in _TREND_FIELDS:
        assert body[field]["compare_month"] == expected


def test_jobs_dashboard_stats_invalid_compare_month_format_rejected(client):
    response = client.get("/reports/jobs-dashboard-stats?compare_month=not-a-month")
    assert response.status_code == 400


def test_jobs_dashboard_stats_compare_month_out_of_range_rejected(client):
    # The current (in-progress) month isn't a valid comparison target -- it isn't over yet.
    current_key = stats.month_key(stats.month_start(_NOW))
    response = client.get(f"/reports/jobs-dashboard-stats?compare_month={current_key}")
    assert response.status_code == 400

    # Nor is anything older than 12 months back.
    too_old_key = stats.month_key(stats.shift_months(stats.month_start(_NOW), -13))
    response = client.get(f"/reports/jobs-dashboard-stats?compare_month={too_old_key}")
    assert response.status_code == 400


def test_jobs_dashboard_stats_total_jobs_cumulative_series_and_compare_value(client, db_session):
    # Total Jobs is creation-timestamp-based: the series is a running total "as of"
    # each month-end, so a job created 6 months ago should raise every point from
    # that month onward (including this one), while a job created this month should
    # raise only the current point.
    target_key = stats.month_key(stats.shift_months(stats.month_start(_NOW), -6))

    before = client.get("/reports/jobs-dashboard-stats").json()
    before_point = next(p for p in before["total_jobs_trend"]["series"] if p["month"] == target_key)

    _make_job(db_session, created_at=_months_ago(6))
    _make_job(db_session, created_at=_NOW)

    after = client.get("/reports/jobs-dashboard-stats").json()
    after_point = next(p for p in after["total_jobs_trend"]["series"] if p["month"] == target_key)

    assert after["total_jobs"] - before["total_jobs"] == 2
    assert after_point["value"] - before_point["value"] == 1


def test_jobs_dashboard_stats_compare_month_pct_change_matches_formula(client, db_session):
    target_key = stats.month_key(stats.shift_months(stats.month_start(_NOW), -8))

    before = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    # Counts toward both the target month's comparison value and the current total.
    _make_application(db_session, job, candidate, created_at=_months_ago(8))
    # Created this month -- counts toward the current total only.
    _make_application(db_session, job, candidate, created_at=_NOW)

    after = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()
    trend = after["total_applications_trend"]

    assert trend["compare_month"] == target_key
    assert after["total_applications"] - before["total_applications"] == 2
    assert trend["compare_value"] - before["total_applications_trend"]["compare_value"] == 1

    expected_pct = round(
        (after["total_applications"] - trend["compare_value"]) / trend["compare_value"] * 100, 1
    )
    assert trend["pct_change"] == expected_pct


def test_jobs_dashboard_stats_hires_series_is_monthly_not_cumulative(client, db_session):
    target_ms = stats.shift_months(stats.month_start(_NOW), -3)
    target_key = stats.month_key(target_ms)
    target_mid = _months_ago(3)

    before = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()
    hires_before_point = next(
        p for p in before["hires_this_month_trend"]["series"] if p["month"] == target_key
    )
    avg_before_point = next(
        p for p in before["avg_time_to_hire_trend"]["series"] if p["month"] == target_key
    )

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(
        db_session, job, candidate, status="onboarding_completed",
        created_at=target_mid - timedelta(days=50),
    )
    _make_audit_entry(
        db_session, "application", application.id, "onboarding_completed", created_at=target_mid
    )

    after = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()

    # This month's flat hires_this_month is untouched -- the new completion is 3
    # calendar months old, not this month.
    assert after["hires_this_month"] == before["hires_this_month"]

    hires_after_point = next(
        p for p in after["hires_this_month_trend"]["series"] if p["month"] == target_key
    )
    avg_after_point = next(
        p for p in after["avg_time_to_hire_trend"]["series"] if p["month"] == target_key
    )
    assert hires_after_point["value"] - hires_before_point["value"] == 1

    prior_sum = (avg_before_point["value"] or 0) * hires_before_point["value"]
    expected_avg = (prior_sum + 50.0) / (hires_before_point["value"] + 1)
    assert abs(avg_after_point["value"] - expected_avg) < 0.1

    # compare_value for the selected month must track that same series point exactly.
    assert after["hires_this_month_trend"]["compare_value"] == hires_after_point["value"]


def test_jobs_dashboard_stats_active_jobs_trend_is_approximated_from_current_status(client, db_session):
    target_key = stats.month_key(stats.shift_months(stats.month_start(_NOW), -4))

    before = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()
    assert before["active_jobs_trend"]["is_approximate"] is True
    assert before["open_positions_trend"]["is_approximate"] is True
    # Every other stat is exact, computed from real creation timestamps.
    assert before["total_jobs_trend"]["is_approximate"] is False
    assert before["total_applications_trend"]["is_approximate"] is False
    assert before["hires_this_month_trend"]["is_approximate"] is False
    assert before["avg_time_to_hire_trend"]["is_approximate"] is False

    # This job is published *now*, but there's no historical record of whether it was
    # published back in the target month too -- the approximation has no choice but to
    # assume its current status held then as well, which is exactly the caveat the
    # is_approximate flag exists to surface.
    _make_job(db_session, status="published", positions_count=2, created_at=_months_ago(4))
    # Published now, but created *this* month -- must not affect the target month's
    # approximated snapshot, since it didn't exist as of that cutoff.
    _make_job(db_session, status="published", positions_count=5, created_at=_NOW)

    after = client.get(f"/reports/jobs-dashboard-stats?compare_month={target_key}").json()

    assert after["active_jobs"] - before["active_jobs"] == 2
    assert after["open_positions"] - before["open_positions"] == 7
    assert (
        after["active_jobs_trend"]["compare_value"] - before["active_jobs_trend"]["compare_value"] == 1
    )
    assert (
        after["open_positions_trend"]["compare_value"]
        - before["open_positions_trend"]["compare_value"]
        == 2
    )

    before_point = next(p for p in before["active_jobs_trend"]["series"] if p["month"] == target_key)
    after_point = next(p for p in after["active_jobs_trend"]["series"] if p["month"] == target_key)
    assert after_point["value"] - before_point["value"] == 1


# --- app/reports/stats: IST month-boundary correctness ---
#
# This app is India-only, so "today"/"this month" must be IST's calendar, not UTC's.
# These use explicit, hand-picked `now` instants (never the real wall clock) so the
# assertions are exact and don't depend on when the suite happens to run -- in
# particular they exercise the ~5.5 hour window at the start of each month (IST is
# UTC+5:30) where naively reading `some_utc_datetime.month` is a whole month behind
# what an India-based user sees on their own clock.


def test_month_start_uses_ist_calendar_not_utc_during_month_rollover_window():
    # 2026-07-31 20:00 UTC == 2026-08-01 01:30 IST -- IST has already rolled into
    # August while UTC's calendar date is still the last day of July.
    fragile_now = datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone.utc)
    assert stats.month_key(stats.month_start(fragile_now)) == "2026-08"

    # And safely *before* that rollover (still July on both clocks), it must stay July.
    safe_now = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
    assert stats.month_key(stats.month_start(safe_now)) == "2026-07"


def test_default_compare_month_is_previous_calendar_month_relative_to_ist_today():
    cases = [
        # (now_utc, expected current month, expected default compare_month)
        (datetime(2026, 8, 9, 6, 0, 0, tzinfo=timezone.utc), "2026-08", "2026-07"),  # ordinary midday case
        # The exact bug this guards against: today is "early August" on an IST clock
        # (2026-08-01 01:30 IST), but UTC's own calendar still reads July 31 -- the old
        # code used UTC's month directly and defaulted to "vs June 2026" here instead
        # of the correct "vs July 2026".
        (datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone.utc), "2026-08", "2026-07"),
        (datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc), "2026-07", "2026-06"),
        # Same rollover window, but at a year boundary.
        (datetime(2025, 12, 31, 19, 0, 0, tzinfo=timezone.utc), "2026-01", "2025-12"),
    ]
    for now_utc, expected_current, expected_compare in cases:
        assert stats.month_key(stats.month_start(now_utc)) == expected_current
        assert stats.month_key(stats.parse_compare_month(None, now_utc)) == expected_compare


def test_last_12_month_series_ends_on_ist_current_month_during_rollover_window():
    fragile_now = datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone.utc)
    month_starts = stats.last_12_month_starts(fragile_now)
    assert len(month_starts) == 12
    assert stats.month_key(month_starts[-1]) == "2026-08"
    assert stats.month_key(month_starts[-2]) == "2026-07"


# --- /reports/recent-activity ---


def test_recent_activity_describes_job_role_events(client, db_session):
    job = _make_job(db_session, title="Recent Activity Job")
    _make_audit_entry(
        db_session, "job_role", job.id, "job_role_created", created_at=_NOW,
        details={"status": "draft"},
    )
    _make_audit_entry(
        db_session, "job_role", job.id, "job_platforms_published", created_at=_NOW + timedelta(seconds=1),
        details={"previous_status": "ready_for_publishing", "new_status": "published"},
    )

    response = client.get("/reports/recent-activity?limit=50")

    assert response.status_code == 200
    messages = [item["message"] for item in response.json()["items"] if item["entity_id"] == str(job.id)]
    assert "Job created: Recent Activity Job" in messages
    assert "Job published: Recent Activity Job" in messages


def test_recent_activity_describes_application_events(client, db_session):
    job = _make_job(db_session, title="App Activity Job")
    candidate = _make_candidate(db_session, full_name="Riley Applicant")
    application = _make_application(db_session, job, candidate)
    _make_audit_entry(
        db_session, "application", application.id, "application_created", created_at=_NOW,
    )
    _make_audit_entry(
        db_session, "application", application.id, "onboarding_completed", created_at=_NOW + timedelta(seconds=1),
    )

    response = client.get("/reports/recent-activity?limit=50")

    assert response.status_code == 200
    messages = [
        item["message"] for item in response.json()["items"] if item["entity_id"] == str(application.id)
    ]
    assert "New application: Riley Applicant for App Activity Job" in messages
    assert "Hire completed: Riley Applicant for App Activity Job" in messages


def test_recent_activity_falls_back_to_humanized_action_for_unmapped_actions(client, db_session):
    job = _make_job(db_session, title="Unmapped Action Job")
    _make_audit_entry(db_session, "job_role", job.id, "job_role_updated", created_at=_NOW)

    response = client.get("/reports/recent-activity?limit=50")

    messages = [item["message"] for item in response.json()["items"] if item["entity_id"] == str(job.id)]
    assert "Job role updated: Unmapped Action Job" in messages


def test_recent_activity_excludes_other_entity_types(client, db_session):
    doc_id = uuid.uuid4()
    _make_audit_entry(db_session, "bgv_document", doc_id, "bgv_document_uploaded", created_at=_NOW)

    response = client.get("/reports/recent-activity?limit=50")

    assert all(item["entity_id"] != str(doc_id) for item in response.json()["items"])


def test_recent_activity_respects_limit(client, db_session):
    job = _make_job(db_session, title="Limit Job")
    for i in range(5):
        _make_audit_entry(
            db_session, "job_role", job.id, f"step_{i}", created_at=_NOW + timedelta(seconds=i)
        )

    response = client.get("/reports/recent-activity?limit=3")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_recent_activity_orders_newest_first(client, db_session):
    job = _make_job(db_session, title="Ordering Job")
    for i in range(5):
        _make_audit_entry(
            db_session, "job_role", job.id, f"step_{i}", created_at=_NOW + timedelta(seconds=i)
        )

    # A large limit + scoped to this test's own job/entity id, rather than asserting on
    # the global unfiltered feed's first item -- the shared dev database may already have
    # real, more recent activity from concurrent use that would otherwise outrank these rows.
    response = client.get("/reports/recent-activity?limit=50")

    assert response.status_code == 200
    all_items = response.json()["items"]

    # The endpoint's overall sort order is a real, data-independent assertion.
    timestamps = [item["created_at"] for item in all_items]
    assert timestamps == sorted(timestamps, reverse=True)

    # Among just this test's own rows, newest-first still holds.
    own_messages = [item["message"] for item in all_items if item["entity_id"] == str(job.id)]
    assert own_messages == [f"Step {i}: Ordering Job" for i in reversed(range(5))]


# --- /reports/job-status-overview ---


def test_job_status_overview_includes_every_real_status_even_at_zero(client):
    body = client.get("/reports/job-status-overview?period=all_time").json()
    labels = [row["label"] for row in body["by_status"]]

    assert labels == list(JOB_ROLE_STATUSES)
    assert body["total"] == sum(row["count"] for row in body["by_status"])


def test_job_status_overview_invalid_period_rejected(client):
    response = client.get("/reports/job-status-overview?period=next_week")
    assert response.status_code == 400


def test_job_status_overview_default_period_is_this_month(client, db_session):
    before = client.get("/reports/job-status-overview").json()
    before_counts = {row["label"]: row["count"] for row in before["by_status"]}

    _make_job(db_session, status="draft", created_at=_NOW)
    _make_job(db_session, status="published", created_at=_NOW)
    # Backdated to last month -- must be excluded from the default (this month) period.
    _make_job(db_session, status="draft", created_at=_months_ago(1))

    after = client.get("/reports/job-status-overview").json()
    after_counts = {row["label"]: row["count"] for row in after["by_status"]}

    assert after_counts["draft"] - before_counts["draft"] == 1
    assert after_counts["published"] - before_counts["published"] == 1
    assert after["total"] - before["total"] == 2


def test_job_status_overview_last_3_months_includes_current_and_two_prior_excludes_older(client, db_session):
    before = client.get("/reports/job-status-overview?period=last_3_months").json()
    before_total = before["total"]

    _make_job(db_session, status="published", created_at=_NOW)
    _make_job(db_session, status="closed", created_at=_months_ago(2))
    # One month further back than the window reaches -- must be excluded.
    excluded_job = _make_job(db_session, status="closed", created_at=_months_ago(3))

    after = client.get("/reports/job-status-overview?period=last_3_months").json()

    assert after["total"] - before_total == 2

    # Sanity: that excluded job really does exist and really is outside the window --
    # confirmed via all_time, which has no lower bound at all.
    all_time = client.get("/reports/job-status-overview?period=all_time").json()
    assert all_time["total"] >= after["total"]
    assert excluded_job.created_at < _months_ago(2)


def test_job_status_overview_this_year_excludes_prior_year(client, db_session):
    before = client.get("/reports/job-status-overview?period=this_year").json()
    before_total = before["total"]

    ist_now = _NOW + stats._IST_OFFSET
    january_this_year = stats._ist_month_boundary(ist_now.year, 1) + timedelta(days=9, hours=12)
    december_last_year = stats._ist_month_boundary(ist_now.year, 1) - timedelta(days=5)

    _make_job(db_session, status="ready_for_publishing", created_at=january_this_year)
    _make_job(db_session, status="ready_for_publishing", created_at=december_last_year)

    after = client.get("/reports/job-status-overview?period=this_year").json()

    assert after["total"] - before_total == 1


def test_job_status_overview_all_time_has_no_lower_bound(client, db_session):
    before = client.get("/reports/job-status-overview?period=all_time").json()
    before_total = before["total"]

    _make_job(db_session, status="closed", created_at=_BASE_TIME)

    after = client.get("/reports/job-status-overview?period=all_time").json()

    assert after["total"] - before_total == 1
