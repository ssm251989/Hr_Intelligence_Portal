"""Interviewer-first, double-blind pick-2-of-3 scheduling negotiation
(app/interview_scheduling/negotiation.py) -- auto-triggered the moment an application's
status becomes Shortlisted ('hr_selected'), replacing the candidate-facing part of the
older propose_interview_slots flow for that one trigger point (the manual "Propose Slots"
button is untouched and still uses the older flow).

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from icalendar import Calendar
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
from app.models.hr_integration import HrIntegration
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.negotiation_token import NegotiationToken
from app.models.user import User
from app.models.user_integration import UserIntegration

REAL_TRACKER_PATH = Path(__file__).resolve().parents[2] / "Sample" / "Interview_Tracker" / "interview_tracker_sample.xlsx"
REAL_POOL_JOB_TITLE = "Automation Anywhere Architect"
REAL_POOL_INTERVIEWER = "Kishore"


def _real_tracker_copy(tmp_path) -> Path:
    """Copies the real interview_tracker_sample.xlsx, then trims its Interviewer Pool row
    for REAL_POOL_JOB_TITLE down to just REAL_POOL_INTERVIEWER. The checked-in file's own
    pool row actually lists two more names (Suresh A, Jagadeesh) from real usage -- harmless
    to this suite's "one real interviewer" invariant (see module docstring) back when a pool
    interviewer had to resolve to a registered User to be reachable, since neither has one
    and both were silently skipped. Now that reachability is decided purely by the Mails
    sheet + interviewer_busy_this_week (see app/interview_scheduling/negotiation.py's own
    docstring), both resolve to a real Mails-sheet email and would otherwise silently
    intercept offers these tests expect to reach a busy-Kishore fallback or a test-added
    interviewer instead. Trimmed here, on the per-test copy only -- the checked-in file
    itself is never touched -- so every test's own _extend_pool_with call still appends
    cleanly on top of a single-name baseline."""
    dest = tmp_path / "interview_tracker_sample.xlsx"
    shutil.copy(REAL_TRACKER_PATH, dest)
    workbook = load_workbook(dest)
    sheet = workbook[INTERVIEWER_POOL_SHEET]
    for row in sheet.iter_rows(min_row=2):
        if row[0].value and str(row[0].value).strip().lower() == REAL_POOL_JOB_TITLE.lower():
            row[1].value = REAL_POOL_INTERVIEWER
            break
    workbook.save(dest)
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


def _connect_hr_smtp(db_session, smtp_username="hr@example.com") -> HrIntegration:
    # The shared, org-level HR mailbox every negotiation email now sends from -- distinct
    # from any interviewer's/recruiter's own UserIntegration (still used only for Calendar
    # availability/event creation, unchanged by this).
    row = db_session.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db_session.add(row)
    row.smtp_host = "smtp.example.com"
    row.smtp_port = 587
    row.use_tls = True
    row.smtp_username = smtp_username
    row.smtp_password = encrypt("hr-smtp-password")
    row.from_address = smtp_username
    db_session.commit()
    db_session.refresh(row)
    return row


def _disconnect_hr_smtp(db_session) -> None:
    # The hr_integrations row is a singleton (id=1) that -- like every other settings
    # singleton in this app -- an earlier test's own db.commit() can leave configured;
    # explicitly reset it rather than assuming isolation.
    row = db_session.get(HrIntegration, 1)
    if row is not None:
        row.smtp_host = None
        row.smtp_username = None
        row.smtp_password = None
        db_session.commit()


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
        neg, "send_hr_email",
        lambda hr_integration, *, to, subject, body, html_body=None, attachment=None: sent.append(
            {
                "identity": hr_integration.smtp_username, "to": to, "subject": subject, "body": body,
                "html_body": html_body, "attachment": attachment,
            }
        ),
    )
    return sent


def _forbid_calendar_event(monkeypatch) -> None:
    """The pick-2-of-3 mechanic's own confirmation step (negotiation._finalize) must never
    call the Google Calendar API at all -- see its docstring for why. Installed instead of
    a mock that fakes success, so any call at all fails the test loudly rather than being
    silently accepted."""
    def _fail(*args, **kwargs):
        raise AssertionError("create_calendar_event must not be called by the pick-2-of-3 negotiation mechanic")
    monkeypatch.setattr(interview_confirmation, "create_calendar_event", _fail)


def _interviewer_row(db_session, application, interviewer_name: Optional[str] = None) -> Optional[NegotiationToken]:
    """The most-recently-created interviewer-role row for this application -- there is
    normally exactly one live one at a time (see NegotiationToken's own docstring).
    `interviewer_name` narrows it when more than one name has ever been tried (e.g. a
    fallback-to-the-next-interviewer scenario needs each name's own row)."""
    query = db_session.query(NegotiationToken).filter(
        NegotiationToken.application_id == application.id, NegotiationToken.role == "interviewer"
    )
    if interviewer_name is not None:
        query = query.filter(NegotiationToken.interviewer_name == interviewer_name)
    return query.order_by(NegotiationToken.created_at.desc()).first()


def _candidate_row(db_session, application) -> Optional[NegotiationToken]:
    return (
        db_session.query(NegotiationToken)
        .filter(NegotiationToken.application_id == application.id, NegotiationToken.role == "candidate")
        .order_by(NegotiationToken.created_at.desc())
        .first()
    )


def _slot_isos(round_day) -> list[str]:
    return [t.isoformat() for t in neg._slot_times_for_day(round_day)]


# --- walk-the-pool-on-busy (unchanged pool-walk mechanic) ---


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
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert len(sent) == 1
    assert sent[0]["to"] == other_email  # Kishore skipped -- busy this week

    row = _interviewer_row(db_session, application)
    assert row.interviewer_name == other_name

    busy_attempt = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_interviewer_attempt")
        .all()
    )
    outcomes_by_name = {entry.details["interviewer"]: entry.details["outcome"] for entry in busy_attempt}
    assert outcomes_by_name[REAL_POOL_INTERVIEWER] == "busy_this_week"
    assert outcomes_by_name[other_name] == "offer_sent"


def test_interviewer_with_no_personal_google_connection_still_receives_an_offer(db_session, tmp_path, monkeypatch):
    """The real, currently-blocked scenario: an interviewer (like Suresh A) who is a
    registered User and not busy per the Excel tracker, but has never connected a personal
    Google account. hradmin65@gmail.com (the shared HR mailbox) is the single account of
    record for every interview-scheduling email this mechanic sends -- no interviewer
    should ever need their own Google connection to be reachable. Deliberately does NOT
    call _connect_google for this interviewer."""
    tracker_path = _real_tracker_copy(tmp_path)
    name = f"Interviewer {uuid.uuid4().hex[:8]}"
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [name])
    _add_mail_entry(tracker_path, name, email)
    _configure_tracker(db_session, tracker_path)

    # The real "Kishore" pool row (this fixture's own base data, already a registered User
    # in this shared dev DB) always walks first -- mark them busy so the walk actually
    # reaches this test's own interviewer, same pattern as
    # test_walks_past_a_busy_interviewer_to_the_next_in_the_pool above.
    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))

    user = _make_user(db_session, name)  # no _connect_google call -- the point of this test
    assert db_session.query(UserIntegration).filter(UserIntegration.user_id == user.id).first() is None

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session, smtp_username="hr-shared-token")

    sent = _capture_emails(monkeypatch)
    outcome, reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert reason is None
    assert len(sent) == 1
    assert sent[0]["to"] == email
    assert sent[0]["identity"] == "hr-shared-token"  # sent via the shared HR mailbox, not any personal Google/Gmail account

    attempts = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_interviewer_attempt")
        .all()
    )
    outcomes_by_name = {entry.details["interviewer"]: entry.details["outcome"] for entry in attempts}
    assert outcomes_by_name[REAL_POOL_INTERVIEWER] == "busy_this_week"
    assert outcomes_by_name[name] == "offer_sent"


def test_pool_interviewer_with_no_user_account_at_all_still_receives_an_offer(db_session, tmp_path, monkeypatch):
    """The normal case now, not an edge case: a pool interviewer (like Suresh A or
    Jagadeesh in the real tracker) who has an email on file in the Mails sheet but has
    NEVER been registered as a User in this system at all. Reachability is decided purely
    by the Mails sheet + interviewer_busy_this_week -- no User row is looked up or required
    anywhere in this flow any more."""
    tracker_path = _real_tracker_copy(tmp_path)
    name = f"Interviewer {uuid.uuid4().hex[:8]}"
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [name])
    _add_mail_entry(tracker_path, name, email)
    _configure_tracker(db_session, tracker_path)

    # Kishore (the real pool row's own entry) always walks first -- mark busy so the walk
    # reaches this test's own, deliberately unregistered interviewer.
    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))
    assert db_session.query(User).filter(User.full_name == name).first() is None

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session, smtp_username="hr-shared-token")

    sent = _capture_emails(monkeypatch)
    outcome, reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert reason is None
    assert len(sent) == 1
    assert sent[0]["to"] == email
    assert sent[0]["identity"] == "hr-shared-token"

    row = _interviewer_row(db_session, application)
    assert row.interviewer_name == name
    assert row.interviewer_email == email
    assert row.interviewer_user_id is None

    attempts = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_interviewer_attempt")
        .all()
    )
    outcomes_by_name = {entry.details["interviewer"]: entry.details["outcome"] for entry in attempts}
    assert outcomes_by_name[REAL_POOL_INTERVIEWER] == "busy_this_week"
    assert outcomes_by_name[name] == "offer_sent"
    # Never logged any more -- there is no "is this a registered User" check left in this
    # flow to produce this outcome.
    assert "not_a_registered_user" not in outcomes_by_name.values()


def test_pool_interviewer_with_no_mail_entry_is_skipped_as_no_email_on_file(db_session, tmp_path, monkeypatch):
    """A pool name with no row in the Mails sheet at all is skipped for the specific,
    correct reason "no_email_on_file" -- not "not_a_registered_user" (that outcome no
    longer exists), since there is no User-account check left to fail here at all."""
    tracker_path = _real_tracker_copy(tmp_path)
    unreachable_name = f"Ghost Interviewer {uuid.uuid4().hex[:8]}"
    reachable_name = f"Interviewer {uuid.uuid4().hex[:8]}"
    reachable_email = f"{uuid.uuid4().hex[:8]}@example.com"
    # unreachable_name is added to the pool but deliberately given NO Mails-sheet entry.
    _extend_pool_with(tracker_path, [unreachable_name, reachable_name])
    _add_mail_entry(tracker_path, reachable_name, reachable_email)
    _configure_tracker(db_session, tracker_path)

    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert len(sent) == 1
    assert sent[0]["to"] == reachable_email

    attempts = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_interviewer_attempt")
        .all()
    )
    outcomes_by_name = {entry.details["interviewer"]: entry.details["outcome"] for entry in attempts}
    assert outcomes_by_name[REAL_POOL_INTERVIEWER] == "busy_this_week"
    assert outcomes_by_name[unreachable_name] == "no_email_on_file"
    assert outcomes_by_name[reachable_name] == "offer_sent"


def test_confirmed_interview_for_a_no_user_account_interviewer_gets_plaintext_fields_and_confirmation_email(
    db_session, tmp_path, monkeypatch
):
    """End-to-end through _finalize for an interviewer who was never a registered User:
    the confirmation email must still reach them (via the Mails-sheet address carried on
    the NegotiationToken, not a User lookup), and the resulting Interview row must carry
    their plain-text name/email directly -- interviewer_id stays NULL, but List/Dashboard/
    reports must still be able to show who it was (see Interview's own docstring)."""
    tracker_path = _real_tracker_copy(tmp_path)
    name = f"Interviewer {uuid.uuid4().hex[:8]}"
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [name])
    _add_mail_entry(tracker_path, name, email)
    _configure_tracker(db_session, tracker_path)
    _mark_busy_this_week(tracker_path, REAL_POOL_INTERVIEWER, datetime.now(timezone.utc))
    assert db_session.query(User).filter(User.full_name == name).first() is None

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session, smtp_username="hr-shared-token")
    sent = _capture_emails(monkeypatch)
    _forbid_calendar_event(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_row = _interviewer_row(db_session, application)
    picks = _slot_isos(interviewer_row.round_day)[:2]

    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=picks)
    candidate_row = _candidate_row(db_session, application)
    result = neg.submit_negotiation_response(db_session, candidate_row.token, action="submit", selected_isos=picks)

    assert result.status == "confirmed"

    interview = db_session.query(Interview).filter(Interview.application_id == application.id).first()
    assert interview is not None
    assert interview.interviewer_id is None
    assert interview.interviewer_name == name
    assert interview.interviewer_email == email

    confirmation_emails = sent[2:]
    assert len(confirmation_emails) == 2
    assert {e["to"] for e in confirmation_emails} == {email, candidate.email}


# --- exactly-2-of-3 validation ---


def test_submission_rejected_unless_exactly_two_slots_are_selected(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"

    row = _interviewer_row(db_session, application)
    all_isos = _slot_isos(row.round_day)

    for bad_selection in ([], all_isos[:1], all_isos):
        result = neg.submit_negotiation_response(db_session, row.token, action="submit", selected_isos=bad_selection)
        assert result.status == "form"
        assert result.error is not None
        assert "exactly 2" in result.error

    db_session.refresh(row)
    assert row.invalidated_at is None  # a rejected submission never consumes the token
    assert row.selected_slots is None
    assert len(sent) == 1  # no candidate email ever went out from a rejected submission


def test_submission_rejected_for_a_slot_time_outside_the_real_three(db_session, tmp_path, monkeypatch):
    """Defense against a tampered POST -- a checkbox value that isn't one of this round's
    real 3 canned times must never be accepted, even paired with one that is."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    row = _interviewer_row(db_session, application)
    real_iso = _slot_isos(row.round_day)[0]
    fake_iso = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    result = neg.submit_negotiation_response(db_session, row.token, action="submit", selected_isos=[real_iso, fake_iso])
    assert result.status == "form"
    assert result.error is not None

    db_session.refresh(row)
    assert row.invalidated_at is None


# --- a valid submission starts the next step ---


def test_valid_interviewer_submission_starts_the_candidate_round(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    row = _interviewer_row(db_session, application)
    picks = _slot_isos(row.round_day)[:2]

    result = neg.submit_negotiation_response(db_session, row.token, action="submit", selected_isos=picks)

    assert result.status == "interviewer_submitted"
    db_session.refresh(row)
    assert row.invalidated_at is not None
    assert sorted(row.selected_slots) == sorted(picks)
    assert len(sent) == 2  # interviewer offer + candidate offer

    cand_row = _candidate_row(db_session, application)
    assert cand_row is not None
    assert cand_row.invalidated_at is None
    assert cand_row.round_day == row.round_day

    started_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_candidate_round_started")
        .first()
    )
    assert started_entry is not None

    workbook = load_workbook(tracker_path)
    log_rows = list(workbook["Interview Log"].iter_rows(min_row=2, values_only=True))
    header = [cell.value for cell in next(workbook["Interview Log"].iter_rows(min_row=1, max_row=1))]
    status_col = header.index("Status")
    assert any(row_vals[status_col] == "Awaiting Candidate Response" for row_vals in log_rows)


# --- decline falls back to the next interviewer / day+1 retry -- unchanged fallback ---


def test_interviewer_decline_falls_back_to_the_next_interviewer_same_day(db_session, tmp_path, monkeypatch):
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
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"
    assert sent[-1]["to"] == email_a

    row_a = _interviewer_row(db_session, application, interviewer_name=name_a)
    result = neg.submit_negotiation_response(db_session, row_a.token, action="decline", selected_isos=[])
    assert result.status == "declined"

    assert len(sent) == 2
    assert sent[1]["to"] == email_b

    db_session.refresh(row_a)
    assert row_a.invalidated_at is not None
    assert row_a.selected_slots is None


def test_both_days_exhausted_flags_the_application_for_manual_scheduling(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)  # the real pool's only interviewer

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"

    day1_row = _interviewer_row(db_session, application)
    day1_round = day1_row.round_day
    neg.submit_negotiation_response(db_session, day1_row.token, action="decline", selected_isos=[])

    # The pool has only one interviewer -- day 1 is now exhausted, so the one retry (day
    # after) must have auto-started against the SAME pool.
    day2_row = _interviewer_row(db_session, application)
    assert day2_row.round_day == day1_round + timedelta(days=1)
    assert day2_row.id != day1_row.id
    assert len(sent) == 2  # day1 offer + day2 offer

    neg.submit_negotiation_response(db_session, day2_row.token, action="decline", selected_isos=[])

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


# --- the live bug this session found: once flagged for manual scheduling, retry must
# actually be able to un-stick the application, not silently skip forever ---


def test_flagged_for_manual_scheduling_becomes_retriable_after_retry_negotiation(db_session, tmp_path, monkeypatch):
    """Reproduces the exact contradiction found live: an application flagged
    interview_negotiation_manual_scheduling_required kept getting reported ELIGIBLE by
    check_retry_eligibility while attempt_auto_negotiate_interview_slots' own guard
    (_has_live_negotiation_or_scheduled_interview) silently skipped every subsequent
    attempt forever, since it read the flag as "was this ever logged" rather than "is this
    still the most recent word on it." retry_negotiation must now actually clear it."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)  # the real pool's only interviewer

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)

    # Exhaust the (one-interviewer) pool on both retryable days to get flagged, exactly as
    # in test_both_days_exhausted_flags_the_application_for_manual_scheduling above.
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"
    day1_row = _interviewer_row(db_session, application)
    neg.submit_negotiation_response(db_session, day1_row.token, action="decline", selected_isos=[])
    day2_row = _interviewer_row(db_session, application)
    neg.submit_negotiation_response(db_session, day2_row.token, action="decline", selected_isos=[])

    manual_flag = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_manual_scheduling_required")
        .first()
    )
    assert manual_flag is not None

    # A bare re-attempt (NOT through retry_negotiation) must still be blocked -- the flag is
    # cleared specifically by retry_negotiation, never by simply re-running the trigger.
    bare_outcome, bare_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert bare_outcome is None
    assert bare_reason == "Application is flagged for manual scheduling and needs a human to pick it up"

    # check_retry_eligibility correctly keeps saying ELIGIBLE throughout -- this whole
    # mechanism exists specifically to un-stick an application flagged this way.
    assert neg.check_retry_eligibility(db_session, application) is None

    # A second interviewer, added to the pool only now -- never attempted for either day
    # tried above, so a genuinely fresh retry (flag cleared, not short-circuited by it) can
    # actually reach "started" again, not just re-discover the same two exhausted days.
    new_name = f"Interviewer {uuid.uuid4().hex[:8]}"
    new_email = f"{uuid.uuid4().hex[:8]}@example.com"
    _extend_pool_with(tracker_path, [new_name])
    _add_mail_entry(tracker_path, new_name, new_email)
    new_user = _make_user(db_session, new_name)
    _connect_google(db_session, new_user)

    outcome, invalidated_count, reason = neg.retry_negotiation(db_session, application, recruiter)

    assert outcome == "started"  # actually un-stuck this time, not re-flagged
    assert reason is None
    fresh_row = _interviewer_row(db_session, application, interviewer_name=new_name)
    assert fresh_row is not None

    cleared = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_manual_scheduling_cleared")
        .first()
    )
    assert cleared is not None
    # Not re-checking _has_live_negotiation_or_scheduled_interview here -- the successful
    # retry just created a genuinely live token of its own, which would (correctly) make
    # the guard non-None again for an unrelated reason. The specific condition this test is
    # about is already proven cleared: _is_flagged_for_manual_scheduling, checked directly.
    assert neg._is_flagged_for_manual_scheduling(db_session, application) is False


# --- overlap computation: guaranteed at 3 total slots (pigeonhole), earliest wins ---


def test_overlap_earliest_wins_when_both_sides_pick_identically(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer_user = _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session, smtp_username="hr-shared-token")
    sent = _capture_emails(monkeypatch)
    _forbid_calendar_event(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_row = _interviewer_row(db_session, application)
    all_isos = _slot_isos(interviewer_row.round_day)
    earliest_two = all_isos[:2]  # 10AM, 3PM -- overlap should be BOTH, earliest (10AM) wins

    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=earliest_two)
    candidate_row = _candidate_row(db_session, application)

    result = neg.submit_negotiation_response(db_session, candidate_row.token, action="submit", selected_isos=earliest_two)

    assert result.status == "confirmed"
    assert result.scheduled_at == datetime.fromisoformat(earliest_two[0])

    db_session.refresh(application)
    assert application.status == "interview_scheduled"
    interview = db_session.query(Interview).filter(Interview.application_id == application.id).first()
    assert interview is not None
    # Compared as datetimes (not isoformat() strings) -- Postgres round-trips a timestamptz
    # back in its own session offset (e.g. IST), the same instant but a different string.
    assert interview.scheduled_at == datetime.fromisoformat(earliest_two[0])
    assert interview.scheduling_method == "auto"

    # 2 negotiation-round emails (interviewer + candidate picking their slots) + 2
    # confirmation emails with the generated .ics attached, one to each party -- and,
    # per _forbid_calendar_event above, this never touches the Google Calendar API.
    assert len(sent) == 4
    assert all(email["identity"] == "hr-shared-token" for email in sent)

    confirmation_emails = sent[2:]
    assert {email["to"] for email in confirmation_emails} == {interviewer_user.email, candidate.email}
    for email in confirmation_emails:
        assert email["subject"] == f"Interview confirmed: {job.title}"
        assert email["attachment"] is not None
        assert email["attachment"].filename == "interview.ics"
        parsed = Calendar.from_ical(email["attachment"].content)
        event = next(iter(parsed.walk("VEVENT")))
        assert event["dtstart"].dt == datetime.fromisoformat(earliest_two[0])


def test_overlap_computation_with_partially_different_picks_still_guarantees_one_common_slot(db_session, tmp_path, monkeypatch):
    """Interviewer and candidate pick DIFFERENT (but not disjoint) pairs -- with only 3
    total slots, 2-of-3 picked by each side always shares at least one (pigeonhole): here
    exactly one, and that one must be what's scheduled."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    _capture_emails(monkeypatch)
    _forbid_calendar_event(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_row = _interviewer_row(db_session, application)
    all_isos = _slot_isos(interviewer_row.round_day)  # [10AM, 3PM, 6PM]

    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=all_isos[:2])  # 10AM, 3PM
    candidate_row = _candidate_row(db_session, application)

    result = neg.submit_negotiation_response(db_session, candidate_row.token, action="submit", selected_isos=all_isos[1:])  # 3PM, 6PM

    # Overlap is exactly {3PM} -- neither the never-common 10AM nor 6PM.
    assert result.status == "confirmed"
    assert result.scheduled_at.isoformat() == all_isos[1]


def test_negotiation_module_no_longer_references_create_confirmed_calendar_event():
    """Static guard alongside the two live-flow tests above (both run with
    _forbid_calendar_event installed, which fails loudly if the underlying Google Calendar
    API call ever happens) -- confirms confirmation.create_confirmed_calendar_event isn't
    even imported into this module anymore, so this mechanic's confirmation step
    (_finalize) has no way to reach it at all, not just that it happens not to be called
    today."""
    assert not hasattr(neg, "create_confirmed_calendar_event")


# --- defensive no-overlap path: unreachable at 3 slots, forced directly per the task ---


def _submit_interviewer_and_get_candidate_row(db_session, tmp_path, monkeypatch, recruiter) -> tuple:
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    _connect_hr_smtp(db_session)
    sent = _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_row = _interviewer_row(db_session, application)
    picks = _slot_isos(interviewer_row.round_day)[:2]
    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=picks)
    return application, _candidate_row(db_session, application), sent


def test_defensive_no_overlap_reprompts_the_candidate_only(db_session, tmp_path, monkeypatch):
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    application, candidate_row, sent = _submit_interviewer_and_get_candidate_row(db_session, tmp_path, monkeypatch, recruiter)

    # A real submission can never actually reach zero overlap at 3 total slots (pigeonhole)
    # -- force it directly, exactly as the task asks, rather than trying to construct real
    # data that can't exist under today's slot count.
    candidate_row.responded_at = datetime.now(timezone.utc)
    candidate_row.invalidated_at = candidate_row.responded_at
    candidate_row.selected_slots = ["not-a-real-slot-1", "not-a-real-slot-2"]
    db_session.commit()

    emails_before = len(sent)
    result = neg._resolve_candidate_submission(db_session, application, candidate_row)

    assert result.status == "candidate_reprompted"
    assert len(sent) == emails_before + 1  # a fresh candidate email went out

    reprompted_row = _candidate_row(db_session, application)
    assert reprompted_row.id != candidate_row.id
    assert reprompted_row.invalidated_at is None
    assert reprompted_row.round_day == candidate_row.round_day

    reprompt_logged = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_candidate_reprompted")
        .first()
    )
    assert reprompt_logged is not None

    db_session.refresh(application)
    assert application.status == "hr_selected"  # not finalized -- still awaiting real overlap


def test_second_consecutive_no_overlap_flags_manual_scheduling_instead_of_looping(db_session, tmp_path, monkeypatch):
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    application, candidate_row, sent = _submit_interviewer_and_get_candidate_row(db_session, tmp_path, monkeypatch, recruiter)

    candidate_row.responded_at = datetime.now(timezone.utc)
    candidate_row.invalidated_at = candidate_row.responded_at
    candidate_row.selected_slots = ["not-a-real-slot-1", "not-a-real-slot-2"]
    db_session.commit()
    first_reprompt = neg._resolve_candidate_submission(db_session, application, candidate_row)
    assert first_reprompt.status == "candidate_reprompted"

    reprompted_row = _candidate_row(db_session, application)
    reprompted_row.responded_at = datetime.now(timezone.utc)
    reprompted_row.invalidated_at = reprompted_row.responded_at
    reprompted_row.selected_slots = ["still-not-real-1", "still-not-real-2"]
    db_session.commit()

    second_result = neg._resolve_candidate_submission(db_session, application, reprompted_row)

    assert second_result.status == "declined"
    manual_flag = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_manual_scheduling_required")
        .first()
    )
    assert manual_flag is not None
    # No third negotiation row was ever started for the candidate role.
    assert _candidate_row(db_session, application).id == reprompted_row.id


# --- branded HTML negotiation offer emails -- rendered from the real, published
# recruitment.negotiation.* message_templates (Part 4 -- see
# hrctl.migrate_comms_templates and _render_negotiation_email), matching the negotiation
# landing page's own branded shell (negotiation_router.py), not a plain-text email that
# then jumps to a fully branded page. Content is now DATA (see
# tests/test_template_render_parity.py for the proof it matches this module's own old,
# now-deleted hardcoded builders byte-for-byte/text-for-text) -- these tests exercise the
# real render path end to end instead of a since-deleted pure function. ---


def test_interviewer_email_html_interpolates_candidate_job_and_date_with_a_cta_link(db_session):
    _subject, _text, html = neg._render_negotiation_email(
        db_session, "recruitment.negotiation.interviewer_offer",
        candidate_name="Jane Doe", job_title="Backend Engineer", round_day="26 Aug 2026",
        picker_url="https://ctdhr.example.com/interview-negotiation/tok123",
        required_picks=neg.REQUIRED_PICKS, token_expiry_days=neg.TOKEN_EXPIRY_DAYS,
    )

    assert "Jane Doe" in html
    assert "Backend Engineer" in html
    assert "26 Aug 2026" in html
    assert 'href="https://ctdhr.example.com/interview-negotiation/tok123"' in html
    assert "Choose Your Available Slots" in html
    assert "CTD TECHS" in html
    assert "expires in 5 days" in html
    assert html.strip().lower().startswith("<!doctype html>")


def test_candidate_email_html_interpolates_job_with_a_cta_link(db_session):
    _subject, _text, html = neg._render_negotiation_email(
        db_session, "recruitment.negotiation.candidate_offer",
        candidate_name="Jane Doe", job_title="Backend Engineer",
        picker_url="https://ctdhr.example.com/interview-negotiation/tok456",
        required_picks=neg.REQUIRED_PICKS, token_expiry_days=neg.TOKEN_EXPIRY_DAYS,
    )

    assert "Hi Jane Doe," in html
    assert "Backend Engineer" in html
    assert 'href="https://ctdhr.example.com/interview-negotiation/tok456"' in html
    assert "Choose Your Available Slots" in html
    assert "CTD TECHS" in html
    assert "expires in 5 days" in html


def test_negotiation_email_html_escapes_candidate_name_and_job_title(db_session):
    _subject, _text, html = neg._render_negotiation_email(
        db_session, "recruitment.negotiation.interviewer_offer",
        candidate_name="<script>alert(1)</script>", job_title="R&D <Lead>", round_day="26 Aug 2026",
        picker_url="https://example.com/x", required_picks=neg.REQUIRED_PICKS, token_expiry_days=neg.TOKEN_EXPIRY_DAYS,
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "R&amp;D" in html
    assert "&lt;Lead&gt;" in html


def test_interviewer_offer_email_is_sent_with_a_populated_html_body(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, name="Jane Doe")
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    sent = _capture_emails(monkeypatch)

    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome == "started"
    assert len(sent) == 1
    email = sent[0]
    assert email["subject"] == f"Interview scheduling for {job.title}"
    assert email["html_body"] is not None
    assert "Jane Doe" in email["html_body"]
    assert job.title in email["html_body"]
    assert "Choose Your Available Slots" in email["html_body"]
    # The plain-text version must still be sent too -- html_body is an addition, not a
    # replacement.
    assert email["body"] and "<html" not in email["body"]


def test_candidate_offer_email_is_sent_with_a_populated_html_body(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, name="Jane Doe")
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    sent = _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    interviewer_row = _interviewer_row(db_session, application)
    picks = _slot_isos(interviewer_row.round_day)[:2]
    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=picks)

    candidate_email = sent[-1]
    assert candidate_email["subject"] == f"Interview scheduling for {job.title}"
    assert candidate_email["html_body"] is not None
    assert "Jane Doe" in candidate_email["html_body"]
    assert job.title in candidate_email["html_body"]
    assert "Choose Your Available Slots" in candidate_email["html_body"]
    assert candidate_email["body"] and "<html" not in candidate_email["body"]


# --- shared HR mailbox: same sender regardless of actor, graceful skip when absent ---


def test_email_uses_shared_hr_credentials_regardless_of_which_recruiter_triggered_it(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    _connect_hr_smtp(db_session, smtp_username="hr-shared-token")

    sent = _capture_emails(monkeypatch)

    # Two entirely different recruiters, NEITHER of whom has any personal Google
    # connection at all, each shortlisting their own separate candidate.
    recruiter_1 = _make_user(db_session, "Recruiter One", role="recruiter")
    job_1 = _make_job(db_session)
    application_1 = _make_application(db_session, job_1, _make_candidate(db_session))
    outcome_1, _reason_1 = neg.attempt_auto_negotiate_interview_slots(db_session, application_1, recruiter_1)

    recruiter_2 = _make_user(db_session, "Recruiter Two", role="recruiter")
    job_2 = _make_job(db_session)
    application_2 = _make_application(db_session, job_2, _make_candidate(db_session))
    outcome_2, _reason_2 = neg.attempt_auto_negotiate_interview_slots(db_session, application_2, recruiter_2)

    assert outcome_1 == "started"
    assert outcome_2 == "started"
    assert len(sent) == 2
    assert all(email["identity"] == "hr-shared-token" for email in sent)


def test_skips_gracefully_and_logs_a_clear_reason_when_hr_smtp_is_not_configured(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    _disconnect_hr_smtp(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")

    sent = _capture_emails(monkeypatch)
    outcome, reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome is None
    assert reason is not None and "SMTP" in reason and "not configured" in reason
    assert sent == []

    skipped = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_skipped")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert skipped is not None
    assert "SMTP" in skipped.details["reason"]
    assert "not configured" in skipped.details["reason"]

    # No orphaned negotiation state was left behind either -- the skip happens before any
    # row is created.
    assert _interviewer_row(db_session, application) is None


def test_undecryptable_hr_smtp_password_skips_gracefully(db_session, tmp_path, monkeypatch):
    # Deliberately NOT mocking send_hr_email here -- this exercises the real decrypt
    # failure inside app.integrations.hr_email.send_hr_email, not a mocked stand-in.
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    row = db_session.get(HrIntegration, 1)
    if row is None:
        row = HrIntegration(id=1)
        db_session.add(row)
    row.smtp_host = "smtp.example.com"
    row.smtp_username = "hr@example.com"
    row.smtp_password = "not-a-valid-fernet-token"
    db_session.commit()

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")

    outcome, reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)

    assert outcome is None
    assert reason is not None and "could not be decrypted" in reason

    skipped = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_skipped")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert skipped is not None
    assert "could not be decrypted" in skipped.details["reason"]


# --- idempotency guard ---


def test_idempotency_guard_prevents_a_second_negotiation_for_the_same_application(db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    first, _first_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert first == "started"
    assert len(sent) == 1

    second, second_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert second is None
    assert second_reason is not None
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


# --- atomicity: a failed send must not leave its NegotiationToken row live (the
# orphaned-token incident -- a send failure after _create_negotiation_row already committed
# the row left it blocking _has_live_negotiation_or_scheduled_interview's idempotency guard
# for up to TOKEN_EXPIRY_DAYS even once the send issue itself was fixed) ---


def test_advance_interviewer_round_invalidates_row_on_send_failure_and_unblocks_retry(db_session, tmp_path, monkeypatch):
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("SMTP down")))

    outcome, reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome is None
    assert reason is not None and "SMTP down" in reason

    row = _interviewer_row(db_session, application)
    assert row is not None
    assert row.invalidated_at is not None

    skipped = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_skipped")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert skipped is not None
    assert "SMTP down" in skipped.details["reason"]

    # The now-invalidated row must not trip _has_live_negotiation_or_scheduled_interview --
    # a subsequent attempt (SMTP working this time) must actually start, not be skipped as
    # "already has a live negotiation".
    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    retry_outcome, _retry_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert retry_outcome == "started"


def test_start_candidate_round_invalidates_row_on_send_failure_and_unblocks_guard(db_session, tmp_path, monkeypatch):
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"
    interviewer_row = _interviewer_row(db_session, application)
    picks = _slot_isos(interviewer_row.round_day)[:2]

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("candidate smtp fail")))
    result = neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=picks)

    # The interviewer's own submission is still recorded (it succeeded) even though the
    # follow-up candidate email failed -- _start_candidate_round's failure is a silent
    # best-effort skip, same contract as every other step here.
    assert result.status == "interviewer_submitted"
    db_session.refresh(interviewer_row)
    assert interviewer_row.invalidated_at is not None

    candidate_row = _candidate_row(db_session, application)
    assert candidate_row is not None
    assert candidate_row.invalidated_at is not None  # the failed send's own row, cleaned up

    assert neg._has_live_negotiation_or_scheduled_interview(db_session, application) is None


def test_start_candidate_round_does_not_write_tracker_row_or_audit_log_on_send_failure(db_session, tmp_path, monkeypatch):
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome == "started"
    interviewer_row = _interviewer_row(db_session, application)
    picks = _slot_isos(interviewer_row.round_day)[:2]

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("candidate smtp fail")))
    neg.submit_negotiation_response(db_session, interviewer_row.token, action="submit", selected_isos=picks)

    started_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_candidate_round_started")
        .first()
    )
    assert started_entry is None

    workbook = load_workbook(tracker_path)
    log_rows = list(workbook["Interview Log"].iter_rows(min_row=2, values_only=True))
    header = [cell.value for cell in next(workbook["Interview Log"].iter_rows(min_row=1, max_row=1))]
    status_col = header.index("Status")
    assert not any(row[status_col] == "Awaiting Candidate Response" for row in log_rows)


def test_attempt_auto_negotiate_writes_send_failed_interview_log_row_on_smtp_error(db_session, tmp_path, monkeypatch):
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("SMTP down")))
    outcome, _reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert outcome is None

    workbook = load_workbook(tracker_path)
    sheet = workbook["Interview Log"]
    header = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    status_col = header.index("Status")
    candidate_col = header.index("Candidate")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    matching = [row for row in rows if row[status_col] == "Send Failed - Retry Needed"]

    assert len(matching) == 1
    assert matching[0][candidate_col] == candidate.full_name


# --- HTTP layer: GET renders the form, POST submits it ---


def test_get_negotiation_page_renders_the_pick_two_form(client, db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    row = _interviewer_row(db_session, application)

    response = client.get(f"/interview-negotiation/{row.token}")

    assert response.status_code == 200
    assert "CTD TECHS" in response.text
    assert "Interview Scheduling" in response.text
    assert "None of these work for me" in response.text
    assert "Submit My Selections" in response.text
    assert response.text.count('class="slot-checkbox"') == 3


def test_post_negotiation_page_with_wrong_count_rerenders_form_with_error(client, db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    row = _interviewer_row(db_session, application)
    one_iso = _slot_isos(row.round_day)[0]

    response = client.post(
        f"/interview-negotiation/{row.token}", data={"action": "submit", "slots": [one_iso]}
    )

    assert response.status_code == 200
    assert "exactly 2" in response.text
    db_session.refresh(row)
    assert row.invalidated_at is None


def test_post_negotiation_page_decline_renders_declined_outcome(client, db_session, tmp_path, monkeypatch):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)
    _capture_emails(monkeypatch)

    neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    row = _interviewer_row(db_session, application)

    response = client.post(f"/interview-negotiation/{row.token}", data={"action": "decline"})

    assert response.status_code == 200
    assert "noted" in response.text.lower()
    db_session.refresh(row)
    assert row.invalidated_at is not None


# --- router wiring: fires on the real Shortlisted transition through both endpoints ---


def test_legacy_shortlist_decision_select_triggers_the_negotiation(client, db_session, tmp_path, monkeypatch, make_auth_headers):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    headers = make_auth_headers(role="recruiter", email=email)
    _connect_hr_smtp(db_session)

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
    _connect_hr_smtp(db_session)

    sent = _capture_emails(monkeypatch)
    response = client.post(f"/applications/{application.id}/shortlist-status", json={"target_status": "shortlisted"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"
    assert len(sent) == 1


def test_fresh_shortlist_transition_clears_a_leftover_manual_scheduling_flag_and_still_negotiates(
    client, db_session, tmp_path, monkeypatch, make_auth_headers
):
    """The real Kranthi Kumar incident: an application flagged manual-scheduling-required
    during an EARLIER shortlisting cycle, moved back to Screening, then shortlisted again
    fresh -- a genuinely new decision, unrelated to the old flag. Before this fix,
    attempt_auto_negotiate_interview_slots' own guard saw the stale flag and silently
    skipped, with no interviewer ever contacted and no error surfaced anywhere."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    headers = make_auth_headers(role="recruiter", email=email)
    _connect_hr_smtp(db_session)

    # A flag left over from an earlier, unrelated shortlisting cycle -- logged directly,
    # not walked through a real pool exhaustion, since only the flag's presence matters.
    db_session.add(AuditLog(
        entity_type="application", entity_id=application.id,
        action="interview_negotiation_manual_scheduling_required", actor=email,
        details={"job_title": job.title, "candidate_name": candidate.full_name},
    ))
    db_session.commit()
    assert neg._is_flagged_for_manual_scheduling(db_session, application) is True

    sent = _capture_emails(monkeypatch)
    response = client.post(f"/applications/{application.id}/shortlist-status", json={"target_status": "shortlisted"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "hr_selected"
    # The interviewer was actually contacted this time -- not silently skipped.
    assert len(sent) == 1

    cleared = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_manual_scheduling_cleared")
        .first()
    )
    assert cleared is not None
    assert neg._is_flagged_for_manual_scheduling(db_session, application) is False


def test_reset_application_to_screening_clears_a_manual_scheduling_flag(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="hr_selected")

    db_session.add(AuditLog(
        entity_type="application", entity_id=application.id,
        action="interview_negotiation_manual_scheduling_required", actor="kg@ctdtechs.com",
        details={"job_title": job.title, "candidate_name": candidate.full_name},
    ))
    db_session.commit()
    assert neg._is_flagged_for_manual_scheduling(db_session, application) is True

    neg.reset_application_to_screening(db_session, application, "aisub2@ctdtechs.ai", "test reset")

    db_session.refresh(application)
    assert application.status == "screened"
    assert neg._is_flagged_for_manual_scheduling(db_session, application) is False

    reset_logged = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "manual_stage_reset_to_screening")
        .first()
    )
    assert reset_logged is not None
    assert reset_logged.details["previous_status"] == "hr_selected"
    assert reset_logged.details["new_status"] == "screened"


# --- POST .../retry-negotiation: the manual escape hatch for an application stuck at
# Shortlisted after a send failure -- replaces the one-off manual NegotiationToken cleanup
# that exact incident used to require by hand. ---


def test_retry_negotiation_succeeds_when_eligible(db_session, tmp_path, monkeypatch):
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    # The original failure, already self-cleaned by the inline _invalidate_batch fix -- so
    # nothing is left live going into the retry (see the separate stale-token test below for
    # the case where something IS left live).
    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("SMTP down")))
    first_outcome, _first_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert first_outcome is None

    assert neg.check_retry_eligibility(db_session, application) is None

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    outcome, invalidated_count, reason = neg.retry_negotiation(db_session, application, recruiter)

    assert outcome == "started"
    assert invalidated_count == 0
    assert reason is None

    row = _interviewer_row(db_session, application)
    assert row.invalidated_at is None  # the fresh, real retry row

    retry_logged = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_retry_triggered")
        .first()
    )
    assert retry_logged is not None
    assert retry_logged.actor == recruiter.email


def test_retry_negotiation_rejected_when_status_is_not_shortlisted(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened")

    reason = neg.check_retry_eligibility(db_session, application)
    assert reason == "Application is not in Shortlisted status"


def test_retry_negotiation_rejected_when_interview_already_exists(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    interview = Interview(
        application_id=application.id, interviewer_id=interviewer.id,
        scheduled_at=datetime.now(timezone.utc), scheduling_method="auto",
    )
    db_session.add(interview)
    db_session.commit()

    reason = neg.check_retry_eligibility(db_session, application)
    assert reason == "An interview has already been scheduled for this application"


# --- check_retry_eligibility and attempt_auto_negotiate_interview_slots' own guard
# (_has_live_negotiation_or_scheduled_interview) must never independently drift again on
# the conditions they're meant to share -- see _in_flight_or_scheduled_reason. ---


def test_check_retry_eligibility_and_the_guard_agree_on_an_existing_interview(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    interview = Interview(
        application_id=application.id, interviewer_id=interviewer.id,
        scheduled_at=datetime.now(timezone.utc), scheduling_method="auto",
    )
    db_session.add(interview)
    db_session.commit()

    eligibility_reason = neg.check_retry_eligibility(db_session, application)
    guard_reason = neg._has_live_negotiation_or_scheduled_interview(db_session, application)

    assert eligibility_reason is not None
    assert eligibility_reason == guard_reason


def test_check_retry_eligibility_and_the_guard_agree_when_nothing_is_in_flight(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    assert neg.check_retry_eligibility(db_session, application) is None
    assert neg._has_live_negotiation_or_scheduled_interview(db_session, application) is None


def test_check_retry_eligibility_tolerates_a_stale_token_the_guard_still_blocks_on(db_session, tmp_path):
    """The one condition these two are deliberately allowed to differ on, by design: a live
    token OLDER than RETRY_MIDFLIGHT_WINDOW is presumed orphaned by check_retry_eligibility
    (about to be invalidated by retry_negotiation before the guard ever runs again), but
    still counts as blocking for a fresh auto-trigger, which must never fire alongside a
    live token of any age. Documented explicitly here rather than left as an implicit gap --
    the actual bug this session found (the manual-scheduling flag) was an UNDOCUMENTED,
    unintentional version of this same shape."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    round_day = neg._tomorrow_ist(datetime.now(timezone.utc))
    stale_row = neg._create_negotiation_row(
        db_session, application=application, role="interviewer", interviewer_user_id=interviewer.id,
        actor_email="recruiter@example.com", candidate_name=candidate.full_name, job_title=job.title,
        interviewer_name=REAL_POOL_INTERVIEWER, round_day=round_day, tracker_path=str(tracker_path),
    )
    stale_row.created_at = datetime.now(timezone.utc) - neg.RETRY_MIDFLIGHT_WINDOW - timedelta(minutes=1)
    db_session.commit()

    assert neg.check_retry_eligibility(db_session, application) is None
    assert neg._has_live_negotiation_or_scheduled_interview(db_session, application) is not None


def test_retry_negotiation_endpoint_surfaces_reason_on_a_skip(client, db_session, tmp_path, make_auth_headers):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    headers = make_auth_headers(role="recruiter")
    # hr_integrations is a singleton row this shared dev DB may already have real SMTP
    # credentials committed on (same "an earlier test's own db.commit() can leave it
    # configured" reasoning as _disconnect_hr_smtp's own comment) -- explicitly reset it so
    # this test's "not configured" precondition holds regardless of that real state.
    _disconnect_hr_smtp(db_session)

    response = client.post(f"/interview-scheduling/applications/{application.id}/retry-negotiation", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] is None
    assert body["reason"] == "HR mailbox's SMTP settings are not configured -- cannot send negotiation emails"


def test_retry_negotiation_endpoint_returns_409_tracker_locked_when_the_file_is_open(
    client, db_session, tmp_path, make_auth_headers, monkeypatch
):
    """Part 1 pending fix (docs/HRMS_COMPLETE_SPEC.txt): a locked tracker file surfaces as a
    distinct 409 {code: "TRACKER_LOCKED"}, not a generic 200-with-reason or a raw 500 --
    see app.interview_scheduling.negotiation.TrackerLockedNegotiationError and
    router.py's retry_negotiation_endpoint. sync_interviewer_pool_job_titles is the first
    tracker write attempt_auto_negotiate_interview_slots makes, so raising
    TrackerFileLockedError there is the simplest way to simulate the file being open in
    Excel at the moment a recruiter clicks Retry Scheduling."""
    from app.interview_scheduling.tracker import TrackerFileLockedError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    headers = make_auth_headers(role="recruiter")
    _connect_hr_smtp(db_session)

    def _raise_locked(*_args, **_kwargs):
        raise TrackerFileLockedError("Tracker file is open in Excel -- close it and retry. (simulated)")

    monkeypatch.setattr(neg, "sync_interviewer_pool_job_titles", _raise_locked)
    response = client.post(f"/interview-scheduling/applications/{application.id}/retry-negotiation", headers=headers)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "TRACKER_LOCKED"
    assert "Tracker file is open in Excel" in detail["message"]


def test_retry_negotiation_rejected_when_a_token_was_just_created(db_session, tmp_path):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    round_day = neg._tomorrow_ist(datetime.now(timezone.utc))
    neg._create_negotiation_row(
        db_session, application=application, role="interviewer", interviewer_user_id=interviewer.id,
        actor_email="recruiter@example.com", candidate_name=candidate.full_name, job_title=job.title,
        interviewer_name=REAL_POOL_INTERVIEWER, round_day=round_day, tracker_path=str(tracker_path),
    )

    # Created moments ago (real wall-clock created_at, well inside RETRY_MIDFLIGHT_WINDOW)
    # -- genuinely may still be in flight, must not be treated as orphaned.
    reason = neg.check_retry_eligibility(db_session, application)
    assert reason is not None
    assert "may still be in flight" in reason


def test_retry_negotiation_cleans_up_a_stale_orphaned_token_and_still_retries(db_session, tmp_path, monkeypatch):
    """The exact incident this whole mechanism exists for: a token that went live and was
    never invalidated (predating the _invalidate_batch atomicity fix, or left behind for any
    other reason), well past any reasonable "just fired" window. check_retry_eligibility
    must treat it as orphaned rather than mid-flight, and retry_negotiation must clean it up
    automatically -- the exact manual DB fix this replaces -- before trying again."""
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    _connect_hr_smtp(db_session)

    round_day = neg._tomorrow_ist(datetime.now(timezone.utc))
    stale_row = neg._create_negotiation_row(
        db_session, application=application, role="interviewer", interviewer_user_id=interviewer.id,
        actor_email="recruiter@example.com", candidate_name=candidate.full_name, job_title=job.title,
        interviewer_name=REAL_POOL_INTERVIEWER, round_day=round_day, tracker_path=str(tracker_path),
    )
    stale_row.created_at = datetime.now(timezone.utc) - neg.RETRY_MIDFLIGHT_WINDOW - timedelta(minutes=1)
    db_session.commit()

    assert stale_row.invalidated_at is None  # orphaned: live, unresolved

    reason = neg.check_retry_eligibility(db_session, application)
    assert reason is None  # too old to count as "mid-flight" -- eligible

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    outcome, invalidated_count, reason = neg.retry_negotiation(db_session, application, recruiter)

    assert outcome == "started"
    assert invalidated_count == 1
    assert reason is None
    db_session.refresh(stale_row)
    assert stale_row.invalidated_at is not None

    cleanup_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "interview_negotiation_stale_tokens_invalidated")
        .first()
    )
    assert cleanup_entry is not None
    assert cleanup_entry.details["invalidated_count"] == 1


def test_retry_negotiation_endpoint_succeeds_and_clears_the_send_failed_state(
    client, db_session, tmp_path, monkeypatch
):
    from app.core.security import create_access_token
    from app.integrations.hr_email import SmtpError

    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    _real_pool_interviewer(db_session)

    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    recruiter = _make_user(db_session, "Recruiter", role="recruiter")
    headers = {"Authorization": f"Bearer {create_access_token(subject=str(recruiter.id))}"}
    _connect_hr_smtp(db_session)

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: (_ for _ in ()).throw(SmtpError("SMTP down")))
    first_outcome, _first_reason = neg.attempt_auto_negotiate_interview_slots(db_session, application, recruiter)
    assert first_outcome is None

    monkeypatch.setattr(neg, "send_hr_email", lambda *a, **k: None)
    response = client.post(f"/interview-scheduling/applications/{application.id}/retry-negotiation", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "started"
    assert body["invalidated_stale_tokens"] == 0
    assert body["reason"] is None


def test_retry_negotiation_endpoint_rejects_when_an_interview_already_exists(
    client, db_session, tmp_path, make_auth_headers
):
    tracker_path = _real_tracker_copy(tmp_path)
    _configure_tracker(db_session, tracker_path)
    interviewer = _real_pool_interviewer(db_session)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)
    headers = make_auth_headers(role="recruiter")

    interview = Interview(
        application_id=application.id, interviewer_id=interviewer.id,
        scheduled_at=datetime.now(timezone.utc), scheduling_method="auto",
    )
    db_session.add(interview)
    db_session.commit()

    response = client.post(f"/interview-scheduling/applications/{application.id}/retry-negotiation", headers=headers)

    assert response.status_code == 409
    assert "already been scheduled" in response.json()["detail"]
