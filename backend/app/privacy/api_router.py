"""Privacy & security admin API (docs/HRMS_COMPLETE_SPEC.txt Part 13 sections D-E):
notices, consent ledger, data principal requests, retention runs (dry-run -> approve ->
execute, two different people), breach register, audit export. Plus the public endpoints a
data principal uses: the privacy notice (with the auto-derived processor list) and
raising a request."""

import csv
import io
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.privacy import BreachIncident, ConsentRecord, DataPrincipalRequest, RetentionRun
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant
from app.privacy import service

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])
public_router = APIRouter(prefix="/api/v1/public/privacy", tags=["privacy-public"])


def _get(db: Session, model, row_id: UUID, label: str):
    tenant = require_current_tenant()
    row = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.id == row_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---- public ----


@public_router.get("/notice/{purpose}")
def public_notice(purpose: str, language: str = "en", db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    notice = service.current_notice(db, tenant, purpose, language)
    return {"purpose": purpose, "version": notice.version if notice else None, "title": notice.title if notice else None,
            "body": notice.body if notice else None, "processors": service.processors(db, tenant)}


class PublicRequest(BaseModel):
    request_type: str
    subject_type: str = "candidate"
    email: str
    details: Optional[str] = None


@public_router.post("/requests", status_code=202)
def public_request(payload: PublicRequest, db: Session = Depends(get_db)):
    """Always 202 with the same body -- whether or not we hold data for that email is only
    revealed after identity verification."""
    if payload.request_type not in ("access", "correction", "erasure", "grievance", "nomination") or payload.subject_type not in ("candidate", "employee", "other"):
        raise HTTPException(status_code=400, detail="Unknown request type")
    service.create_request(db, require_current_tenant(), request_type=payload.request_type, subject_type=payload.subject_type,
                           subject_email=payload.email, details=payload.details)
    return {"status": "received", "message": "We've received your request and will contact you at this email to verify your identity."}


# ---- notices + consent ----


class NoticePublish(BaseModel):
    purpose: str
    title: str
    body: str
    language: str = "en"


@router.post("/notices", status_code=201)
def publish_notice(payload: NoticePublish, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.notice.configure"))):
    notice = service.publish_notice(db, require_current_tenant(), actor=current_user.email, **payload.model_dump())
    return {"id": str(notice.id), "version": notice.version}


@router.get("/consents")
def consent_ledger(subject_email: Optional[str] = None, purpose: Optional[str] = None, db: Session = Depends(get_db),
                   current_user: User = Depends(require("privacy.consent.view"))):
    tenant = require_current_tenant()
    query = db.query(ConsentRecord).filter(ConsentRecord.tenant_id == tenant.tenant_id)
    if subject_email:
        query = query.filter(ConsentRecord.subject_email == subject_email.lower())
    if purpose:
        query = query.filter(ConsentRecord.purpose == purpose)
    return [{"subject_type": c.subject_type, "subject_email": c.subject_email, "purpose": c.purpose, "action": c.action,
             "notice_version": c.notice_version, "channel": c.channel, "at": c.recorded_at.isoformat() if c.recorded_at else None}
            for c in query.order_by(ConsentRecord.recorded_at.desc()).limit(500).all()]


# ---- data principal requests ----


def _dpr_dict(r: DataPrincipalRequest) -> dict:
    return {"id": str(r.id), "type": r.request_type, "subject_type": r.subject_type, "subject_email": r.subject_email, "status": r.status,
            "due_at": r.due_at.isoformat(), "identity_verified": r.identity_verified_at is not None, "legal_hold": r.legal_hold,
            "assigned_to": r.assigned_to, "resolution": r.resolution, "outcome": r.outcome_json}


@router.get("/requests")
def list_requests(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.view"))):
    tenant = require_current_tenant()
    query = db.query(DataPrincipalRequest).filter(DataPrincipalRequest.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(DataPrincipalRequest.status == status)
    return [_dpr_dict(r) for r in query.order_by(DataPrincipalRequest.due_at.asc()).all()]


@router.post("/requests/{request_id}/verify")
def verify_request(request_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.edit"))):
    return _dpr_dict(service.verify_identity(db, _get(db, DataPrincipalRequest, request_id, "Request"), actor=current_user.email))


class LegalHold(BaseModel):
    legal_hold: bool


@router.post("/requests/{request_id}/legal-hold")
def legal_hold(request_id: UUID, payload: LegalHold, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.approve"))):
    row = _get(db, DataPrincipalRequest, request_id, "Request")
    row.legal_hold = payload.legal_hold
    db.commit()
    return _dpr_dict(row)


@router.get("/requests/{request_id}/access-export")
def access_export(request_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.edit"))):
    row = _get(db, DataPrincipalRequest, request_id, "Request")
    if row.identity_verified_at is None:
        raise HTTPException(status_code=409, detail="Verify the requester's identity first")
    return service.access_export(db, require_current_tenant(), row)


@router.post("/requests/{request_id}/erase")
def erase(request_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.approve"))):
    try:
        return _dpr_dict(service.execute_erasure(db, require_current_tenant(), _get(db, DataPrincipalRequest, request_id, "Request"), actor=current_user.email))
    except service.PrivacyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class CloseRequest(BaseModel):
    status: str
    resolution: str
    outcome: Optional[dict] = None


@router.post("/requests/{request_id}/close")
def close_request(request_id: UUID, payload: CloseRequest, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.request.edit"))):
    try:
        return _dpr_dict(service.close_request(db, _get(db, DataPrincipalRequest, request_id, "Request"), actor=current_user.email, **payload.model_dump()))
    except service.PrivacyError as exc:
        raise _bad(exc)


# ---- retention ----


class RetentionDryRun(BaseModel):
    category: str


def _run_dict(r: RetentionRun) -> dict:
    return {"id": str(r.id), "category": r.category, "cutoff": r.cutoff.isoformat(), "count": r.report_json.get("count"), "excluded": r.report_json.get("excluded"),
            "status": r.status, "requested_by": r.requested_by, "approved_by": r.approved_by}


@router.post("/retention/dry-run", status_code=201)
def retention_dry_run(payload: RetentionDryRun, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.retention.create"))):
    try:
        return _run_dict(service.retention_dry_run(db, require_current_tenant(), payload.category, actor=current_user.email))
    except service.PrivacyError as exc:
        raise _bad(exc)


class RetentionDecision(BaseModel):
    approve: bool


@router.post("/retention/{run_id}/decision")
def retention_decide(run_id: UUID, payload: RetentionDecision, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.retention.approve"))):
    try:
        return _run_dict(service.approve_retention_run(db, _get(db, RetentionRun, run_id, "Run"), actor=current_user.email, approve=payload.approve))
    except service.PrivacyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/retention/{run_id}/execute")
def retention_execute(run_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.retention.approve"))):
    try:
        return service.execute_retention_run(db, require_current_tenant(), _get(db, RetentionRun, run_id, "Run"))
    except service.PrivacyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---- breaches ----


class BreachReport(BaseModel):
    title: str
    description: str
    severity: str
    detected_at: datetime
    data_categories: list[str] = []
    affected_count: Optional[int] = None


@router.post("/breaches", status_code=201)
def report_breach(payload: BreachReport, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.breach.create"))):
    if payload.severity not in ("low", "medium", "high", "critical"):
        raise HTTPException(status_code=400, detail="severity is low, medium, high or critical")
    row = service.report_breach(db, require_current_tenant(), actor=current_user.email, **payload.model_dump())
    return {"id": str(row.id), "status": row.status}


@router.get("/breaches")
def list_breaches(db: Session = Depends(get_db), current_user: User = Depends(require("privacy.breach.view"))):
    tenant = require_current_tenant()
    return [{"id": str(b.id), "title": b.title, "severity": b.severity, "status": b.status, "detected_at": b.detected_at.isoformat(),
             "affected_count": b.affected_count, "board_notified_at": b.board_notified_at.isoformat() if b.board_notified_at else None, "actions": b.actions_json}
            for b in db.query(BreachIncident).filter(BreachIncident.tenant_id == tenant.tenant_id).order_by(BreachIncident.detected_at.desc()).all()]


class BreachAction(BaseModel):
    action: str
    note: Optional[str] = None


@router.post("/breaches/{breach_id}/actions")
def breach_action(breach_id: UUID, payload: BreachAction, db: Session = Depends(get_db), current_user: User = Depends(require("privacy.breach.edit"))):
    try:
        row = service.breach_action(db, require_current_tenant(), _get(db, BreachIncident, breach_id, "Incident"), actor=current_user.email, **payload.model_dump())
    except service.PrivacyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"id": str(row.id), "status": row.status}


# ---- audit export (section D) ----


@router.get("/audit-export")
def audit_export(since: Optional[datetime] = None, until: Optional[datetime] = None, db: Session = Depends(get_db),
                 current_user: User = Depends(require("security.audit.export"))):
    query = db.query(AuditLog)
    if since:
        query = query.filter(AuditLog.created_at >= since)
    if until:
        query = query.filter(AuditLog.created_at <= until)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["created_at", "entity_type", "entity_id", "action", "actor", "details"])
    for row in query.order_by(AuditLog.created_at.asc()).limit(100_000).all():
        writer.writerow([row.created_at.isoformat() if row.created_at else "", row.entity_type, row.entity_id, row.action, row.actor, row.details])
    return Response(content=out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit_export.csv"'})
