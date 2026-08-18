import io
import uuid

from docx import Document
from PIL import Image

from app.ai_services.resume_parser import ResumeParsingError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole


def _make_job(db_session, title="CSV Test Job", **kwargs) -> JobRole:
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


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_image_bytes(color=(200, 50, 50)) -> bytes:
    image = Image.new("RGB", (4, 4), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_docx_bytes_with_photo(text: str, photo_bytes: bytes) -> bytes:
    document = Document()
    document.add_paragraph(text)
    document.add_picture(io.BytesIO(photo_bytes))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_upload_resume_creates_candidate(client):
    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["resume_path"]
    assert body["parsed_fields"] is None


def test_upload_resume_rejects_unsupported_type(client):
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.txt", b"plain text resume", "text/plain")},
    )

    assert response.status_code == 400


def test_get_candidate_not_found(client):
    response = client.get(f"/candidates/{uuid.uuid4()}")
    assert response.status_code == 404


def test_download_resume(client):
    resume_bytes = _make_docx_bytes("Jane Doe")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.get(f"/candidates/{candidate_id}/resume")

    assert response.status_code == 200
    assert response.content == resume_bytes


def test_parse_resume_updates_parsed_fields(client, db_session, monkeypatch):
    fake_parsed = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "total_experience_years": 4.5,
        "skills": ["Python", "SQL"],
        "education": [{"degree": "B.Tech", "institution": "IIT", "year": 2019}],
        "work_history": [{"company": "Acme", "title": "Engineer", "start": "2020", "end": "2024"}],
    }
    monkeypatch.setattr("app.candidates.router.parse_resume", lambda raw_text: fake_parsed)

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    body = response.json()
    assert body["parsed_fields"] == fake_parsed

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_id == uuid.UUID(candidate_id),
            AuditLog.action == "ai_resume_parser_scored",
        )
        .one_or_none()
    )
    assert audit_entry is not None
    assert audit_entry.details == fake_parsed


# --- embedded candidate photo extraction (best-effort, part of parse-resume) ---


def test_parse_resume_extracts_embedded_photo_from_docx(client, monkeypatch):
    fake_parsed = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "total_experience_years": 4.5,
        "skills": ["Python"],
        "education": [],
        "work_history": [],
    }
    monkeypatch.setattr("app.candidates.router.parse_resume", lambda raw_text: fake_parsed)

    photo_bytes = _make_image_bytes()
    resume_bytes = _make_docx_bytes_with_photo("Jane Doe\njane@example.com", photo_bytes)
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    assert response.json()["photo_path"]

    photo_response = client.get(f"/candidates/{candidate_id}/photo")
    assert photo_response.status_code == 200
    assert photo_response.content == photo_bytes


def test_parse_resume_without_embedded_photo_leaves_photo_path_null(client, monkeypatch):
    monkeypatch.setattr("app.candidates.router.parse_resume", lambda raw_text: {"full_name": "Jane Doe"})

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    assert response.json()["photo_path"] is None
    assert client.get(f"/candidates/{candidate_id}/photo").status_code == 404


def test_parse_resume_photo_extraction_failure_does_not_break_parsing(client, monkeypatch):
    # Photo extraction blowing up for any reason must never take the actual resume parse
    # down with it -- the endpoint should still succeed with the real parsed fields, just
    # without a photo.
    fake_parsed = {"full_name": "Jane Doe", "email": "jane@example.com"}
    monkeypatch.setattr("app.candidates.router.parse_resume", lambda raw_text: fake_parsed)
    monkeypatch.setattr(
        "app.candidates.router.extract_photo",
        lambda file_bytes, filename: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    body = response.json()
    assert body["parsed_fields"] == fake_parsed
    assert body["photo_path"] is None


def test_download_photo_not_found_returns_404(client, db_session):
    candidate = _make_candidate(db_session, full_name="No Photo")

    response = client.get(f"/candidates/{candidate.id}/photo")

    assert response.status_code == 404


def test_parse_resume_ai_failure_returns_502(client, monkeypatch):
    def fake_parse_resume(raw_text):
        raise ResumeParsingError("Failed to parse resume: AI service timed out")

    monkeypatch.setattr("app.candidates.router.parse_resume", fake_parse_resume)

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 502


def test_parse_resume_without_upload_returns_400(client, db_session):
    from app.models.candidate import Candidate

    candidate = Candidate(full_name="No Resume")
    db_session.add(candidate)
    db_session.commit()

    response = client.post(f"/candidates/{candidate.id}/parse-resume")

    assert response.status_code == 400


# --- source tracking ---


def test_upload_resume_sets_manual_source(client):
    resume_bytes = _make_docx_bytes("Jane Doe")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    assert response.json()["source"] == "manual"


def test_candidate_read_includes_location_defaulting_to_null(client, db_session):
    candidate = _make_candidate(db_session, full_name="No Location")

    response = client.get(f"/candidates/{candidate.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["location"] is None
    assert body["source"] == "manual"


# --- inferred_gender (fallback-avatar hint, computed from full_name on every read) ---


def test_get_candidate_inferred_gender_for_confident_names(client, db_session):
    male_candidate = _make_candidate(db_session, full_name="John Smith")
    female_candidate = _make_candidate(db_session, full_name="Priya Sharma")

    male_body = client.get(f"/candidates/{male_candidate.id}").json()
    female_body = client.get(f"/candidates/{female_candidate.id}").json()

    assert male_body["inferred_gender"] == "male"
    assert female_body["inferred_gender"] == "female"


def test_get_candidate_inferred_gender_null_for_unknown_name(client, db_session):
    candidate = _make_candidate(db_session, full_name="Xyzabcqqq Nobody")

    response = client.get(f"/candidates/{candidate.id}")

    assert response.status_code == 200
    assert response.json()["inferred_gender"] is None


def test_get_candidate_inferred_gender_null_when_no_name_yet(client):
    # Freshly uploaded, not yet parsed -- full_name is null, so there's nothing to infer
    # from; must not error, just report null same as any other unset field.
    resume_bytes = _make_docx_bytes("no name yet")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    assert response.json()["inferred_gender"] is None


def test_parse_resume_response_includes_inferred_gender(client, monkeypatch):
    monkeypatch.setattr(
        "app.candidates.router.parse_resume", lambda raw_text: {"full_name": "Priya Sharma", "email": "priya@example.com"}
    )

    resume_bytes = _make_docx_bytes("Priya Sharma")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    response = client.post(f"/candidates/{candidate_id}/parse-resume")

    assert response.status_code == 200
    assert response.json()["inferred_gender"] == "female"


def test_list_candidate_applications_includes_inferred_gender(client, db_session):
    job = _make_job(db_session, title="Inferred Gender Job")
    candidate = _make_candidate(db_session, full_name="John Smith", email="john.gender@example.com")
    _make_application(db_session, job, candidate)

    response = client.get("/candidates/applications", params={"search": "john.gender@example.com", "page_size": 50})

    assert response.status_code == 200
    assert response.json()["items"][0]["inferred_gender"] == "male"


# --- GET /candidates/applications (Candidates List page data source) ---


def test_list_candidate_applications_one_row_per_application(client, db_session):
    job_a = _make_job(db_session, title="Job A")
    job_b = _make_job(db_session, title="Job B")
    candidate = _make_candidate(db_session, full_name="Multi Applicant", email="multi@example.com")
    app_a = _make_application(db_session, job_a, candidate, status="received")
    app_b = _make_application(db_session, job_b, candidate, status="screened", match_score=77)

    response = client.get("/candidates/applications", params={"search": "multi@example.com", "page_size": 50})

    assert response.status_code == 200
    body = response.json()
    ids = {row["application_id"] for row in body["items"]}
    assert str(app_a.id) in ids
    assert str(app_b.id) in ids
    by_id = {row["application_id"]: row for row in body["items"]}
    assert by_id[str(app_b.id)]["match_score"] == 77.0
    assert by_id[str(app_b.id)]["job_title"] == "Job B"


def test_list_candidate_applications_filters_by_status_source_and_job(client, db_session):
    job = _make_job(db_session, title="Filter Job")
    portal_candidate = _make_candidate(db_session, full_name="Portal Cand", source="career_portal")
    manual_candidate = _make_candidate(db_session, full_name="Manual Cand", source="manual")
    portal_app = _make_application(db_session, job, portal_candidate, status="screened")
    _make_application(db_session, job, manual_candidate, status="received")

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "status": "screened", "source": "career_portal", "page_size": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["application_id"] == str(portal_app.id)


def test_list_candidate_applications_pagination(client, db_session):
    job = _make_job(db_session, title="Pagination Job")
    candidate = _make_candidate(db_session, full_name="Pagination Cand")
    for _ in range(5):
        _make_application(db_session, job, candidate)

    first_page = client.get(
        "/candidates/applications", params={"job_role_id": str(job.id), "page": 1, "page_size": 2}
    ).json()
    second_page = client.get(
        "/candidates/applications", params={"job_role_id": str(job.id), "page": 2, "page_size": 2}
    ).json()

    assert first_page["total"] == 5
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert {row["application_id"] for row in first_page["items"]}.isdisjoint(
        {row["application_id"] for row in second_page["items"]}
    )


# --- GET /candidates/applications/export -- unpaginated, for the List page's Export button ---


def test_list_candidate_applications_page_size_over_200_is_rejected(client, db_session):
    # Confirms the paginated endpoint's cap is unchanged -- export must go through the
    # dedicated endpoint below, not a raised page_size limit on this one.
    job = _make_job(db_session, title="Cap Unchanged Job")
    response = client.get("/candidates/applications", params={"job_role_id": str(job.id), "page_size": 1000})
    assert response.status_code == 422


def test_export_large_result_set_bypasses_the_200_page_size_cap(client, db_session):
    # This is the actual bug report: exporting more than 200 matching rows used to 422
    # because the List page's Export button called the paginated endpoint above with
    # page_size=1000. The dedicated export endpoint has no page_size at all.
    job = _make_job(db_session, title="Export Bulk Job")
    candidates = [Candidate(full_name=f"Bulk Candidate {i}") for i in range(250)]
    db_session.add_all(candidates)
    db_session.commit()
    applications = [Application(job_role_id=job.id, candidate_id=c.id, status="received") for c in candidates]
    db_session.add_all(applications)
    db_session.commit()

    response = client.get("/candidates/applications/export", params={"job_role_id": str(job.id)})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 250


def test_export_respects_filters_when_no_application_ids_given(client, db_session):
    job = _make_job(db_session, title="Export Filter Job")
    matching = _make_candidate(db_session, full_name="Matches Filter", source="career_portal")
    non_matching = _make_candidate(db_session, full_name="Does Not Match", source="manual")
    matching_app = _make_application(db_session, job, matching)
    _make_application(db_session, job, non_matching)

    response = client.get(
        "/candidates/applications/export", params={"job_role_id": str(job.id), "source": "career_portal"}
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["application_id"] == str(matching_app.id)


def test_export_by_application_ids_ignores_filters_and_returns_only_those_rows(client, db_session):
    # Row-selection export (checkboxes checked on the List page): application_ids must
    # take priority over every other filter, not be ANDed with them -- a selected row
    # should always export even if it no longer matches whatever filter happens to be
    # active on the page.
    job = _make_job(db_session, title="Selective Export Job")
    selected_candidate = _make_candidate(db_session, full_name="Selected Cand")
    other_candidate = _make_candidate(db_session, full_name="Unselected Cand")
    selected_app = _make_application(db_session, job, selected_candidate, status="received")
    _make_application(db_session, job, other_candidate, status="screened")

    response = client.get(
        "/candidates/applications/export",
        params={"application_ids": [str(selected_app.id)], "status": "screened"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["application_id"] == str(selected_app.id)


def test_export_by_application_ids_not_found_returns_empty_list(client):
    response = client.get("/candidates/applications/export", params={"application_ids": [str(uuid.uuid4())]})
    assert response.status_code == 200
    assert response.json() == []


# --- GET /candidates/applications -- new range/date filters ---


def test_list_candidate_applications_filters_by_experience_range(client, db_session):
    job = _make_job(db_session, title="Experience Filter Job")
    junior = _make_candidate(db_session, full_name="Junior Cand", parsed_fields={"total_experience_years": 1})
    senior = _make_candidate(db_session, full_name="Senior Cand", parsed_fields={"total_experience_years": 8})
    junior_app = _make_application(db_session, job, junior)
    senior_app = _make_application(db_session, job, senior)

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "experience_min": 5, "page_size": 50},
    )

    ids = {row["application_id"] for row in response.json()["items"]}
    assert str(senior_app.id) in ids
    assert str(junior_app.id) not in ids


def test_list_candidate_applications_filters_by_match_score_range(client, db_session):
    job = _make_job(db_session, title="Match Score Filter Job")
    candidate = _make_candidate(db_session)
    low = _make_application(db_session, job, candidate, status="screened", match_score=30)
    high = _make_application(db_session, job, candidate, status="screened", match_score=90)

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "match_score_min": 60, "match_score_max": 100, "page_size": 50},
    )

    ids = {row["application_id"] for row in response.json()["items"]}
    assert str(high.id) in ids
    assert str(low.id) not in ids


def test_list_candidate_applications_default_score_field_ignores_composite_score(client, db_session):
    # The Candidates List's "Match Score" filter must keep targeting the raw Resume Matcher
    # score when score_field is omitted -- unaffected by the Screening List's separate
    # "Screening Score" filter (see the test below). Deliberately divergent scores: a low
    # match_score with a high composite_score, and vice versa, so a test that accidentally
    # filtered by the wrong column would show up as a wrong-app-included/excluded failure.
    job = _make_job(db_session, title="Score Field Default Job")
    candidate = _make_candidate(db_session)
    high_match_low_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=90, composite_score=20
    )
    low_match_high_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=20, composite_score=90
    )

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "match_score_min": 60, "match_score_max": 100, "page_size": 50},
    )

    ids = {row["application_id"] for row in response.json()["items"]}
    assert str(high_match_low_composite.id) in ids
    assert str(low_match_high_composite.id) not in ids


def test_list_candidate_applications_score_field_composite_score_filters_by_composite_not_match(client, db_session):
    # The Screening List's "Screening Score" filter (score_field=composite_score) -- the
    # exact inverse selection of the default test above, against the same two applications.
    job = _make_job(db_session, title="Score Field Composite Job")
    candidate = _make_candidate(db_session)
    high_match_low_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=90, composite_score=20
    )
    low_match_high_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=20, composite_score=90
    )

    response = client.get(
        "/candidates/applications",
        params={
            "job_role_id": str(job.id),
            "match_score_min": 60,
            "match_score_max": 100,
            "score_field": "composite_score",
            "page_size": 50,
        },
    )

    ids = {row["application_id"] for row in response.json()["items"]}
    assert str(low_match_high_composite.id) in ids
    assert str(high_match_low_composite.id) not in ids


def test_export_applications_score_field_composite_score_filters_by_composite_not_match(client, db_session):
    # The export endpoint (Screening List's CSV export) must honor score_field exactly the
    # same way the paginated list endpoint does -- one filter-building implementation
    # shared by both (see _filtered_candidate_applications_query).
    job = _make_job(db_session, title="Export Score Field Job")
    candidate = _make_candidate(db_session)
    high_match_low_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=90, composite_score=20
    )
    low_match_high_composite = _make_application(
        db_session, job, candidate, status="screened", match_score=20, composite_score=90
    )

    response = client.get(
        "/candidates/applications/export",
        params={
            "job_role_id": str(job.id),
            "match_score_min": 60,
            "match_score_max": 100,
            "score_field": "composite_score",
        },
    )

    ids = {row["application_id"] for row in response.json()}
    assert str(low_match_high_composite.id) in ids
    assert str(high_match_low_composite.id) not in ids


def test_list_candidate_applications_score_field_rejects_invalid_value(client, db_session):
    job = _make_job(db_session)
    response = client.get(
        "/candidates/applications", params={"job_role_id": str(job.id), "score_field": "ranking_score"}
    )
    assert response.status_code == 422


def test_list_candidate_applications_filters_by_applied_date_range(client, db_session):
    from datetime import datetime, timezone

    job = _make_job(db_session, title="Applied Date Filter Job")
    candidate = _make_candidate(db_session)
    old_app = _make_application(db_session, job, candidate, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    recent_app = _make_application(db_session, job, candidate, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    response = client.get(
        "/candidates/applications",
        params={"job_role_id": str(job.id), "applied_after": "2025-01-01", "page_size": 50},
    )

    ids = {row["application_id"] for row in response.json()["items"]}
    assert str(recent_app.id) in ids
    assert str(old_app.id) not in ids


# --- PATCH /candidates/{id} -- edit basic contact info ---


def test_update_candidate_contact_info(client, db_session):
    candidate = _make_candidate(db_session, full_name="Old Name", email="old@example.com", phone="000")

    response = client.patch(
        f"/candidates/{candidate.id}",
        json={"full_name": "New Name", "email": "new@example.com", "phone": "111"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "New Name"
    assert body["email"] == "new@example.com"
    assert body["phone"] == "111"


def test_update_candidate_contact_info_partial_update(client, db_session):
    candidate = _make_candidate(db_session, full_name="Keep Name", email="keep@example.com", phone="222")

    response = client.patch(f"/candidates/{candidate.id}", json={"phone": "333"})

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Keep Name"
    assert body["email"] == "keep@example.com"
    assert body["phone"] == "333"


def test_update_candidate_not_found(client):
    response = client.patch(f"/candidates/{uuid.uuid4()}", json={"full_name": "Nobody"})
    assert response.status_code == 404


# --- POST /candidates/upload -- source override (Import from Local) ---
#
# The Import wizard's "Import from Local" step doesn't have its own bulk backend
# endpoint -- it loops over this same single-file upload endpoint once per selected
# file, exactly like the single-candidate "Upload Resume" flow, just tagged with a
# different source so those candidates are distinguishable/filterable afterward (see
# app/candidates/router.py upload_resume). That's what's tested here; the actual
# multi-file looping/progress/partial-failure behavior lives in the frontend wizard
# (see frontend/src/components/ImportCandidatesWizard.test.tsx).


def test_upload_resume_with_local_import_source(client):
    resume_bytes = _make_docx_bytes("Local Import Cand")
    response = client.post(
        "/candidates/upload",
        data={"source": "local_import"},
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    assert response.json()["source"] == "local_import"


def test_upload_resume_defaults_to_manual_source(client):
    resume_bytes = _make_docx_bytes("Default Source Cand")
    response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    assert response.json()["source"] == "manual"


def test_upload_resume_rejects_arbitrary_source(client):
    # Only "manual"/"local_import" are legitimate for this endpoint -- accepting anything
    # a caller sends (e.g. "career_portal") would let this endpoint spoof a source it
    # doesn't actually represent.
    resume_bytes = _make_docx_bytes("Spoofed Source Cand")
    response = client.post(
        "/candidates/upload",
        data={"source": "career_portal"},
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 400
