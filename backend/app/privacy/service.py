"""Privacy operations (docs/HRMS_COMPLETE_SPEC.txt Part 13 section E).

Erasure is anonymisation/pseudonymisation, never a row delete: records keep their ids (so
audit trails, aggregates and FKs stay intact) while the personal data in them is replaced.
Employment records are statutory -- an employee's job history, compensation and letters
are retained for `privacy.retention_days.ex_employee`; erasure before that pseudonymises
only the non-statutory personal fields and says so in the request's outcome. A request
with `legal_hold` refuses erasure entirely.

Retention purges are always two-phase: `retention_dry_run()` writes a report, a human
approves it, then `execute_retention_run()` applies exactly the ids in that report.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.connection import Connection, ConnectionRoute
from app.models.core_hr import Employee, EmploymentRecord
from app.models.intelligence import CopilotConversation, CopilotMessage
from app.models.privacy import (
    CONSENT_ACTIONS,
    DPR_TYPES,
    SUBJECT_TYPES,
    BreachIncident,
    ConsentRecord,
    DataPrincipalRequest,
    PrivacyNotice,
    RetentionRun,
)
from app.models.service_desk import Separation
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

ERASED_NAME = "[erased]"
RETENTION_CATEGORIES = ("candidate_unhired", "ex_employee", "copilot_conversations")


class PrivacyError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant: TenantContext, key: str):
    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---- notices + consent ledger ----


def publish_notice(db: Session, tenant: TenantContext, *, purpose: str, title: str, body: str, language: str = "en", actor: str) -> PrivacyNotice:
    latest = db.query(PrivacyNotice).filter(PrivacyNotice.tenant_id == tenant.tenant_id, PrivacyNotice.purpose == purpose, PrivacyNotice.language == language).order_by(PrivacyNotice.version.desc()).first()
    for old in db.query(PrivacyNotice).filter(PrivacyNotice.tenant_id == tenant.tenant_id, PrivacyNotice.purpose == purpose, PrivacyNotice.language == language, PrivacyNotice.status == "published").all():
        old.status = "retired"
    notice = PrivacyNotice(tenant_id=tenant.tenant_id, purpose=purpose, version=(latest.version + 1) if latest else 1, language=language, title=title, body=body,
                           status="published", published_at=_now(), created_by=actor)
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def current_notice(db: Session, tenant: TenantContext, purpose: str, language: str = "en") -> Optional[PrivacyNotice]:
    query = db.query(PrivacyNotice).filter(PrivacyNotice.tenant_id == tenant.tenant_id, PrivacyNotice.purpose == purpose, PrivacyNotice.status == "published")
    return query.filter(PrivacyNotice.language == language).first() or query.filter(PrivacyNotice.language == "en").first()


def processors(db: Session, tenant: TenantContext) -> list[dict]:
    """Processor list for the privacy notice, derived automatically from the tenant's own
    active connections and what each is routed for -- never a hand-maintained list."""
    routes = db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.enabled.is_(True)).all()
    by_connection: dict = {}
    for route in routes:
        by_connection.setdefault(route.connection_id, set()).add(route.purpose.split(".")[0])
    out = []
    for connection in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.status == "active").all():
        out.append({"provider": connection.provider_code, "used_for": sorted(by_connection.get(connection.id, set()))})
    return sorted(out, key=lambda p: p["provider"])


def record_consent(
    db: Session, tenant: TenantContext, *, subject_type: str, purpose: str, action: str = "granted", subject_id: Optional[UUID] = None,
    subject_email: Optional[str] = None, channel: str = "web", evidence: Optional[dict] = None, notice: Optional[PrivacyNotice] = None,
) -> ConsentRecord:
    if subject_type not in SUBJECT_TYPES or action not in CONSENT_ACTIONS:
        raise PrivacyError("invalid subject type or action")
    if subject_id is None and not subject_email:
        raise PrivacyError("a consent record needs a subject id or email")
    notice = notice or current_notice(db, tenant, purpose)
    row = ConsentRecord(tenant_id=tenant.tenant_id, subject_type=subject_type, subject_id=subject_id, subject_email=(subject_email or "").lower() or None,
                        purpose=purpose, action=action, channel=channel, evidence_json=evidence or {},
                        notice_id=notice.id if notice else None, notice_version=notice.version if notice else None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def has_consent(db: Session, tenant: TenantContext, *, purpose: str, subject_id: Optional[UUID] = None, subject_email: Optional[str] = None) -> bool:
    query = db.query(ConsentRecord).filter(ConsentRecord.tenant_id == tenant.tenant_id, ConsentRecord.purpose == purpose)
    if subject_id is not None:
        query = query.filter(ConsentRecord.subject_id == subject_id)
    elif subject_email:
        query = query.filter(ConsentRecord.subject_email == subject_email.lower())
    else:
        return False
    latest = query.order_by(ConsentRecord.recorded_at.desc()).first()
    return bool(latest and latest.action == "granted")


# ---- data principal requests ----


def create_request(db: Session, tenant: TenantContext, *, request_type: str, subject_type: str, subject_email: str,
                   subject_id: Optional[UUID] = None, details: Optional[str] = None) -> DataPrincipalRequest:
    if request_type not in DPR_TYPES or subject_type not in SUBJECT_TYPES:
        raise PrivacyError("invalid request or subject type")
    sla_days = int(_setting(db, tenant, "privacy.dpr_sla_days"))
    row = DataPrincipalRequest(tenant_id=tenant.tenant_id, request_type=request_type, subject_type=subject_type, subject_email=subject_email.lower(),
                               subject_id=subject_id, details=details, due_at=_now() + timedelta(days=sla_days))
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, "privacy.request_received", {"request_id": str(row.id), "type": request_type, "due_at": row.due_at.isoformat()})
    return row


def _resolve_subject(db: Session, tenant: TenantContext, request: DataPrincipalRequest):
    if request.subject_type == "candidate":
        query = db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id)
        return query.filter(Candidate.id == request.subject_id).first() if request.subject_id else query.filter(Candidate.email == request.subject_email).first()
    if request.subject_type == "employee":
        query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id)
        return query.filter(Employee.id == request.subject_id).first() if request.subject_id else query.filter(Employee.personal_email == request.subject_email).first()
    return None


def verify_identity(db: Session, request: DataPrincipalRequest, *, actor: str) -> DataPrincipalRequest:
    request.identity_verified_at = _now()
    request.status = "in_progress"
    request.assigned_to = request.assigned_to or actor
    db.commit()
    db.refresh(request)
    return request


def access_export(db: Session, tenant: TenantContext, request: DataPrincipalRequest) -> dict:
    """Right of access: a summary of the personal data held and what it's used for."""
    subject = _resolve_subject(db, tenant, request)
    if subject is None:
        return {"found": False}
    if isinstance(subject, Candidate):
        applications = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.candidate_id == subject.id).all()
        data = {"profile": {"full_name": subject.full_name, "email": subject.email, "phone": subject.phone, "location": subject.location,
                            "parsed_fields": subject.parsed_fields, "source": subject.source},
                "applications": [{"id": str(a.id), "status": a.status, "applied_at": a.created_at.isoformat() if a.created_at else None} for a in applications]}
    else:
        from app.core_hr import employees as employees_service
        from app.core_hr import lifecycle

        data = {"profile": employees_service.employee_to_dict(subject),
                "employment_history": [{"from": r.effective_from.isoformat(), "to": r.effective_to.isoformat() if r.effective_to else None, "designation": r.designation, "grade": r.grade}
                                       for r in lifecycle.employment_history(db, tenant, subject.id)]}
    consents = db.query(ConsentRecord).filter(ConsentRecord.tenant_id == tenant.tenant_id, (ConsentRecord.subject_id == subject.id) | (ConsentRecord.subject_email == request.subject_email)).all()
    data["consents"] = [{"purpose": c.purpose, "action": c.action, "at": c.recorded_at.isoformat() if c.recorded_at else None} for c in consents]
    data["processors"] = processors(db, tenant)
    return {"found": True, "data": data}


def _remove_file(directory_attr: str, relative: Optional[str]) -> bool:
    """Deletes an uploaded file as part of an APPROVED erasure/retention action only."""
    if not relative:
        return False
    from app.candidates import storage

    base = getattr(storage, directory_attr, None)
    if base is None:
        return False
    path = Path(base) / relative
    if path.exists() and path.is_file():
        path.unlink()
        return True
    return False


def anonymise_candidate(db: Session, candidate: Candidate) -> dict:
    removed = {"resume": _remove_file("UPLOAD_DIR", candidate.resume_path), "photo": _remove_file("PHOTO_UPLOAD_DIR", candidate.photo_path)}
    candidate.full_name = ERASED_NAME
    candidate.email = None
    candidate.phone = None
    candidate.location = None
    candidate.parsed_fields = {}
    candidate.custom_fields = {}
    candidate.resume_path = None
    candidate.photo_path = None
    db.commit()
    return {"anonymised": "candidate", "files_removed": removed}


_EMPLOYEE_NON_STATUTORY = ("personal_email", "personal_phone", "preferred_name", "pronouns", "marital_status", "blood_group")
_EMPLOYEE_NON_STATUTORY_JSON = ("addresses_json", "emergency_contacts_json", "family_json", "languages_json")


def pseudonymise_employee(db: Session, tenant: TenantContext, employee: Employee, *, full: bool) -> dict:
    """`full=False`: statutory-retention mode -- only non-statutory personal fields cleared.
    `full=True`: after the retention period -- names replaced and identity refs dropped too.
    Employment/compensation history rows are kept either way (aggregates and audit)."""
    for field in _EMPLOYEE_NON_STATUTORY:
        setattr(employee, field, None)
    for field in _EMPLOYEE_NON_STATUTORY_JSON:
        setattr(employee, field, [])
    cleared = list(_EMPLOYEE_NON_STATUTORY + _EMPLOYEE_NON_STATUTORY_JSON)
    if full:
        employee.first_name = ERASED_NAME
        employee.last_name = None
        employee.dob = None
        for ref in ("pan_secret_ref", "aadhaar_secret_ref", "passport_secret_ref", "visa_secret_ref", "driving_licence_secret_ref", "bank_account_secret_ref"):
            setattr(employee, ref, None)
        employee.aadhaar_last4 = None
        employee.custom_fields = {}
        cleared += ["names", "dob", "identity_documents", "bank_account", "custom_fields"]
    db.commit()
    return {"pseudonymised": "employee", "mode": "full" if full else "statutory_retention", "cleared": cleared}


def _employee_retention_ended(db: Session, tenant: TenantContext, employee: Employee) -> bool:
    days = int((_setting(db, tenant, "privacy.retention_days") or {}).get("ex_employee", 2920))
    last = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == employee.id, Separation.status == "completed").order_by(Separation.approved_lwd.desc()).first()
    return bool(last and last.approved_lwd and last.approved_lwd + timedelta(days=days) < _now().date())


def execute_erasure(db: Session, tenant: TenantContext, request: DataPrincipalRequest, *, actor: str) -> DataPrincipalRequest:
    if request.request_type != "erasure":
        raise PrivacyError("not an erasure request")
    if request.identity_verified_at is None:
        raise PrivacyError("verify the requester's identity first")
    if request.legal_hold:
        raise PrivacyError("this subject is under legal hold; erasure is refused")
    subject = _resolve_subject(db, tenant, request)
    if subject is None:
        outcome = {"found": False}
    elif isinstance(subject, Candidate):
        outcome = anonymise_candidate(db, subject)
    else:
        if subject.status in ("active", "on_notice", "pre_hire"):
            raise PrivacyError("a current employee's records are needed for employment; erase after separation")
        outcome = pseudonymise_employee(db, tenant, subject, full=_employee_retention_ended(db, tenant, subject))
        if outcome["mode"] == "statutory_retention":
            outcome["retained_reason"] = "employment records are retained for the statutory period; personal fields outside it were cleared"
    request.outcome_json = outcome
    request.status = "completed"
    request.resolution = request.resolution or f"erasure executed by {actor}"
    request.closed_at = _now()
    db.commit()
    db.refresh(request)
    return request


def close_request(db: Session, request: DataPrincipalRequest, *, actor: str, status: str, resolution: str, outcome: Optional[dict] = None) -> DataPrincipalRequest:
    if status not in ("completed", "rejected"):
        raise PrivacyError("close as completed or rejected")
    request.status, request.resolution, request.closed_at = status, resolution, _now()
    if outcome is not None:
        request.outcome_json = outcome
    request.assigned_to = request.assigned_to or actor
    db.commit()
    db.refresh(request)
    return request


def overdue_requests(db: Session, tenant: TenantContext) -> list[DataPrincipalRequest]:
    return db.query(DataPrincipalRequest).filter(DataPrincipalRequest.tenant_id == tenant.tenant_id, DataPrincipalRequest.status.in_(("received", "verifying", "in_progress")),
                                                 DataPrincipalRequest.due_at < _now()).all()


# ---- retention ----


def retention_dry_run(db: Session, tenant: TenantContext, category: str, *, actor: str, today: Optional[date] = None) -> RetentionRun:
    if category not in RETENTION_CATEGORIES:
        raise PrivacyError(f"category is one of {RETENTION_CATEGORIES}")
    today = today or _now().date()
    days = int((_setting(db, tenant, "privacy.retention_days") or {}).get(category, 0))
    if days <= 0:
        raise PrivacyError(f"no retention period configured for {category} (privacy.retention_days)")
    cutoff = today - timedelta(days=days)
    excluded: dict = {}
    if category == "candidate_unhired":
        hired = {a.candidate_id for a in db.query(Application.candidate_id).filter(Application.tenant_id == tenant.tenant_id, Application.status == "hired").all()}
        recent = {a.candidate_id for a in db.query(Application.candidate_id).filter(Application.tenant_id == tenant.tenant_id, Application.updated_at >= cutoff).all()}
        rows = db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.created_at < cutoff, Candidate.full_name != ERASED_NAME).all()
        ids = [str(c.id) for c in rows if c.id not in hired and c.id not in recent]
        excluded = {"hired": len(hired), "recent_activity": len(recent)}
    elif category == "ex_employee":
        seps = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status == "completed", Separation.approved_lwd < cutoff).all()
        ids = sorted({str(s.employee_id) for s in seps})
    else:
        ids = [str(c.id) for c in db.query(CopilotConversation).filter(CopilotConversation.tenant_id == tenant.tenant_id, CopilotConversation.created_at < cutoff).all()]
    run = RetentionRun(tenant_id=tenant.tenant_id, category=category, cutoff=cutoff, report_json={"ids": ids, "count": len(ids), "excluded": excluded, "retention_days": days},
                       requested_by=actor)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def approve_retention_run(db: Session, run: RetentionRun, *, actor: str, approve: bool) -> RetentionRun:
    if run.status != "dry_run":
        raise PrivacyError(f"run is already {run.status}")
    if approve and actor == run.requested_by:
        raise PrivacyError("a different person must approve a purge than the one who requested it")
    run.status = "approved" if approve else "rejected"
    run.approved_by = actor
    db.commit()
    db.refresh(run)
    return run


def execute_retention_run(db: Session, tenant: TenantContext, run: RetentionRun) -> dict:
    """Applies exactly the ids in the approved report -- never re-queries, so what was
    approved is what happens."""
    if run.status != "approved":
        raise PrivacyError("only an approved run can be executed")
    done = 0
    for raw_id in run.report_json.get("ids", []):
        row_id = UUID(raw_id)
        if run.category == "candidate_unhired":
            candidate = db.get(Candidate, row_id)
            if candidate is not None and candidate.full_name != ERASED_NAME:
                anonymise_candidate(db, candidate)
                done += 1
        elif run.category == "ex_employee":
            employee = db.get(Employee, row_id)
            if employee is not None:
                pseudonymise_employee(db, tenant, employee, full=True)
                done += 1
        else:
            for message in db.query(CopilotMessage).filter(CopilotMessage.tenant_id == tenant.tenant_id, CopilotMessage.conversation_id == row_id).all():
                message.content = "[purged]"
                message.tool_calls_json = []
            done += 1
    run.status = "executed"
    run.executed_at = _now()
    db.commit()
    return {"run_id": str(run.id), "processed": done}


# ---- breach register ----


def report_breach(db: Session, tenant: TenantContext, *, title: str, description: str, severity: str, detected_at: datetime,
                  data_categories: list[str], affected_count: Optional[int], actor: str) -> BreachIncident:
    row = BreachIncident(tenant_id=tenant.tenant_id, title=title, description=description, severity=severity, detected_at=detected_at,
                         data_categories_json=data_categories, affected_count=affected_count, reported_by=actor,
                         actions_json=[{"at": _now().isoformat(), "by": actor, "action": "reported"}])
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, "privacy.breach_reported", {"breach_id": str(row.id), "severity": severity, "title": title})
    return row


def breach_action(db: Session, tenant: TenantContext, incident: BreachIncident, *, action: str, actor: str, note: Optional[str] = None) -> BreachIncident:
    """action: contain | notify_board | notify_principals | close. Notifications go through
    comms templates (event `privacy.breach_<action>`) the tenant configures."""
    now = _now()
    if action == "contain":
        incident.status = "contained"
    elif action == "notify_board":
        incident.board_notified_at = now
        incident.status = "notified"
    elif action == "notify_principals":
        incident.principals_notified_at = now
        incident.status = "notified"
    elif action == "close":
        if incident.board_notified_at is None and incident.severity in ("high", "critical"):
            raise PrivacyError("a high/critical breach must be notified to the Board before it can be closed")
        incident.status = "closed"
    else:
        raise PrivacyError("unknown action")
    incident.actions_json = [*(incident.actions_json or []), {"at": now.isoformat(), "by": actor, "action": action, "note": note}]
    db.commit()
    db.refresh(incident)
    if action.startswith("notify"):
        from app.platform.comms.service import dispatch_event

        dispatch_event(db, tenant, f"privacy.breach_{action}", {"breach_id": str(incident.id), "title": incident.title, "affected_count": incident.affected_count})
    return incident
