"""Recruitment platform API (docs/HRMS_COMPLETE_SPEC.txt Part 8) -- pipeline templates,
job requisitions, hiring team, interviewer availability, offer components/CTC, and the
prompt registry. Gated by `authz.require(...)` using new `recruitment.*` permission codes
(Part 5's registry), same pattern as every platform router since Part 5."""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.interview_scheduling import availability as availability_service
from app.models.interviewer_availability import InterviewerAvailability
from app.models.job_role import JobRole
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import career_site, ctc, hiring_team, pipeline, prompt_registry, requisitions

router = APIRouter(prefix="/api/v1/recruitment", tags=["recruitment"])
public_router = APIRouter(prefix="/api/v1/public/recruitment", tags=["recruitment-public"])


# ---- pipeline templates/stages ----


@router.post("/pipeline-templates/seed-default")
def seed_default_pipeline_template(db: Session = Depends(get_db), current_user=Depends(require("recruitment.pipeline.configure"))):
    tenant = require_current_tenant()
    template = pipeline.seed_default_template(db, tenant)
    return {"id": str(template.id), "name": template.name, "is_default": template.is_default}


@router.get("/pipeline-templates")
def list_pipeline_templates(db: Session = Depends(get_db), current_user=Depends(require("recruitment.pipeline.view"))):
    tenant = require_current_tenant()
    return [{"id": str(t.id), "name": t.name, "is_default": t.is_default} for t in pipeline.list_templates(db, tenant)]


@router.get("/pipeline-templates/{template_id}/stages")
def list_pipeline_stages(template_id: UUID, db: Session = Depends(get_db), current_user=Depends(require("recruitment.pipeline.view"))):
    tenant = require_current_tenant()
    return [
        {"id": str(s.id), "code": s.code, "name_i18n": s.name_i18n, "order": s.order, "category": s.category, "sla_days": s.sla_days}
        for s in pipeline.list_stages(db, tenant, template_id)
    ]


# ---- job requisitions ----


@router.post("/requisitions", status_code=201)
def create_requisition(payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.requisition.create"))):
    tenant = require_current_tenant()
    requisition = requisitions.create_requisition(
        db, tenant, title=payload["title"], reason=payload.get("reason", "new"), headcount=payload.get("headcount", 1),
        position_id=payload.get("position_id"), department_id=payload.get("department_id"), budget=payload.get("budget"),
        justification=payload.get("justification"), requested_by=current_user.email,
    )
    return {"id": str(requisition.id), "status": requisition.status}


@router.get("/requisitions")
def list_requisitions(status: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require("recruitment.requisition.view"))):
    tenant = require_current_tenant()
    return [
        {"id": str(r.id), "title": r.title, "reason": r.reason, "headcount": r.headcount, "status": r.status}
        for r in requisitions.list_requisitions(db, tenant, status=status)
    ]


@router.post("/requisitions/{requisition_id}/request-approval")
def request_requisition_approval(requisition_id: UUID, db: Session = Depends(get_db), current_user=Depends(require("recruitment.requisition.approve"))):
    tenant = require_current_tenant()
    try:
        result = requisitions.request_approval(db, tenant, requisition_id, requested_by_user_id=current_user.id, actor_email=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if result["applied"]:
        return {"applied": True, "status": result["status"]}
    return {"applied": False, "workflow_instance_id": str(result["workflow_instance_id"])}


# ---- hiring team ----


@router.post("/jobs/{job_role_id}/hiring-team", status_code=201)
def add_hiring_team_member(job_role_id: UUID, payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.job.edit"))):
    tenant = require_current_tenant()
    try:
        member = hiring_team.add_member(
            db, tenant, job_role_id=job_role_id, role_in_hiring=payload["role_in_hiring"],
            user_id=payload.get("user_id"), external_name=payload.get("external_name"), external_email=payload.get("external_email"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(member.id), "role_in_hiring": member.role_in_hiring}


@router.get("/jobs/{job_role_id}/hiring-team")
def list_hiring_team(job_role_id: UUID, db: Session = Depends(get_db), current_user=Depends(require("recruitment.job.view"))):
    tenant = require_current_tenant()
    return [
        {"id": str(m.id), "role_in_hiring": m.role_in_hiring, "user_id": str(m.user_id) if m.user_id else None, "external_name": m.external_name, "external_email": m.external_email}
        for m in hiring_team.list_members(db, tenant, job_role_id)
    ]


# ---- interviewer availability ----


@router.put("/interviewer-availability")
def upsert_interviewer_availability(payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.availability.configure"))):
    tenant = require_current_tenant()
    row = availability_service.upsert_availability(
        db, tenant, interviewer_email=payload["interviewer_email"], interviewer_name=payload.get("interviewer_name"),
        employee_id=payload.get("employee_id"), weekly_pattern=payload.get("weekly_pattern"), exceptions=payload.get("exceptions"),
        max_interviews_per_day=payload.get("max_interviews_per_day"), max_interviews_per_week=payload.get("max_interviews_per_week"),
        skills=payload.get("skills"),
    )
    return {"id": str(row.id), "interviewer_email": row.interviewer_email}


@router.get("/interviewer-availability")
def list_interviewer_availability(db: Session = Depends(get_db), current_user=Depends(require("recruitment.availability.view"))):
    tenant = require_current_tenant()
    rows: list[InterviewerAvailability] = availability_service.list_availability(db, tenant)
    return [
        {
            "id": str(r.id), "interviewer_email": r.interviewer_email, "interviewer_name": r.interviewer_name,
            "max_interviews_per_day": r.max_interviews_per_day, "max_interviews_per_week": r.max_interviews_per_week, "source": r.source,
        }
        for r in rows
    ]


# ---- offer components / CTC breakup ----


@router.post("/offer-components", status_code=201)
def create_offer_component(payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.offer.edit"))):
    tenant = require_current_tenant()
    component = ctc.create_component(db, tenant, code=payload["code"], name=payload["name"], type=payload["type"], value=payload["value"], order=payload.get("order", 0))
    return {"id": str(component.id), "code": component.code}


@router.get("/offer-components")
def list_offer_components(db: Session = Depends(get_db), current_user=Depends(require("recruitment.offer.view"))):
    tenant = require_current_tenant()
    return [{"id": str(c.id), "code": c.code, "name": c.name, "type": c.type, "value": float(c.value)} for c in ctc.list_components(db, tenant)]


@router.post("/offers/{offer_id}/ctc-breakup")
def compute_offer_ctc_breakup(offer_id: UUID, payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.offer.edit"))):
    tenant = require_current_tenant()
    try:
        offer = ctc.apply_ctc_breakup_to_offer(db, tenant, offer_id, base_ctc=payload["base_ctc"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return offer.ctc_breakup_json


@router.post("/offers/{offer_id}/counter-offer")
def record_offer_counter_offer(offer_id: UUID, payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.offer.edit"))):
    tenant = require_current_tenant()
    try:
        offer = ctc.record_counter_offer(db, tenant, offer_id, amount=payload["amount"], notes=payload.get("notes"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"counter_offer": offer.counter_offer_json}


@router.post("/offers/{offer_id}/joining-date")
def set_offer_joining_date(offer_id: UUID, payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.offer.edit"))):
    tenant = require_current_tenant()
    try:
        offer = ctc.set_joining_date(db, tenant, offer_id, joining_date=date.fromisoformat(payload["joining_date"]))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"joining_date": offer.joining_date.isoformat() if offer.joining_date else None}


# ---- prompt registry ----


@router.post("/prompts", status_code=201)
def create_prompt_draft(payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.prompt.configure"))):
    tenant = require_current_tenant()
    prompt = prompt_registry.create_draft(
        db, tenant, key=payload["key"], name=payload["name"], system_prompt=payload["system_prompt"],
        purpose=payload.get("purpose"), variables_schema=payload.get("variables_schema"),
    )
    return {"id": str(prompt.id), "key": prompt.key, "version": prompt.version, "status": prompt.status}


@router.post("/prompts/{prompt_id}/publish")
def publish_prompt(prompt_id: UUID, db: Session = Depends(get_db), current_user=Depends(require("recruitment.prompt.configure"))):
    from app.models.prompt import PromptTemplate

    prompt = db.get(PromptTemplate, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    prompt = prompt_registry.publish(db, prompt)
    return {"id": str(prompt.id), "status": prompt.status}


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db), current_user=Depends(require("recruitment.prompt.view"))):
    tenant = require_current_tenant()
    return [{"id": str(p.id), "key": p.key, "version": p.version, "status": p.status, "purpose": p.purpose} for p in prompt_registry.list_prompts(db, tenant)]


# ---- career site: knockout questions on a job ----


@router.put("/jobs/{job_role_id}/knockout-questions")
def set_knockout_questions(job_role_id: UUID, payload: dict, db: Session = Depends(get_db), current_user=Depends(require("recruitment.job.edit"))):
    job = db.get(JobRole, job_role_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.knockout_questions_json = payload.get("questions", [])
    db.commit()
    db.refresh(job)
    return {"questions": job.knockout_questions_json}


@public_router.get("/jobs/{job_role_id}/structured-data")
def get_job_structured_data(job_role_id: UUID, db: Session = Depends(get_db)):
    """Public, no-auth -- mirrors the already-public /public/jobs/{id} (this is only a
    different SERIALIZATION of the same published job, not new data), same "public_router,
    separate prefix" convention as every other part's own public endpoints."""
    from app.platform.comms.theme import get_theme_and_org_context

    job = db.get(JobRole, job_role_id)
    if job is None or job.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")
    tenant = require_current_tenant()
    org_display_name = get_theme_and_org_context(db, tenant)["org"]["display_name"]
    from app.core.config import settings as app_settings

    return career_site.job_structured_data(job, org_display_name, app_settings.APP_BASE_URL)
