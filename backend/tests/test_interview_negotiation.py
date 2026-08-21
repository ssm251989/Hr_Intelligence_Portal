"""Interviewer-first scheduling negotiation (app/interview_scheduling/negotiation.py) --
auto-triggered the moment an application's status becomes Shortlisted ('hr_selected'),
replacing the candidate-facing part of the older propose_interview_slots flow for that one
trigger point (the manual "Propose Slots" button is untouched and still uses the older flow).

Every test here uses a per-test copy of the real interview_tracker_sample.xlsx (Sample/
Interview_Tracker/interview_tracker_sample.xlsx) as its Interviewer Pool/Mails source --
its one real row, "Automation Anywhere Architect" -> "Kishore" (with a real registered,
Google-connected "Kishore" user already in this shared dev database, and a real "Mails"
sheet entry for them) -- copied per-test into tmp_path so tests never write to the checked-in
fixture. Extra interviewer names, where a scenario needs more than one, are appended to that
same real pool row (comma-separated, preserving order) rather than replacing it.
"""

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import load_workbook

from app.core.crypto import encrypt
from app.integrations.google_calendar import format_ist_datetime
from app.interview_scheduling import confirmation as interview_confirmation
from app.interview_scheduling import negotiation as neg
from app.interview_scheduling.storage import get_interview_scheduling_settings
from app.interview_scheduling.tracker import INTERVIEWER_POOL_SHEET, MAILS_SHEET, append_interview_log_row
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.negotiation_token import NegotiationToken
from app.models.user import User
from app.models.user_integration import UserIntegration

REAL_TRACKER_PATH = Path(__file__).resolve().parents[2] / "Sample" / "Interview_Tracker" / "interview_tracker_sample.xlsx"
REAL_POOL_JOB_TITLE = "Automation Anywhere Architect"
REAL_POOL_INTERVIEWER = "Kishore"


def _real_tracker_copy(tmp_path) -> Path:
    dest = tmp_path / "interview_tracker_sample.xlsx"
    shutil.copy(REAL_TRACKER_PATH, dest)
    return dest


def _extend_pool_with(tracker_path: Path, extra_names: list[str]) -> None:
    """Appends `extra_names` (comma-separated, preserving order) onto the real pool row's
    existing "Eligible Interviewers" cell for REAL_POOL_JOB_TITLE -- so "Kishore" (the real
    data) always walks first, and test-only names walk after, in a real multi-interviewer
    pool rather than an invented one."""
    workbook = load_workbook(tracker_path)
    sheet = workbook[INTERVIEWER_POOL_SHEET]
    for row in sheet.iter_rows(min_row=2):
        if row[0].value and str(row[0].value).strip().lower() == REAL_POOL_JOB_TITLE.lower():
            existing = [n.strip() for n in str(row[1].value or "").split(",") if n.strip()]
            row[1].value = ", ".join(existing + extra_names)
            break
    workbook.save(tracker_path)


def _add_mail_entry(tracker_path: Path, name: str, email: str) -> None:
    workbook = load_workbook(tracker_path)
    workbook[MAILS_SHEET].append([name, email])
    workbook.save(tracker_path)


def _mark_busy_this_week(tracker_path: Path, interviewer_name: str, when: datetime) -> None:
    append_interview_log_row(
        tracker_path,
        {"Assigned Interviewer": interviewer_name, "Status": "Confirmed", "Candidate Preferred Time": format_ist_datetime(when)},
    )


def _configure_tracker(db_session, tracker_path: Path) -> None:
    settings_row = get_interview_scheduling_settings(db_session)
    settings_row.tracker_path = str(tracker_path)
    db_session.commit()


def _make_user(db_session, name, role="interviewer") -> User:
    user = User(email=f"{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name=name, role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _connect_google(db_session, user) -> UserIntegration:
    integration = UserIntegration(user_id=user.id, provider="google", refresh_token=encrypt("fake-refresh-token"))
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)
    return integration


def _real_pool_interviewer(db_session) -> User:
    """Reuses the real, already-registered "Kishore" account (see the module docstring)
    rather than minting a duplicate -- a second same-named user would make
    service._find_interviewer_user's own match ambiguous."""
    existing = db_session.query(User).filter(User.full_name.ilike(REAL_POOL_INTERVIEWER)).all()
    if len(existing) == 1:
        user = existing[0]
        has_google = (
            db_session.query(UserIntegration)
            .filter(UserIntegration.user_id == user.id, UserIntegration.provider == "google")
            .first()
        )
        if not has_google:
            _connect_google(db_session, user)
        return user
    user = _make_user(db_session, REAL_POOL_INTERVIEWER)
    _connect_google(db_session, user)
    return user


def _make_job(db_session, title=REAL_POOL_JOB_TITLE, status="draft") -> JobRole:
    # "draft" (the model's own default), not "published" -- keeps these test job postings
    # out of the career portal / active listings in this shared dev database.
    job = JobRole(title=title, status=status)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


_AUTO_EMAIL = object()


def _make_candidate(db_session, email=_AUTO_EMAIL, name="Jane Doe") -> Candidate:
    if email is _AUTO_EMAIL:
        email = f"{uuid.uuid4().hex[:10]}@example.com"
    candidate = Candidate(full_name=name, email=email)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="hr_selected") -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _capture_emails(monkeypatch) -> list:
    sent = []
    monkeypatch.setattr(
        neg, "send_email",
        lambda refresh_token, *, to, subject, body: sent.append({"to": to, "subject": subject, "body": body}) or "msg-id",
    )
    return sent


def _mock_calendar_event(monkeypatch) -> None:
    monkeypatch.setattr(
        interview_confirmation, "create_calendar_event",
        lambda *a, **k: {"event_id": "evt-1", "html_link": "https://calendar.example/evt-1"},
    )


def _interviewer_batch(db_session, application) -> list[NegotiationToken]:
    return (
        db_session.query(NegotiationToken)
        .filter(NegotiationToken.application_id == application.id, NegotiationToken.role == "interviewer")
        .all()
    )


def _candidate_batch(db_session, application) -> list[NegotiationToken]:
    return (
        db_session.query(NegotiationToken)
        .filter(NegotiationToken.application_id == application.id, NegotiationToken.role == "candidate")
        .all()
    )


# --- walk-the-pool-on-busy ---


def test_walks_past_a_busy_interviewer_to_the_next_in_the_pool(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    other_name = f"Interviewer {uuid.uuid4().hex[:8]}"
    other_email = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [other_name])
    _add_mail_entry(tracker_path, other_name, other_email)
    _configure_tracker(db_session, tracker_path)

    _real_pool_interviewer(db_session)  # Kishore -- real, but about to be marked busy
    other_user = _make_user(db_session, other_name)
    _connect_google(db_session, other_user)
    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    outcome = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert len(sent) == 1
    assert sent[0]["to"] == other_email  # Kishore skipped -- busy this week

    batch = _interviewer_batch(db_session, application)
    assert {row.interviewer_name for row in batch} == {other_name}

    busy_attempt = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_interviewer_attempt")
        .all()
    )
    outcomes_by_name = {entry.details["interviewer"]: entry.details["outcome"] for entry in busy_attempt}
    assert outcomes_by_name[REAL_POOL_INTERVIEWER] == "busy_this_week"
    assert outcomes_by_name[other_name] == "offer_sent"


# --- "None of these work" fallback to the next interviewer, same day ---


def test_not_available_click_falls_back_to_the_next_interviewer_same_day(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    name_a = f"Interviewer {uuid.uuid4().hex[:8]}"
    name_b = f"Interviewer {uuid.uuid4().hex[:8]}"
    email_a = f"{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [name_a, name_b])
    _add_mail_entry(tracker_path, name_a, email_a)
    _add_mail_entry(tracker_path, name_b, email_b)
    _configure_tracker(db_session, tracker_path)

    # Marked busy purely so this test's outcome doesn't depend on the real Kishore
    # account's actual, unpredictable real-world busy status across runs.
    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))
    _real_pool_interviewer(db_session)
    user_a = _make_user(db_session, name_a)
    _connect_google(db_session, user_a)
    user_b = _make_user(db_session, name_b)
    _connect_google(db_session, user_b)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    outcome = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"
    assert sent[-1]["to"] == email_a

    batch_a = [row for row in _interviewer_batch(db_session, application) if row.interviewer_name == name_a]
    not_available_token = next(r for r in batch_a if r.kind == "not_available").token

    click_outcome = neg.handle_negotiation_click(db_session, not_available_token)
    assert click_outcome.status == "declined"

    assert len(sent) == 2
    assert sent[1]["to"] == email_b

    for row in batch_a:
        db_session.refresh(row)
        assert row.invalidated_at is not None


# --- multi-select availability ---


def test_interviewer_can_mark_multiple_slots_available_before_done(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    outcome = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"

    batch = _interviewer_batch(db_session, application)
    slot_rows = sorted([r for r in batch if r.kind == "slot"], key=lambda r: r.slot_time)
    assert len(slot_rows) == 3
    done_token = next(r for r in batch if r.kind == "done").token

    # Mark the 1st and 3rd available, skip the 2nd.
    first_click = neg.handle_negotiation_click(db_session, slot_rows[0].token)
    assert first_click.status == "recorded"
    third_click = neg.handle_negotiation_click(db_session, slot_rows[2].token)
    assert third_click.status == "recorded"

    done_click = neg.handle_negotiation_click(db_session, done_token)
    assert done_click.status == "confirmed"
    assert len(sent) == 2  # interviewer offer + candidate offer

    # --- candidate narrowed to exactly the interviewer-confirmed slots ---
    candidate_batch = _candidate_batch(db_session, application)
    candidate_slot_times = {r.slot_time for r in candidate_batch if r.kind == "slot"}
    assert candidate_slot_times == {slot_rows[0].slot_time, slot_rows[2].slot_time}
    assert slot_rows[1].slot_time not in candidate_slot_times  # the un-marked slot never reaches the candidate


# --- day+1 retry, and its stop condition ---


def test_both_days_exhausted_flags_the_application_for_manual_scheduling(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)  # the real pool's only interviewer

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    outcome = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"

    day1_batch = _interviewer_batch(db_session, application)
    day1_round = day1_batch[0].round_day
    not_available_day1 = next(r for r in day1_batch if r.kind == "not_available").token

    neg.handle_negotiation_click(db_session, not_available_day1)

    # The pool has only one interviewer -- day 1 is now exhausted, so the one retry (day
    # after) must have auto-started against the SAME pool.
    all_batches = _interviewer_batch(db_session, application)
    round_days = {row.round_day for row in all_batches}
    assert round_days == {day1_round, day1_round + timedelta(days=1)}
    assert len(sent) == 2  # day1 offer + day2 offer

    day2_batch = [row for row in all_batches if row.round_day != day1_round]
    not_available_day2 = next(r for r in day2_batch if r.kind == "not_available").token

    neg.handle_negotiation_click(db_session, not_available_day2)

    # Both days now exhausted -- no third day, flagged for manual scheduling instead.
    assert len(sent) == 2  # no further offer went out
    manual_flag = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_manual_scheduling_required")
        .first()
    )
    assert manual_flag is not None

    workbook = load_workbook(tracker_path)
    log_rows = list(workbook["Interview Log"].iter_rows(min_row=2, values_only=True))
    header = [cell.value for cell in next(workbook["Interview Log"].iter_rows(min_row=1, max_row=1))]
    status_col = header.index("Status")
    assert any(row[status_col] == "Manual Scheduling Required" for row in log_rows)


# --- earliest mutual slot wins when both sides confirm more than one overlapping slot ---


def test_earliest_of_the_candidate_confirmed_slots_is_scheduled(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    _mock_calendar_event(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_batch = _interviewer_batch(db_session, application)
    slot_rows = sorted([r for r in interviewer_batch if r.kind == "slot"], key=lambda r: r.slot_time)
    done_token = next(r for r in interviewer_batch if r.kind == "done").token

    # Interviewer marks all 3 available.
    for row in slot_rows:
        neg.handle_negotiation_click(db_session, row.token)
    neg.handle_negotiation_click(db_session, done_token)

    candidate_batch = _candidate_batch(db_session, application)
    candidate_slot_rows = sorted([r for r in candidate_batch if r.kind == "slot"], key=lambda r: r.slot_time)
    candidate_done_token = next(r for r in candidate_batch if r.kind == "done").token
    assert len(candidate_slot_rows) == 3

    # Candidate marks the LATER two as available (skips the earliest) -- the earliest of
    # what the candidate actually confirmed must still be the one scheduled, not simply the
    # earliest of everything ever offered.
    neg.handle_negotiation_click(db_session, candidate_slot_rows[1].token)
    neg.handle_negotiation_click(db_session, candidate_slot_rows[2].token)
    outcome = neg.handle_negotiation_click(db_session, candidate_done_token)

    assert outcome.status == "confirmed"
    assert outcome.scheduled_at == candidate_slot_rows[1].slot_time
    assert outcome.scheduled_at != candidate_slot_rows[0].slot_time  # never-marked earliest slot must not win

    db_session.refresh(application)
    assert application.status == "interview_scheduled"
    interview = db_session.query(Interview).filter(Interview.application_id == application.id).first()
    assert interview is not None
    assert interview.scheduled_at == candidate_slot_rows[1].slot_time
    assert interview.scheduling_method == "auto"


# --- idempotency guard ---


def test_idempotency_guard_prevents_a_second_negotiation_for_the_same_application(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_google(db_session, recruiter)

    sent = _capture_emails(monkeypatch)
    first = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert first == "started"
    assert len(sent) == 1

    second = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert second is None
    assert len(sent) == 1  # no duplicate offer sent

    skipped = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_skipped")
        .first()
    )
    assert skipped is not None


def test_idempotency_guard_does_not_fire_for_an_application_already_shortlisted_before_this_shipped(db_session, tmp_path, monkeypatch):
    # Simulates a candidate that was already sitting in 'hr_selected' before this
    # automation existed -- created directly, never through either shortlisting endpoint.
    # Nothing calls attempt_auto_negotiate_interview_slots on its own except those two
    # endpoints, so this row is never retroactively picked up merely by existing.
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    _make_application(db_session, job, candidate)

    sent = _capture_emails(monkeypatch)
    assert sent == []


# --- router wiring: fires on the real Shortlisted transition through both endpoints ---


def _connect_google_for_email(db_session, email) -> None:
    user = db_session.query(User).filter(User.email == email).one()
    _connect_google(db_session, user)


def test_legacy_shortlist_decision_select_triggers_the_negotiation(client, db_session, tmp_path, monkeypatch, make_auth_headers):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    headers = make_auth_headers(role="recruiter", email=email)
    _connect_google_for_email(db_session, email)

    sent = _capture_emails(monkeypatch)
    response = client.post(f"/applications/{application.id}/shortlist-decision", json={"decision": "select"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"
    assert len(sent) == 1


def test_shortlist_status_transition_to_shortlisted_triggers_the_negotiation(client, db_session, tmp_path, monkeypatch, make_auth_headers):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    headers = make_auth_headers(role="recruiter", email=email)
    _connect_google_for_email(db_session, email)

    sent = _capture_emails(monkeypatch)
    response = client.post(f"/applications/{application.id}/shortlist-status", json={"target_status": "shortlisted"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"
    assert len(sent) == 1
