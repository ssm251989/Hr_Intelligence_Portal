"""Part 15 step 15.4 (L B1-B8, K H3-H5): read-only helpers the restyled Salary / BGV /
Offers pages need that the original endpoints don't return -- no new tables, no changes to
how any stage moves forward.

- GET  /api/v1/ui/offers/context                          currency + offer expiry days (B7)
- GET  /api/v1/ui/offers/applications/{id}/offer-timeline offer sent -> viewed -> signed (B8),
                                                           expiry (B7), approval steps (H4)
- GET  /api/v1/ui/offers/applications/{id}/bgv-timeline   document + vendor updates (B5)
- GET  /api/v1/ui/offers/template                         latest offer letter template (B6)
- POST /api/v1/ui/offers/template/preview                 live preview of unsaved text (B6)
- POST /api/v1/ui/offers/template                         save (+ publish) the offer template
fix 2026-10-05 (app/offers/revisions.py):
- GET  /api/v1/ui/offers/applications/{id}/offer-versions  status, sent n times, history, pending revision
- POST /api/v1/ui/offers/applications/{id}/offer/resend    same offer, reminder email (15 min cooldown)
- POST /api/v1/ui/offers/applications/{id}/offer/revise    revised offer (v2, v3...), approval when above the limit
- POST /api/v1/ui/offers/applications/{id}/offer/revisions/{version_id}/decide   approve / reject a waiting revision
- GET  /api/v1/ui/offers/applications/{id}/offer/versions/{n}/pdf               any version's PDF

Templates are the Part 7 `letter_templates` rows with key "offer", rendered through the same
sandboxed Jinja renderer (`platform.comms.renderer.render_string`) every letter/email uses.
Every read is tenant-scoped by the TenantOwned ORM filter plus an explicit tenant_id check.
"""

from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/offers", tags=["ui-offers"])

DEFAULT_EXPIRY_DAYS = 7
OFFER_TEMPLATE_KEY = "offer"

DEFAULT_TEMPLATE = """<p>Dear {{ candidate_name }},</p>
<p>We are delighted to offer you the role of <strong>{{ job_title }}</strong> at {{ org.display_name }}.</p>
<p>Your yearly salary (CTC) will be <strong>{{ salary }}</strong>. Your first day is {{ start_date }},
and you will report to {{ reporting_manager }}.</p>
<p>Please sign this letter by {{ expiry_date }} to accept the offer.</p>
<p>We look forward to welcoming you.</p>
<p>Warm regards,<br>{{ org.display_name }}</p>
"""

SAMPLE_CONTEXT = {
    "candidate_name": "Priya Sharma",
    "job_title": "Senior Analyst",
    "salary": "12,00,000",
    "start_date": "1 November",
    "reporting_manager": "Arun Kumar",
    "expiry_date": "7 days from sending",
}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _setting(db: Session, key: str, default: Any) -> Any:
    try:
        from app.platform.settings.resolver import SettingContext, SettingsService

        value = SettingsService(db).get(key, SettingContext(tenant=require_current_tenant()))
        return default if value in (None, "") else value
    except Exception:  # unknown key / settings not seeded -- the documented default applies
        return default


def _expiry_days(db: Session) -> int:
    try:
        return int(_setting(db, "recruitment.offer.expiry_days", DEFAULT_EXPIRY_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_EXPIRY_DAYS


def _application_or_404(db: Session, application_id: UUID) -> Application:
    tenant = require_current_tenant()
    application = db.get(Application, application_id)
    if application is None or getattr(application, "tenant_id", tenant.tenant_id) != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="We couldn't find that application.")
    return application


def _audit(db: Session, entity_type: str, entity_ids: list, actions: tuple) -> list[AuditLog]:
    if not entity_ids:
        return []
    return (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == entity_type, AuditLog.entity_id.in_(entity_ids), AuditLog.action.in_(actions))
        .order_by(AuditLog.created_at)
        .all()
    )


@router.get("/context")
def ui_context(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"currency": _setting(db, "org.currency", None), "offer_expiry_days": _expiry_days(db)}


# ---- offers: timeline, expiry, approval steps ----

_OFFER_ACTIONS = (
    "ai_offer_letter_generated", "offer_sent", "offer_sent_for_signing", "offer_viewed", "docusign_envelope_viewed",
    "docusign_envelope_creation_failed", "offer_signed", "onboarding_completed", "offer_resent", "offer_revised",
)
_KIND = {
    "ai_offer_letter_generated": "sent", "offer_sent": "sent", "offer_sent_for_signing": "sent", "offer_viewed": "viewed",
    "docusign_envelope_viewed": "viewed", "docusign_envelope_creation_failed": "esign_failed",
    "offer_signed": "signed", "onboarding_completed": "joined", "offer_resent": "resent", "offer_revised": "revised",
}


def _approval_steps(db: Session, entity_ids: list) -> list[dict]:
    from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep

    tenant = require_current_tenant()
    rows = (
        db.query(WorkflowStep, WorkflowInstance, WorkflowDefinition)
        .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
        .filter(WorkflowInstance.tenant_id == tenant.tenant_id, WorkflowInstance.entity_id.in_(entity_ids), WorkflowStep.node_type == "approval")
        .order_by(WorkflowStep.started_at)
        .all()
    )
    return [
        {
            "id": str(step.id), "name": definition.name, "step": step.node_id, "status": step.status, "action": step.action,
            "acted_by": step.acted_by, "comment": step.comment, "started_at": _iso(step.started_at), "ended_at": _iso(step.ended_at),
            "due_at": _iso(step.due_at),
        }
        for step, _instance, definition in rows
    ]


@router.get("/applications/{application_id}/offer-timeline")
def offer_timeline(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.offer import Offer

    application = _application_or_404(db, application_id)
    offer = db.query(Offer).filter(Offer.application_id == application.id).one_or_none()
    days = _expiry_days(db)
    events = [
        {"kind": _KIND[row.action], "action": row.action, "at": _iso(row.created_at), "by": row.actor}
        for row in _audit(db, "application", [application.id], _OFFER_ACTIONS)
    ]
    offer_info = None
    if offer is not None:
        sent_at = next((e["at"] for e in events if e["kind"] == "sent"), None) or _iso(offer.created_at)
        expiry: Optional[date] = offer.expiry_date
        is_default = expiry is None
        if expiry is None and offer.created_at is not None:
            base = datetime.fromisoformat(sent_at) if sent_at else offer.created_at
            expiry = (base + timedelta(days=days)).date()
        offer_info = {
            "id": str(offer.id), "created_at": _iso(offer.created_at), "sent_at": sent_at, "signed": bool(offer.signed),
            "expiry_date": _iso(expiry), "expiry_is_default": is_default, "joining_date": _iso(offer.joining_date),
            "esign": "docusign" if offer.docusign_sender_id else ("manual" if offer.docusign_envelope_id else None),
        }
    ids = [application.id] + ([offer.id] if offer is not None else [])
    return {"offer": offer_info, "events": events, "approvals": _approval_steps(db, ids), "expiry_days": days}


# ---- BGV: document + vendor timeline ----

_BGV_APP_ACTIONS = ("bgv_requested", "bgv_clearance_decision")
_BGV_DOC_ACTIONS = ("bgv_document_uploaded", "ai_document_validator_scored")


@router.get("/applications/{application_id}/bgv-timeline")
def bgv_timeline(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.bgv_document import BgvDocument
    from app.models.onboarding import BgvCase

    application = _application_or_404(db, application_id)
    tenant = require_current_tenant()
    events: list[dict] = []
    for row in _audit(db, "application", [application.id], _BGV_APP_ACTIONS):
        details = row.details or {}
        events.append({"kind": row.action, "at": _iso(row.created_at), "by": row.actor, "decision": details.get("decision")})
    doc_ids = [d.id for d in db.query(BgvDocument).filter(BgvDocument.application_id == application.id).all()]
    for row in _audit(db, "bgv_document", doc_ids, _BGV_DOC_ACTIONS):
        details = row.details or {}
        events.append({
            "kind": row.action, "at": _iso(row.created_at), "by": row.actor, "doc_id": str(row.entity_id),
            "doc_type": details.get("doc_type") or details.get("doc_type_detected"), "result": details.get("validation_status"),
        })

    subject_ids = [application.id] + ([application.candidate_id] if application.candidate_id else [])
    cases = (
        db.query(BgvCase)
        .filter(BgvCase.tenant_id == tenant.tenant_id, BgvCase.subject_type == "candidate", BgvCase.subject_id.in_(subject_ids))
        .order_by(BgvCase.created_at)
        .all()
    )
    vendor = []
    for case in cases:
        steps = [("vendor_created", case.created_at), ("vendor_consent", case.consent_at), ("vendor_started", case.initiated_at),
                 ("vendor_completed", case.completed_at), ("vendor_decided", case.decided_at)]
        for kind, at in steps:
            if at is not None:
                events.append({"kind": kind, "at": _iso(at), "by": case.decided_by if kind == "vendor_decided" else None,
                               "decision": case.decision if kind == "vendor_decided" else None, "case_id": str(case.id)})
        vendor.append({
            "id": str(case.id), "status": case.status, "decision": case.decision, "discrepancy": case.discrepancy,
            "checks": [{"type": c.get("type"), "status": c.get("status"), "notes": c.get("notes")} for c in (case.checks_json or [])],
        })
    events.sort(key=lambda e: e["at"] or "")
    return {"events": events, "vendor_cases": vendor}


# ---- offer letter template: load / live preview / save ----


class PreviewRequest(BaseModel):
    html_tpl: str
    sample_context: dict[str, Any] = {}


class TemplateSave(BaseModel):
    html_tpl: str
    name: str = "Offer letter"
    publish: bool = True


def _latest_template(db: Session):
    from app.models.core_hr import LetterTemplate

    tenant = require_current_tenant()
    return (
        db.query(LetterTemplate)
        .filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == OFFER_TEMPLATE_KEY)
        .order_by(LetterTemplate.version.desc())
        .first()
    )


@router.get("/template")
def get_offer_template(db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    template = _latest_template(db)
    if template is None:
        return {"id": None, "version": 0, "status": "default", "name": "Offer letter", "html_tpl": DEFAULT_TEMPLATE,
                "sample_context": SAMPLE_CONTEXT}
    return {"id": str(template.id), "version": template.version, "status": template.status, "name": template.name,
            "html_tpl": template.html_tpl, "sample_context": SAMPLE_CONTEXT}


@router.post("/template/preview")
def preview_offer_template(payload: PreviewRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    """Renders UNSAVED text so the editor's right-hand preview updates while typing. A
    template mistake comes back as {"error": ...} (200) -- it's expected mid-edit."""
    from app.platform.comms.renderer import TemplateRenderError, render_string
    from app.platform.comms.theme import get_theme_and_org_context

    if len(payload.html_tpl) > 50_000:
        raise HTTPException(status_code=413, detail="This letter is too long to preview. Please shorten it.")
    ctx = {**SAMPLE_CONTEXT, **get_theme_and_org_context(db, require_current_tenant()), **payload.sample_context}
    try:
        return {"html": render_string(payload.html_tpl, ctx), "error": None}
    except TemplateRenderError as exc:
        return {"html": None, "error": str(exc)}


@router.post("/template", status_code=201)
def save_offer_template(payload: TemplateSave, db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.letter.create"))):
    from app.audit.service import log_action
    from app.core_hr import letters as letters_service
    from app.platform.comms.renderer import TemplateRenderError

    tenant = require_current_tenant()
    template = letters_service.create_draft(db, tenant, key=OFFER_TEMPLATE_KEY, name=payload.name, html_tpl=payload.html_tpl)
    if payload.publish:
        try:
            template = letters_service.publish(db, template)
        except TemplateRenderError as exc:
            raise HTTPException(status_code=400, detail=f"Saved as a draft, but it can't be used yet: {exc}")
    log_action(db, "letter_template", template.id, "offer_template_saved", current_user.email, {"version": template.version, "status": template.status})
    return {"id": str(template.id), "version": template.version, "status": template.status}


# ---- fix 2026-10-05: resend for signature + revised offer ----


def _offer_or_404(db: Session, application_id: UUID):
    from app.models.offer import Offer

    _application_or_404(db, application_id)
    offer = db.query(Offer).filter(Offer.application_id == application_id).one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer for this candidate yet.")
    return offer


@router.get("/applications/{application_id}/offer-versions")
def offer_versions(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.offers import revisions

    return revisions.summary(db, require_current_tenant(), _offer_or_404(db, application_id), current_user)


@router.post("/applications/{application_id}/offer/resend")
def offer_resend(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "admin"))):
    from app.offers import revisions

    offer = _offer_or_404(db, application_id)
    try:
        out = revisions.resend(db, require_current_tenant(), offer, actor=current_user.email)
    except revisions.CooldownError as exc:
        raise HTTPException(status_code=429, detail={"code": "RESEND_COOLDOWN", "message": str(exc), "wait_minutes": exc.wait_minutes}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**out, "summary": revisions.summary(db, require_current_tenant(), offer, current_user)}


class OfferComponentIn(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    amount: float


class OfferReviseIn(BaseModel):
    ctc_total: Optional[float] = None
    components: Optional[list[OfferComponentIn]] = None
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    work_location: Optional[str] = None
    terms: Optional[str] = None
    reason_code: str
    reason_note: Optional[str] = None


@router.post("/applications/{application_id}/offer/revise")
def offer_revise(application_id: UUID, payload: OfferReviseIn, db: Session = Depends(get_db),
                 current_user: User = Depends(require_roles("recruiter", "admin"))):
    from app.offers import revisions

    offer = _offer_or_404(db, application_id)
    data = payload.model_dump()
    if payload.components is not None:
        data["components"] = [c.model_dump() for c in payload.components]
    try:
        out = revisions.revise(db, require_current_tenant(), offer, data, actor=current_user.email, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**out, "summary": revisions.summary(db, require_current_tenant(), offer, current_user)}


class RevisionDecisionIn(BaseModel):
    approve: bool
    note: Optional[str] = None


@router.post("/applications/{application_id}/offer/revisions/{version_id}/decide")
def offer_revision_decide(application_id: UUID, version_id: UUID, payload: RevisionDecisionIn, db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    from app.offers import revisions

    offer = _offer_or_404(db, application_id)
    try:
        out = revisions.decide(db, require_current_tenant(), offer, version_id, approve=payload.approve, user=current_user, note=payload.note)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**out, "summary": revisions.summary(db, require_current_tenant(), offer, current_user)}


@router.get("/applications/{application_id}/offer/versions/{version_no}/pdf")
def offer_version_pdf(application_id: UUID, version_no: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from fastapi.responses import Response

    from app.offers import revisions

    offer = _offer_or_404(db, application_id)
    data = revisions.version_pdf(db, require_current_tenant(), offer, version_no)
    if data is None:
        raise HTTPException(status_code=404, detail="No such version.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="offer-letter-v{version_no}.pdf"'})
