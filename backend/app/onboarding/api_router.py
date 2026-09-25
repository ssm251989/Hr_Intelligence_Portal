"""Pre-boarding & onboarding API (docs/HRMS_COMPLETE_SPEC.txt Part 9). HR endpoints are
gated by `authz.require("onboarding.*")`; the new-hire portal and the BGV vendor webhook
are public routes authenticated by their own opaque tokens (portal_token / webhook_token),
never by an app session.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.onboarding import BgvCase, OnboardingPlan, OnboardingPlanTemplate, OnboardingTask, PreboardingCase, PreboardingDocument, AssignmentRule
from app.models.user import User
from app.onboarding import assignment_rules, bgv, conversion, dashboard, plans
from app.onboarding.portal import PortalAuthError, PortalValidationError, PreboardingPortal, case_to_dict
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])
public_router = APIRouter(prefix="/api/v1/public/onboarding", tags=["onboarding-public"])


def _case_or_404(db: Session, case_id: UUID) -> PreboardingCase:
    tenant = require_current_tenant()
    case = db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Pre-boarding case not found")
    return case


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---- pre-boarding cases (HR) ----


class CaseCreate(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    joining_date: Optional[date] = None
    offer_id: Optional[UUID] = None
    attributes: dict = {}
    welcome_content: dict = {}


@router.get("/cases")
def list_cases(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    tenant = require_current_tenant()
    query = db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(PreboardingCase.status == status)
    return [case_to_dict(c) for c in query.order_by(PreboardingCase.joining_date.asc()).all()]


@router.post("/cases", status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.create"))):
    portal = PreboardingPortal(db, require_current_tenant())
    try:
        if payload.offer_id:
            case = portal.create_case_from_offer(payload.offer_id, joining_date=payload.joining_date, attributes=payload.attributes, created_by=current_user.email)
            if payload.welcome_content:
                case.welcome_content_json = payload.welcome_content
                db.commit()
        else:
            if not (payload.email and payload.first_name and payload.joining_date):
                raise PortalValidationError("email, first_name and joining_date are required without an offer_id")
            case = portal.create_case(
                email=payload.email, first_name=payload.first_name, last_name=payload.last_name, joining_date=payload.joining_date,
                attributes=payload.attributes, welcome_content=payload.welcome_content, created_by=current_user.email,
            )
    except PortalValidationError as exc:
        raise _bad_request(exc)
    # The portal token is returned exactly once, to the HR user who creates the case (to
    # send via the comms template of their choice); it is never listed again.
    return {**case_to_dict(case), "portal_token": case.portal_token}


@router.get("/cases/{case_id}")
def get_case(case_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    case = _case_or_404(db, case_id)
    portal = PreboardingPortal(db, require_current_tenant())
    return {
        **case_to_dict(case), "readiness": portal.readiness(case), "form_submissions": case.form_submissions_json or {},
        "documents": [
            {"id": str(d.id), "document_type": d.document_type_code, "status": d.verification_status,
             "extracted": d.extracted_json, "verified_by": d.verified_by, "rejection_reason": d.rejection_reason}
            for d in portal.documents(case)
        ],
    }


@router.post("/cases/{case_id}/rotate-token")
def rotate_token(case_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    case = PreboardingPortal(db, require_current_tenant()).rotate_token(_case_or_404(db, case_id))
    log_action(db, "preboarding_case", case.id, "portal_token_rotated", current_user.email)
    return {"portal_token": case.portal_token, "expires_at": case.portal_token_expires_at.isoformat()}


class JoiningDateChange(BaseModel):
    joining_date: date
    reason: Optional[str] = None


@router.post("/cases/{case_id}/joining-date")
def change_joining_date(case_id: UUID, payload: JoiningDateChange, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    case = PreboardingPortal(db, require_current_tenant()).change_joining_date(_case_or_404(db, case_id), payload.joining_date, actor=current_user.email, reason=payload.reason)
    return case_to_dict(case)


class CloseCase(BaseModel):
    reason: Optional[str] = None


@router.post("/cases/{case_id}/no-show")
def mark_no_show(case_id: UUID, payload: CloseCase, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    try:
        case = PreboardingPortal(db, require_current_tenant()).mark_no_show(_case_or_404(db, case_id), actor=current_user.email, reason=payload.reason)
    except PortalValidationError as exc:
        raise _bad_request(exc)
    return case_to_dict(case)


@router.post("/cases/{case_id}/revoke")
def revoke_offer(case_id: UUID, payload: CloseCase, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    try:
        case = PreboardingPortal(db, require_current_tenant()).revoke_offer(_case_or_404(db, case_id), actor=current_user.email, reason=payload.reason)
    except PortalValidationError as exc:
        raise _bad_request(exc)
    return case_to_dict(case)


class ConvertRequest(BaseModel):
    confirm_joined: bool


@router.post("/cases/{case_id}/convert")
def convert_case(case_id: UUID, payload: ConvertRequest, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.approve"))):
    if not payload.confirm_joined:
        raise HTTPException(status_code=400, detail="Confirm the new hire has actually joined before converting")
    try:
        return conversion.convert(db, require_current_tenant(), _case_or_404(db, case_id), actor=current_user.email)
    except conversion.ConversionError as exc:
        raise _bad_request(exc)


# ---- document verification queue (HR) ----


@router.get("/documents/pending")
def pending_documents(db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    tenant = require_current_tenant()
    rows = (
        db.query(PreboardingDocument)
        .filter(PreboardingDocument.tenant_id == tenant.tenant_id, PreboardingDocument.verification_status == "pending")
        .order_by(PreboardingDocument.uploaded_at.asc())
        .all()
    )
    return [{"id": str(d.id), "case_id": str(d.case_id), "document_type": d.document_type_code, "extracted": d.extracted_json} for d in rows]


class DocumentVerify(BaseModel):
    approve: bool
    reason: Optional[str] = None


@router.post("/documents/{document_id}/verify")
def verify_document(document_id: UUID, payload: DocumentVerify, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    tenant = require_current_tenant()
    document = db.query(PreboardingDocument).filter(PreboardingDocument.tenant_id == tenant.tenant_id, PreboardingDocument.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not payload.approve and not payload.reason:
        raise HTTPException(status_code=400, detail="A rejection needs a reason the new hire can act on")
    document = PreboardingPortal(db, tenant).verify_document(document, actor=current_user.email, approve=payload.approve, reason=payload.reason)
    return {"id": str(document.id), "status": document.verification_status}


# ---- plan templates / plans / tasks ----


class PlanTemplateUpsert(BaseModel):
    code: str
    name: str
    tasks: list[dict]


@router.get("/plan-templates")
def list_plan_templates(db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.plan.view"))):
    tenant = require_current_tenant()
    rows = db.query(OnboardingPlanTemplate).filter(OnboardingPlanTemplate.tenant_id == tenant.tenant_id).order_by(OnboardingPlanTemplate.code).all()
    return [{"id": str(t.id), "code": t.code, "name": t.name, "tasks": t.tasks_json, "is_active": t.is_active} for t in rows]


@router.put("/plan-templates")
def upsert_plan_template(payload: PlanTemplateUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.plan.configure"))):
    try:
        template = plans.upsert_template(db, require_current_tenant(), code=payload.code, name=payload.name, tasks=payload.tasks)
    except plans.InvalidPlanTemplateError as exc:
        raise _bad_request(exc)
    return {"id": str(template.id), "code": template.code, "name": template.name, "tasks": template.tasks_json}


class PlanGenerate(BaseModel):
    template_code: str


@router.post("/cases/{case_id}/plan", status_code=201)
def generate_plan(case_id: UUID, payload: PlanGenerate, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.plan.create"))):
    tenant = require_current_tenant()
    template = plans.get_template(db, tenant, payload.template_code)
    if template is None:
        raise HTTPException(status_code=404, detail="Plan template not found")
    plan = plans.generate_plan(db, tenant, _case_or_404(db, case_id), template)
    return {"plan_id": str(plan.id), "tasks": [plans.task_to_dict(t) for t in plans.plan_tasks(db, tenant, plan.id)]}


@router.get("/cases/{case_id}/plan")
def get_plan(case_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.plan.view"))):
    tenant = require_current_tenant()
    plan = db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == tenant.tenant_id, OnboardingPlan.case_id == _case_or_404(db, case_id).id).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan generated for this case yet")
    return {"plan_id": str(plan.id), "template_code": plan.template_code, "tasks": [plans.task_to_dict(t) for t in plans.plan_tasks(db, tenant, plan.id)]}


class TaskComplete(BaseModel):
    response: Optional[dict] = None
    skip: bool = False


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: UUID, payload: TaskComplete, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.task.edit"))):
    tenant = require_current_tenant()
    task = db.query(OnboardingTask).filter(OnboardingTask.tenant_id == tenant.tenant_id, OnboardingTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        task = plans.complete_task(db, tenant, task, actor=current_user.email, response=payload.response, skip=payload.skip)
    except plans.TaskBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return plans.task_to_dict(task)


@router.get("/tasks/overdue")
def overdue_tasks(db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.task.view"))):
    return [plans.task_to_dict(t) for t in plans.overdue_tasks(db, require_current_tenant())]


# ---- assignment rules ----


class AssignmentRuleCreate(BaseModel):
    name: str
    target_type: str
    target_ref: str
    condition_jsonlogic: Optional[dict] = None
    priority: int = 100


def _rule_dict(r: AssignmentRule) -> dict:
    return {"id": str(r.id), "name": r.name, "target_type": r.target_type, "target_ref": r.target_ref,
            "condition_jsonlogic": r.condition_jsonlogic, "priority": r.priority, "is_active": r.is_active}


@router.get("/assignment-rules")
def list_assignment_rules(db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.assignment_rule.view"))):
    tenant = require_current_tenant()
    rows = db.query(AssignmentRule).filter(AssignmentRule.tenant_id == tenant.tenant_id).order_by(AssignmentRule.target_type, AssignmentRule.priority).all()
    return [_rule_dict(r) for r in rows]


@router.post("/assignment-rules", status_code=201)
def create_assignment_rule(payload: AssignmentRuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.assignment_rule.configure"))):
    try:
        rule = assignment_rules.create_rule(db, require_current_tenant(), **payload.model_dump())
    except assignment_rules.InvalidAssignmentRuleError as exc:
        raise _bad_request(exc)
    return _rule_dict(rule)


class AssignmentPreview(BaseModel):
    context: dict


@router.post("/assignment-rules/preview")
def preview_assignment(payload: AssignmentPreview, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.assignment_rule.view"))):
    """Simulate before publish (Part 14 section 7): what a conversion with this context would get."""
    tenant = require_current_tenant()
    return {
        "onboarding_plan_template": assignment_rules.resolve_one(db, tenant, "onboarding_plan_template", payload.context),
        "letter_template": assignment_rules.resolve_one(db, tenant, "letter_template", payload.context),
        "roles": assignment_rules.resolve_all(db, tenant, "role", payload.context),
    }


# ---- BGV (HR) ----


class BgvCreate(BaseModel):
    subject_type: str = "candidate"
    subject_id: UUID
    preboarding_case_id: Optional[UUID] = None
    package: Optional[list[str]] = None
    package_code: Optional[str] = None
    vendor_connection_id: Optional[UUID] = None


def _bgv_or_404(db: Session, bgv_id: UUID) -> BgvCase:
    tenant = require_current_tenant()
    case = db.query(BgvCase).filter(BgvCase.tenant_id == tenant.tenant_id, BgvCase.id == bgv_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="BGV case not found")
    return case


@router.get("/bgv")
def list_bgv(db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.bgv.view"))):
    tenant = require_current_tenant()
    return [bgv.case_to_dict(c) for c in db.query(BgvCase).filter(BgvCase.tenant_id == tenant.tenant_id).order_by(BgvCase.created_at.desc()).all()]


@router.post("/bgv", status_code=201)
def create_bgv(payload: BgvCreate, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.bgv.create"))):
    try:
        case = bgv.create_case(db, require_current_tenant(), **payload.model_dump())
    except bgv.BgvError as exc:
        raise _bad_request(exc)
    # webhook_token returned once, to configure on the vendor side.
    return bgv.case_to_dict(case, include_webhook_token=True)


class BgvConsent(BaseModel):
    consent_text: str


@router.post("/bgv/{bgv_id}/consent")
def bgv_consent(bgv_id: UUID, payload: BgvConsent, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.bgv.edit"))):
    try:
        case = bgv.record_consent(db, _bgv_or_404(db, bgv_id), consent_text=payload.consent_text)
    except bgv.BgvError as exc:
        raise _bad_request(exc)
    log_action(db, "bgv_case", case.id, "bgv_consent_recorded", current_user.email)
    return bgv.case_to_dict(case)


class BgvInitiate(BaseModel):
    vendor_reference: Optional[str] = None


@router.post("/bgv/{bgv_id}/initiate")
def bgv_initiate(bgv_id: UUID, payload: BgvInitiate, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.bgv.edit"))):
    try:
        case = bgv.initiate(db, _bgv_or_404(db, bgv_id), vendor_reference=payload.vendor_reference)
    except bgv.BgvConsentRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bgv.BgvError as exc:
        raise _bad_request(exc)
    return bgv.case_to_dict(case)


class BgvDecision(BaseModel):
    decision: str


@router.post("/bgv/{bgv_id}/decision")
def bgv_decide(bgv_id: UUID, payload: BgvDecision, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.bgv.approve"))):
    try:
        case = bgv.decide(db, _bgv_or_404(db, bgv_id), decision=payload.decision, actor=current_user.email)
    except bgv.BgvError as exc:
        raise _bad_request(exc)
    log_action(db, "bgv_case", case.id, "bgv_decision", current_user.email, {"decision": case.decision})
    return bgv.case_to_dict(case)


# ---- dashboard ----


@router.get("/dashboard")
def onboarding_dashboard(horizon_days: int = 30, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.dashboard.view"))):
    return dashboard.summary(db, require_current_tenant(), horizon_days=horizon_days)


# ---- public: new-hire portal ----


def _portal_case(db: Session, token: str) -> tuple[PreboardingPortal, PreboardingCase]:
    portal = PreboardingPortal(db, require_current_tenant())
    try:
        return portal, portal.authenticate(token)
    except PortalAuthError as exc:
        # One generic message for invalid/expired/closed -- never confirms a token exists.
        raise HTTPException(status_code=401, detail="This link is no longer valid. Please contact HR for a new one.") from exc


@public_router.get("/portal/{token}")
def portal_home(token: str, db: Session = Depends(get_db)):
    portal, case = _portal_case(db, token)
    return portal.portal_view(case)


class PortalFormSubmit(BaseModel):
    data: dict


@public_router.post("/portal/{token}/forms/{form_key}")
def portal_submit_form(token: str, form_key: str, payload: PortalFormSubmit, db: Session = Depends(get_db)):
    portal, case = _portal_case(db, token)
    try:
        case = portal.submit_form(case, form_key, payload.data)
    except PortalValidationError as exc:
        raise _bad_request(exc)
    return portal.portal_view(case)


@public_router.post("/portal/{token}/policies/{policy_code}/acknowledge")
def portal_ack_policy(token: str, policy_code: str, db: Session = Depends(get_db)):
    portal, case = _portal_case(db, token)
    try:
        case = portal.acknowledge_policy(case, policy_code)
    except PortalValidationError as exc:
        raise _bad_request(exc)
    return portal.portal_view(case)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@public_router.post("/portal/{token}/documents", status_code=201)
async def portal_upload_document(token: str, document_type: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    portal, case = _portal_case(db, token)
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")
    extension = (file.filename or "").rsplit(".", 1)[-1] if "." in (file.filename or "") else "bin"
    try:
        document = portal.upload_document(case, document_type, content, extension)
    except PortalValidationError as exc:
        raise _bad_request(exc)
    return {"id": str(document.id), "document_type": document.document_type_code, "status": document.verification_status}


# ---- public: BGV vendor webhook ----


@public_router.post("/bgv/webhook")
def bgv_webhook(payload: dict, x_bgv_token: str = Header(..., alias="X-Bgv-Token"), db: Session = Depends(get_db)):
    tenant = require_current_tenant()
    case = bgv.find_by_webhook_token(db, tenant, x_bgv_token)
    if case is None:
        raise HTTPException(status_code=401, detail="Unknown webhook token")
    try:
        case = bgv.apply_webhook(db, case, payload)
    except bgv.BgvError as exc:
        raise _bad_request(exc)
    log_action(db, "bgv_case", case.id, "bgv_webhook_received", "vendor", {"status": case.status})
    return {"status": case.status}
