"""Part 15 step 15.6: read helpers (plus one small edit) for the Onboarding HR dashboard and
the public pre-joiner portal at /welcome. No new tables, no migrations; every lifecycle
action (joining date, no-show, revoke, new link, convert, verify, tasks) still goes through
the existing /api/v1/onboarding endpoints.

HR (staff session, tenant-scoped, permission-gated):
- GET  /api/v1/ui/onboarding/board                     joiner cards (name, role, readiness %,
                                                       pending documents, overdue tasks), the
                                                       verification queue with names, overdue
                                                       tasks with names, the daily reminder
                                                       check status, and signed offers that
                                                       have no onboarding yet
- GET  /api/v1/ui/onboarding/cases/{id}/detail         one joiner: checklist with friendly
                                                       labels, documents, plan tasks, history
- GET  /api/v1/ui/onboarding/documents/{id}/file       the uploaded file, for HR to check it
- PUT  /api/v1/ui/onboarding/cases/{id}/welcome        buddy, first-day agenda and a personal
                                                       message shown on the joiner's portal

Public (no staff login -- keyed ONLY by the case's existing portal_token, validated by
PreboardingPortal.authenticate, so expired/closed links fail exactly like the original
portal endpoint; only the joiner's own data is returned, never HR-only fields):
- GET  /api/v1/public/ui/onboarding/portal/{token}     first name, joining date, role,
                                                       friendly step list (forms with their
                                                       fields, documents, policies, offer
                                                       signed), welcome message, buddy,
                                                       agenda, whether a welcome video exists
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.onboarding import OnboardingPlan, OnboardingTask, PreboardingCase, PreboardingDocument
from app.models.user import User
from app.onboarding import plans
from app.onboarding.portal import UPLOAD_DIR, PortalAuthError, PreboardingPortal
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/onboarding", tags=["ui-onboarding"])
public_router = APIRouter(prefix="/api/v1/public/ui/onboarding", tags=["ui-onboarding-public"])

ACTIVE = ("invited", "in_progress", "ready")
_MAX_TEXT = 500
_MAX_AGENDA = 12


# ---- small helpers ----


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _humanise(code: str) -> str:
    words = (code or "").replace("_", " ").replace("-", " ").replace(".", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


def _label(label_i18n: Optional[dict], code: str, lang: str) -> str:
    labels = label_i18n or {}
    return _text(labels.get(lang)) or _text(labels.get("en")) or _humanise(code)


def _document_labels(db: Session, tenant, lang: str) -> dict[str, str]:
    from app.platform.metadata import masters

    try:
        return {v.code: _label(v.label_i18n, v.code, lang) for v in masters.list_values(db, tenant, "document_type", include_inactive=True)}
    except Exception:  # master type not seeded -- fall back to readable codes
        return {}


def _form_names(db: Session, tenant, keys: list[str]) -> dict[str, Any]:
    from app.platform.metadata import forms as forms_service

    out = {}
    for key in keys:
        try:
            out[key] = forms_service.get_form(db, tenant, key)
        except Exception:
            out[key] = None
    return out


def _people(db: Session, cases: list[PreboardingCase]) -> dict[UUID, dict]:
    """Name + role for each case: employee (pre_hire) row first, then candidate, then email."""
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.core_hr import Employee
    from app.models.job_role import JobRole
    from app.models.offer import Offer

    out: dict[UUID, dict] = {}
    for case in cases:
        employee = db.get(Employee, case.employee_id) if case.employee_id else None
        candidate = db.get(Candidate, case.candidate_id) if case.candidate_id else None
        offer = db.get(Offer, case.offer_id) if case.offer_id else None
        role = _text((case.attributes_json or {}).get("designation"))
        department = None
        # an offer has no job of its own -- the job comes from the offer's application
        application = db.get(Application, offer.application_id) if offer is not None and offer.application_id else None
        if application is not None and application.job_role_id:
            job = db.get(JobRole, application.job_role_id)
            if job is not None:
                role = role or job.title
                department = job.department
        first = (employee.preferred_name or employee.first_name) if employee else None
        full = " ".join(p for p in [(employee.first_name if employee else None), (employee.last_name if employee else None)] if p)
        if not full and candidate is not None:
            full = candidate.full_name or ""
        if not first and full:
            first = full.split(" ", 1)[0]
        out[case.id] = {
            "name": full or case.email, "first_name": first or case.email.split("@", 1)[0],
            "role": role or None, "department": department,
            "offer_signed": bool(offer.signed) if offer is not None else None,
            "candidate_id": str(case.candidate_id) if case.candidate_id else None,
        }
    return out


def _plan_tasks(db: Session, tenant, case: PreboardingCase) -> list[OnboardingTask]:
    plan = db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == tenant.tenant_id, OnboardingPlan.case_id == case.id).first()
    return plans.plan_tasks(db, tenant, plan.id) if plan is not None else []


def _case_or_404(db: Session, case_id: UUID) -> PreboardingCase:
    tenant = require_current_tenant()
    case = db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="We couldn't find this joiner.")
    return case


def _readiness_counts(readiness: dict) -> dict:
    done = (len(readiness["forms"]["submitted"]) + len(readiness["documents"]["verified"]) + len(readiness["policies"]["acknowledged"])
            + readiness["pre_joining_tasks"]["done"])
    total = (len(readiness["forms"]["required"]) + len(readiness["documents"]["required"]) + len(readiness["policies"]["required"])
             + readiness["pre_joining_tasks"]["total"])
    return {"done": done, "total": total}


def _welcome(case: PreboardingCase) -> dict:
    """The joiner-facing part of welcome_content_json, cleaned: message, buddy, agenda."""
    raw = case.welcome_content_json or {}
    buddy_raw = raw.get("buddy") if isinstance(raw.get("buddy"), dict) else None
    buddy = None
    if buddy_raw and _text(buddy_raw.get("name")):
        buddy = {
            "name": _text(buddy_raw.get("name"), 120), "title": _text(buddy_raw.get("title"), 160) or None,
            "note": _text(buddy_raw.get("note")) or None, "email": _text(buddy_raw.get("email"), 200) or None,
        }
    agenda = []
    for item in raw.get("agenda") if isinstance(raw.get("agenda"), list) else []:
        if isinstance(item, dict) and _text(item.get("title")):
            agenda.append({"time": _text(item.get("time"), 20) or None, "title": _text(item.get("title"), 200), "emoji": _text(item.get("emoji"), 40) or None})
    return {"message": _text(raw.get("message"), 1000) or None, "buddy": buddy, "agenda": agenda[:_MAX_AGENDA]}


def _digest_status(db: Session, tenant) -> dict:
    """The daily 'documents still missing' check (platform/jobs/scheduled.py onboarding_chase)
    files reminder suggestions for HR to approve; this reports whether it is on and when it
    last found something."""
    from sqlalchemy import func

    from app.models.intelligence import AgentSuggestion
    from app.platform.ai import governance

    try:
        enabled = bool(governance.feature_enabled(db, tenant, "agents.onboarding"))
    except Exception:
        enabled = False
    base = db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.agent == "onboarding", AgentSuggestion.kind == "chase_documents")
    last = base.with_entities(func.max(AgentSuggestion.created_at)).scalar()
    waiting = base.filter(AgentSuggestion.status == "pending").count()
    return {"enabled": enabled, "last_found_at": _iso(last), "reminders_waiting": waiting}


# ---- HR: board ----


@router.get("/board")
def board(lang: str = "en", db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.job_role import JobRole
    from app.models.offer import Offer

    tenant = require_current_tenant()
    portal = PreboardingPortal(db, tenant)
    today = datetime.now(timezone.utc).date()
    cases = (
        db.query(PreboardingCase)
        .filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status.in_(ACTIVE))
        .order_by(PreboardingCase.joining_date.asc())
        .all()
    )
    people = _people(db, cases)
    doc_labels = _document_labels(db, tenant, lang)
    overdue = plans.overdue_tasks(db, tenant, today=today)
    plan_case = {p.id: p.case_id for p in db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == tenant.tenant_id).all()}
    overdue_by_case: dict[UUID, int] = {}
    for task in overdue:
        cid = plan_case.get(task.plan_id)
        if cid is not None:
            overdue_by_case[cid] = overdue_by_case.get(cid, 0) + 1
    pending_docs = (
        db.query(PreboardingDocument)
        .filter(PreboardingDocument.tenant_id == tenant.tenant_id, PreboardingDocument.verification_status == "pending")
        .order_by(PreboardingDocument.uploaded_at.asc())
        .all()
    )
    pending_by_case: dict[UUID, int] = {}
    for d in pending_docs:
        pending_by_case[d.case_id] = pending_by_case.get(d.case_id, 0) + 1

    cases_with_plan = set(plan_case.values())
    cards = []
    for case in cases:
        readiness = portal.readiness(case)
        days = (case.joining_date - today).days
        p = people[case.id]
        cards.append({
            "case_id": str(case.id), "name": p["name"], "email": case.email, "role": p["role"], "department": p["department"],
            "candidate_id": p["candidate_id"], "joining_date": case.joining_date.isoformat(), "days_to_join": days,
            "status": case.status, "readiness_percent": readiness["percent"], "readiness": _readiness_counts(readiness),
            "not_ready_soon": days <= 3 and readiness["percent"] < 100, "documents_waiting": pending_by_case.get(case.id, 0),
            "overdue_tasks": overdue_by_case.get(case.id, 0), "has_plan": case.id in cases_with_plan,
            "link_expires_at": _iso(case.portal_token_expires_at), "link_expired": case.portal_token_expires_at < datetime.now(timezone.utc),
            "can_mark_joined": case.joining_date <= today,
        })

    # names for the queue + overdue lists, including cases outside the active set
    other_ids = {d.case_id for d in pending_docs} | {plan_case.get(t.plan_id) for t in overdue}
    other_ids.discard(None)
    extra_cases = [c for c in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.id.in_(list(other_ids))).all() if c.id not in people] if other_ids else []
    people.update(_people(db, extra_cases))

    documents = [
        {"id": str(d.id), "case_id": str(d.case_id), "name": people.get(d.case_id, {}).get("name", ""), "document_type": d.document_type_code,
         "label": doc_labels.get(d.document_type_code) or _humanise(d.document_type_code), "uploaded_at": _iso(d.uploaded_at),
         "extracted": ((d.extracted_json or {}).get("fields") if isinstance((d.extracted_json or {}).get("fields"), dict) else None)}
        for d in pending_docs
    ]
    overdue_rows = [
        {"id": str(t.id), "case_id": str(plan_case.get(t.plan_id)) if plan_case.get(t.plan_id) else None,
         "name": people.get(plan_case.get(t.plan_id), {}).get("name", ""), "title": t.title, "owner_role": t.owner_role,
         "due_date": t.due_date.isoformat(), "days_late": (today - t.due_date).days, "status": t.status}
        for t in overdue
    ]

    # signed offers with no onboarding yet -> "Start onboarding" picks from these
    started = {c.offer_id for c in db.query(PreboardingCase.offer_id).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.offer_id.isnot(None)).all()}
    ready_offers = []
    for offer in db.query(Offer).filter(Offer.tenant_id == tenant.tenant_id, Offer.signed.is_(True)).order_by(Offer.created_at.desc()).limit(50).all():
        if offer.id in started:
            continue
        application = db.get(Application, offer.application_id) if offer.application_id else None
        candidate = db.get(Candidate, application.candidate_id) if application is not None and application.candidate_id else None
        if candidate is None or not candidate.email:
            continue
        job = db.get(JobRole, application.job_role_id) if application.job_role_id else None
        ready_offers.append({"offer_id": str(offer.id), "name": candidate.full_name or candidate.email, "email": candidate.email,
                             "role": job.title if job else None, "joining_date": _iso(offer.joining_date)})

    return {
        "today": today.isoformat(), "cards": cards, "documents_waiting": documents, "overdue_tasks": overdue_rows,
        "digest": _digest_status(db, tenant), "ready_offers": ready_offers,
        "can": {
            "create": has_permission(db, tenant, current_user, "onboarding.preboarding.create"),
            "edit": has_permission(db, tenant, current_user, "onboarding.preboarding.edit"),
            "approve": has_permission(db, tenant, current_user, "onboarding.preboarding.approve"),
            "tasks": has_permission(db, tenant, current_user, "onboarding.task.edit"),
            "plans": has_permission(db, tenant, current_user, "onboarding.plan.create"),
        },
    }


# ---- HR: one joiner ----


@router.get("/cases/{case_id}/detail")
def case_detail(case_id: UUID, lang: str = "en", db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    tenant = require_current_tenant()
    case = _case_or_404(db, case_id)
    portal = PreboardingPortal(db, tenant)
    readiness = portal.readiness(case)
    doc_labels = _document_labels(db, tenant, lang)
    forms = _form_names(db, tenant, readiness["forms"]["required"])
    documents = portal.documents(case)
    by_type: dict[str, PreboardingDocument] = {}
    for d in documents:
        by_type[d.document_type_code] = d  # latest upload wins (ordered by uploaded_at)
    checklist = (
        [{"kind": "form", "code": k, "label": (forms.get(k).name if forms.get(k) else _humanise(k)), "done": k in readiness["forms"]["submitted"]} for k in readiness["forms"]["required"]]
        + [{"kind": "document", "code": k, "label": doc_labels.get(k) or _humanise(k), "done": k in readiness["documents"]["verified"],
            "status": by_type[k].verification_status if k in by_type else "missing"} for k in readiness["documents"]["required"]]
        + [{"kind": "policy", "code": k, "label": _humanise(k), "done": k in readiness["policies"]["acknowledged"]} for k in readiness["policies"]["required"]]
    )
    person = _people(db, [case])[case.id]
    return {
        "case_id": str(case.id), **person, "email": case.email, "joining_date": case.joining_date.isoformat(), "status": case.status,
        "readiness_percent": readiness["percent"], "readiness": _readiness_counts(readiness), "checklist": checklist,
        "documents": [{"id": str(d.id), "document_type": d.document_type_code, "label": doc_labels.get(d.document_type_code) or _humanise(d.document_type_code),
                       "status": d.verification_status, "rejection_reason": d.rejection_reason, "uploaded_at": _iso(d.uploaded_at),
                       "has_file": bool(d.file_path)} for d in documents],
        "tasks": [plans.task_to_dict(t) for t in _plan_tasks(db, tenant, case)],
        "history": [{"event": h.get("event"), "at": h.get("at"), "actor": h.get("actor"), "reason": h.get("reason"), "old": h.get("old"), "new": h.get("new")}
                    for h in (case.history_json or []) if isinstance(h, dict)],
        "welcome": _welcome(case), "link_expires_at": _iso(case.portal_token_expires_at),
    }


@router.get("/documents/{document_id}/file")
def document_file(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.view"))):
    tenant = require_current_tenant()
    document = db.query(PreboardingDocument).filter(PreboardingDocument.tenant_id == tenant.tenant_id, PreboardingDocument.id == document_id).first()
    if document is None or not document.file_path:
        raise HTTPException(status_code=404, detail="We couldn't find that file.")
    path = (UPLOAD_DIR / Path(document.file_path).name).resolve()
    if not path.is_file() or UPLOAD_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="We couldn't find that file.")
    log_action(db, "preboarding_document", document.id, "document_viewed", current_user.email)
    return FileResponse(path)


class BuddyIn(BaseModel):
    name: str = Field(..., max_length=120)
    title: Optional[str] = Field(None, max_length=160)
    note: Optional[str] = Field(None, max_length=_MAX_TEXT)
    email: Optional[str] = Field(None, max_length=200)


class AgendaIn(BaseModel):
    time: Optional[str] = Field(None, max_length=20)
    title: str = Field(..., max_length=200)
    emoji: Optional[str] = Field(None, max_length=40)


class WelcomeIn(BaseModel):
    message: Optional[str] = Field(None, max_length=1000)
    buddy: Optional[BuddyIn] = None
    agenda: list[AgendaIn] = Field(default_factory=list, max_length=_MAX_AGENDA)


@router.put("/cases/{case_id}/welcome")
def save_welcome(case_id: UUID, payload: WelcomeIn, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    case = _case_or_404(db, case_id)
    content = dict(case.welcome_content_json or {})  # keeps anything else stored there (e.g. policies)
    content["message"] = (payload.message or "").strip() or None
    content["buddy"] = payload.buddy.model_dump() if payload.buddy and payload.buddy.name.strip() else None
    content["agenda"] = [a.model_dump() for a in payload.agenda if a.title.strip()]
    case.welcome_content_json = content
    db.commit()
    db.refresh(case)
    log_action(db, "preboarding_case", case.id, "welcome_content_updated", current_user.email)
    return _welcome(case)


# ---- public: the joiner's own portal summary ----


@public_router.get("/portal/{token}")
def portal_summary(token: str, lang: str = "en", db: Session = Depends(get_db)):
    from app.models.experience import TenantMedia

    tenant = require_current_tenant()
    portal = PreboardingPortal(db, tenant)
    try:
        case = portal.authenticate(token)
    except PortalAuthError as exc:
        # Same generic answer as the original portal -- never confirms a link exists.
        raise HTTPException(status_code=401, detail="This link is no longer valid. Please contact HR for a new one.") from exc

    readiness = portal.readiness(case)
    person = _people(db, [case])[case.id]
    doc_labels = _document_labels(db, tenant, lang)
    forms = _form_names(db, tenant, readiness["forms"]["required"])
    documents = portal.documents(case)
    latest: dict[str, PreboardingDocument] = {}
    for d in documents:
        latest[d.document_type_code] = d
    submitted = set((case.form_submissions_json or {}).keys())
    acked = set((case.policy_acks_json or {}).keys())

    steps = []
    if person["offer_signed"] is not None:
        steps.append({"kind": "offer", "code": "offer", "label": None, "done": bool(person["offer_signed"])})
    for key in readiness["forms"]["required"]:
        form = forms.get(key)
        schema = (form.schema_json or {}) if form else {}
        ui = (form.ui_schema_json or {}) if form else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = set(schema.get("required") or [])
        fields = []
        for name, spec in props.items():
            spec = spec if isinstance(spec, dict) else {}
            hint = ui.get(name) if isinstance(ui.get(name), dict) else {}
            fields.append({
                "key": name, "label": _text(spec.get("title")) or _humanise(name), "type": _text(spec.get("type")) or "string",
                "format": _text(spec.get("format")) or None, "options": [str(o) for o in spec.get("enum", [])] if isinstance(spec.get("enum"), list) else None,
                "required": name in required, "hint": _text(spec.get("description")) or None,
                "placeholder": _text(hint.get("ui:placeholder")) or _text(spec.get("examples", [None])[0] if isinstance(spec.get("examples"), list) and spec.get("examples") else None) or None,
            })
        saved = ((case.form_submissions_json or {}).get(key) or {}).get("data") or {}
        steps.append({"kind": "form", "code": key, "label": form.name if form else _humanise(key), "done": key in submitted,
                      "fields": fields, "saved": saved if isinstance(saved, dict) else {}})
    for key in readiness["documents"]["required"]:
        d = latest.get(key)
        status = d.verification_status if d else "missing"
        steps.append({"kind": "document", "code": key, "label": doc_labels.get(key) or _humanise(key),
                      "done": status in ("pending", "verified"), "status": status, "rejection_reason": d.rejection_reason if d and status == "rejected" else None})
    policies = list(dict.fromkeys(readiness["policies"]["required"]))
    for key in policies:
        steps.append({"kind": "policy", "code": key, "label": _humanise(key), "done": key in acked})

    media = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == "welcome.video").first()
    return {
        "first_name": person["first_name"], "role": person["role"], "joining_date": case.joining_date.isoformat(),
        "days_to_join": (case.joining_date - datetime.now(timezone.utc).date()).days, "status": case.status,
        "steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps),
        "welcome": _welcome(case),
        "welcome_media": {"content_type": media.content_type, "title": media.title} if media is not None else None,
    }
