import io
import uuid

from docx import Document

from app.ai_services.resume_matcher import ResumeMatchError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.screening import suitability


def _unique_skill() -> str:
    # This test suite runs against a shared, never-truly-reset dev database (see
    # test_reports.py's own comments on this) -- a common token like "Python" could
    # collide with real or other tests' published jobs and silently win/lose the
    # pre-filter ranking by luck. A uuid-based token guarantees this test's own jobs are
    # the only ones anywhere in the table that could ever score a keyword-overlap match
    # against it.
    return f"zzSuitabilityTestSkill{uuid.uuid4().hex[:10]}"


def _make_job(db_session, skills=None, status="published", jd_text="Job description text.", **kwargs) -> JobRole:
    job = JobRole(title=kwargs.pop("title", "Backend Engineer"), skills=skills, status=status, jd_text=jd_text, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_candidate(db_session, parsed_fields=None, **kwargs) -> Candidate:
    candidate = Candidate(full_name="Jane Doe", parsed_fields=parsed_fields, **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _fake_result(**overrides) -> dict:
    result = {
        "match_score": 80,
        "skill_match_pct": 80,
        "experience_score": 80,
        "location_score": 80,
        "certificates_score": 80,
        "missing_skills": [],
        "recommendation": "strong_fit",
    }
    result.update(overrides)
    return result


# --- _keyword_overlap_score: pure function, no AI/DB access ---


def test_keyword_overlap_score_is_fraction_of_job_skills_covered():
    # Candidate covers 2 of the job's 4 required skills -> 0.5, regardless of any extra
    # candidate skills the job doesn't ask for.
    score = suitability._keyword_overlap_score(
        ["Python", "SQL", "Docker"], ["Python", "SQL", "Kubernetes", "AWS"]
    )
    assert score == 0.5


def test_keyword_overlap_score_is_case_insensitive():
    score = suitability._keyword_overlap_score(["python"], ["PYTHON", "Go"])
    assert score == 0.5


def test_keyword_overlap_score_zero_when_job_has_no_skills_listed():
    assert suitability._keyword_overlap_score(["Python"], []) == 0.0


# --- pre_filter_published_jobs: cheap local ranking, never calls the AI ---


def test_pre_filter_published_jobs_excludes_non_published_statuses(db_session):
    skill = _unique_skill()
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})
    published = _make_job(db_session, skills=[skill], status="published", title="Published Role")
    draft = _make_job(db_session, skills=[skill], status="draft", title="Draft Role")
    closed = _make_job(db_session, skills=[skill], status="closed", title="Closed Role")
    on_hold = _make_job(db_session, skills=[skill], status="on_hold", title="On Hold Role")
    ready = _make_job(db_session, skills=[skill], status="ready_for_publishing", title="Ready Role")

    result_ids = [job.id for job in suitability.pre_filter_published_jobs(db_session, candidate, top_n=1000)]

    assert published.id in result_ids
    for excluded in (draft, closed, on_hold, ready):
        assert excluded.id not in result_ids


def test_pre_filter_published_jobs_ranks_by_skill_overlap_descending(db_session):
    skill_a, skill_b = _unique_skill(), _unique_skill()
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill_a, skill_b, "Docker"]})
    no_overlap = _make_job(db_session, skills=["Java", "Scala"], title="No Overlap")
    full_overlap = _make_job(db_session, skills=[skill_a, skill_b, "Docker"], title="Full Overlap")
    partial_overlap = _make_job(db_session, skills=[skill_a, "Java"], title="Partial Overlap")

    # A generously large top_n so all three test jobs are guaranteed to survive the slice
    # regardless of how many other published jobs already exist in the shared DB -- only
    # their *relative* order (via .index, not full-list equality) is under test here.
    result_ids = [job.id for job in suitability.pre_filter_published_jobs(db_session, candidate, top_n=100000)]

    assert result_ids.index(full_overlap.id) < result_ids.index(partial_overlap.id) < result_ids.index(no_overlap.id)


def test_pre_filter_published_jobs_caps_at_top_n_even_with_many_published_jobs(db_session):
    skill = _unique_skill()
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})
    for i in range(10):
        _make_job(db_session, skills=[skill], title=f"Job {i}")

    result = suitability.pre_filter_published_jobs(db_session, candidate, top_n=3)

    assert len(result) == 3


# --- attempt_auto_suggest_suitable_job: the automatic, best-effort, AI-cost-bounded trigger ---


def test_attempt_auto_suggest_noop_when_candidate_has_no_parsed_fields(db_session, monkeypatch):
    called = []
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: called.append(1) or _fake_result())
    candidate = _make_candidate(db_session, parsed_fields=None)

    outcome = suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert outcome is None
    assert called == []


def test_attempt_auto_suggest_noop_when_pre_filter_finds_no_candidate_jobs(db_session, monkeypatch):
    # Isolates the "nothing survived the pre-filter" branch from real DB content --
    # deterministic regardless of how many (or few) published jobs actually exist.
    called = []
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: called.append(1) or _fake_result())
    monkeypatch.setattr(suitability, "pre_filter_published_jobs", lambda *a, **k: [])
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})

    outcome = suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert outcome is None
    assert called == []


def test_attempt_auto_suggest_calls_ai_only_for_pre_filtered_jobs_not_every_published_job(db_session, monkeypatch):
    # The core cost-control guarantee: 6 published jobs match the candidate's skill, but
    # pre_filter_published_jobs caps consideration at PRE_FILTER_TOP_N (3) -- the AI call
    # must never fire more than that many times no matter how many jobs are published.
    skill = _unique_skill()
    calls = []

    def fake_match_resume(jd_text, *args, **kwargs):
        calls.append(jd_text)
        return _fake_result()

    monkeypatch.setattr(suitability, "match_resume", fake_match_resume)
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})
    for i in range(6):
        _make_job(db_session, skills=[skill], title=f"Job {i}", jd_text=f"JD {uuid.uuid4()}")

    suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert len(calls) == suitability.PRE_FILTER_TOP_N
    assert len(calls) < 6


def test_attempt_auto_suggest_picks_highest_scoring_job_among_considered(db_session, monkeypatch):
    skill = _unique_skill()
    strong_jd = f"Strong JD {uuid.uuid4()}"
    weak_job = _make_job(db_session, skills=[skill], title="Weak Fit", jd_text=f"Weak JD {uuid.uuid4()}")
    strong_job = _make_job(db_session, skills=[skill], title="Strong Fit", jd_text=strong_jd)

    def fake_match_resume(jd_text, *args, **kwargs):
        if jd_text == strong_jd:
            return _fake_result(match_score=95, skill_match_pct=95, experience_score=95, location_score=95, certificates_score=95)
        return _fake_result(match_score=20, skill_match_pct=20, experience_score=20, location_score=20, certificates_score=20)

    monkeypatch.setattr(suitability, "match_resume", fake_match_resume)
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})

    outcome = suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert outcome is not None
    assert outcome.suitable_job_id == strong_job.id
    assert float(outcome.suitable_job_score) == 95.0
    assert weak_job.id != outcome.suitable_job_id


def test_attempt_auto_suggest_never_touches_any_application(db_session, monkeypatch):
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: _fake_result())
    suggested_skill = _unique_skill()
    applied_job = _make_job(db_session, skills=["totally-unrelated-skill"], title="Applied-For Job")
    suggested_job = _make_job(db_session, skills=[suggested_skill], title="Suggested Job")
    candidate = _make_candidate(db_session, parsed_fields={"skills": [suggested_skill]})
    application = Application(job_role_id=applied_job.id, candidate_id=candidate.id, status="received")
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    db_session.refresh(application)
    db_session.refresh(candidate)
    # The suggestion landed on a different job than the one actually applied for, and the
    # application itself is completely untouched -- still 'received', still pointed at
    # applied_job, no score written onto it.
    assert candidate.suitable_job_id == suggested_job.id
    assert application.job_role_id == applied_job.id
    assert application.status == "received"
    assert application.match_score is None


def test_attempt_auto_suggest_swallows_per_job_ai_failure_and_still_considers_the_rest(db_session, monkeypatch):
    skill = _unique_skill()
    flaky_jd = f"Flaky JD {uuid.uuid4()}"
    _make_job(db_session, skills=[skill], title="Flaky Job", jd_text=flaky_jd)
    good_job = _make_job(db_session, skills=[skill], title="Good Job", jd_text=f"Good JD {uuid.uuid4()}")

    def fake_match_resume(jd_text, *args, **kwargs):
        if jd_text == flaky_jd:
            raise ResumeMatchError("boom")
        return _fake_result()

    monkeypatch.setattr(suitability, "match_resume", fake_match_resume)
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})

    outcome = suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert outcome is not None
    assert outcome.suitable_job_id == good_job.id


def test_attempt_auto_suggest_noop_when_every_considered_job_ai_call_fails(db_session, monkeypatch):
    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr(suitability, "match_resume", fake_match_resume)
    skill = _unique_skill()
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})
    _make_job(db_session, skills=[skill])

    outcome = suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    assert outcome is None
    db_session.refresh(candidate)
    assert candidate.suitable_job_id is None
    assert candidate.suitable_job_score is None


def test_attempt_auto_suggest_writes_audit_log_entry(db_session, monkeypatch):
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: _fake_result())
    skill = _unique_skill()
    job = _make_job(db_session, skills=[skill], title="Matched Job")
    candidate = _make_candidate(db_session, parsed_fields={"skills": [skill]})

    suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == candidate.id, AuditLog.action == "ai_suitability_scored")
        .one()
    )
    assert audit_entry.details["suitable_job_id"] == str(job.id)
    assert audit_entry.details["suitable_job_title"] == "Matched Job"
    assert len(audit_entry.details["jobs_considered"]) <= suitability.PRE_FILTER_TOP_N


# --- integration: the real hook point (parse-resume completing) fires automatically ---


def test_parse_resume_triggers_suitability_suggestion_and_never_touches_the_application(client, db_session, monkeypatch):
    suggested_skill = _unique_skill()
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: _fake_result())
    monkeypatch.setattr(
        "app.candidates.router.parse_resume",
        lambda raw_text: {"full_name": "Jane Doe", "email": "jane@example.com", "skills": [suggested_skill]},
    )
    applied_job = _make_job(db_session, skills=["totally-unrelated-skill"], title="Applied-For Job")
    suggested_job = _make_job(db_session, skills=[suggested_skill], title="Suggested Job")

    document = Document()
    document.add_paragraph("Jane Doe\njane@example.com")
    buffer = io.BytesIO()
    document.save(buffer)

    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    application_response = client.post(
        "/applications", json={"job_role_id": str(applied_job.id), "candidate_id": candidate_id}
    )
    application_id = application_response.json()["id"]

    parse_response = client.post(f"/candidates/{candidate_id}/parse-resume")
    assert parse_response.status_code == 200

    refreshed_candidate = db_session.get(Candidate, uuid.UUID(candidate_id))
    assert refreshed_candidate.suitable_job_id == suggested_job.id

    # The applied-for application is unaffected by the suggestion landing on a different job.
    refreshed_application = db_session.get(Application, uuid.UUID(application_id))
    assert refreshed_application.job_role_id == applied_job.id


def test_candidates_list_and_dashboard_expose_suitable_job_fields(client, db_session, monkeypatch):
    monkeypatch.setattr(suitability, "match_resume", lambda *a, **k: _fake_result())
    suggested_skill = _unique_skill()
    job = _make_job(db_session, skills=[suggested_skill], title="Suggested Job", jd_text="Needs the skill.")
    other_job = _make_job(db_session, skills=["totally-unrelated-skill"], title="Applied Job")
    unique_email = f"suitable-fields-{uuid.uuid4().hex[:8]}@example.com"
    candidate = _make_candidate(db_session, parsed_fields={"skills": [suggested_skill]}, email=unique_email)
    application = Application(job_role_id=other_job.id, candidate_id=candidate.id, status="received")
    db_session.add(application)
    db_session.commit()

    suitability.attempt_auto_suggest_suitable_job(db_session, candidate)

    list_response = client.get(
        "/candidates/applications", params={"search": unique_email, "page_size": 50}
    )
    assert list_response.status_code == 200
    row = list_response.json()["items"][0]
    assert row["suitable_job_id"] == str(job.id)
    assert row["suitable_job_title"] == "Suggested Job"
    assert row["suitable_job_score"] == 80.0
    # Never the applied-for job's id/title -- that stays job_role_id/job_title above.
    assert row["job_role_id"] == str(other_job.id)

    dashboard_response = client.get("/reports/candidates-dashboard-stats")
    assert dashboard_response.status_code == 200
    recent = dashboard_response.json()["recent_candidates"]
    matching = [r for r in recent if r["candidate_id"] == str(candidate.id)]
    # recent_candidates is capped to the latest 8 applications system-wide -- in a busy
    # shared dev DB this candidate's single application may have scrolled off that window,
    # which is fine; only assert the shape when it's actually present.
    if matching:
        assert matching[0]["suitable_job_title"] == "Suggested Job"
