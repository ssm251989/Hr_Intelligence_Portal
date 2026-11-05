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

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.onboarding import OnboardingPlan, OnboardingTask, PreboardingCase, PreboardingDocument
from app.models.user import User
from app.onboarding import joiner_stage, plans
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
            + readiness["pre_joining_tasks"]["done"] + readiness.get("welcome_steps", {}).get("done", 0))
    total = (len(readiness["forms"]["required"]) + len(readiness["documents"]["required"]) + len(readiness["policies"]["required"])
             + readiness["pre_joining_tasks"]["total"] + readiness.get("welcome_steps", {}).get("total", 0))
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
            "can_mark_joined": "mark_joined" in joiner_stage.allowed_actions(db, case, today),
            # fix 2026-10-05: the stage + exactly the actions the server will accept (joiner_stage.py)
            "stage": joiner_stage.stage(db, case, today), "allowed_actions": joiner_stage.allowed_actions(db, case, today),
        })

    # fix 2026-10-05: joined in the last 90 days (or marked not reporting) -> the after-joining actions live here
    recent = []
    since = datetime.now(timezone.utc) - timedelta(days=90)
    joined = [c for c in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status == "joined").all()
              if (c.joined_at and c.joined_at >= since) or ((c.attributes_json or {}).get("not_reporting") or {}).get("status") == "active"]
    jp = _people(db, joined)
    # Part 20.2: the Onboarding agent's card per joiner (waiting for approval) / "Employee created - CTD-0012"
    from app.models.intelligence import AgentSuggestion

    cards_by_case = {r.entity_id: r for r in db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id,
                                                                              AgentSuggestion.kind == "employee_create",
                                                                              AgentSuggestion.entity_id.in_([c.id for c in joined] or [None])).all()}
    for case in sorted(joined, key=lambda c: c.joining_date, reverse=True):
        p = jp[case.id]
        flow = (case.attributes_json or {}).get("not_reporting") or {}
        recent.append({
            "case_id": str(case.id), "name": p["name"], "email": case.email, "role": p["role"], "department": p["department"],
            "candidate_id": p["candidate_id"], "joining_date": case.joining_date.isoformat(), "days_since_joining": (today - case.joining_date).days,
            "status": case.status, "stage": joiner_stage.stage(db, case, today), "allowed_actions": joiner_stage.allowed_actions(db, case, today),
            "not_reporting": ({"status": flow.get("status"), "last_seen": flow.get("last_seen"), "notices": [n.get("kind") for n in flow.get("notices", [])]}
                              if flow else None),
            "employee_created": (case.attributes_json or {}).get("employee_created"),
            "employee_card": ({"id": str(cards_by_case[case.id].id), "status": cards_by_case[case.id].status} if case.id in cards_by_case else None),
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
        "today": today.isoformat(), "cards": cards, "recent_joiners": recent, "documents_waiting": documents, "overdue_tasks": overdue_rows,
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
        "joining_details": _joining_details_hr(db, tenant, case),
    }


def _joining_details_hr(db: Session, tenant, case) -> Optional[dict]:
    from app.onboarding import welcome_steps

    try:
        return welcome_steps.hr_details_view(db, tenant, case)
    except Exception:  # noqa: BLE001 -- the joiner page must open even if this part can't be read
        return None


# ---- change 2026-10-05: joining details -- remind the joiner, lock, and the form settings ----


@router.post("/cases/{case_id}/joining-details/remind")
def remind_joining_details(case_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    """Emails the joiner the list of empty fields with their welcome link (at most once an hour)."""
    from datetime import timedelta

    from app.candidates.names import given_name
    from app.models.candidate import Candidate
    from app.platform.links import public_app_url
    from app.onboarding import welcome_steps
    from app.platform.comms.defaults import send_default

    tenant = require_current_tenant()
    case = _case_or_404(db, case_id)
    if case.status not in ("invited", "in_progress", "ready"):
        raise HTTPException(status_code=409, detail="This joiner's onboarding is closed.")
    view = welcome_steps.hr_details_view(db, tenant, case)
    labels = {f["key"]: f["label"] for f in view["fields"]}
    missing = view["missing_required"] + view["missing_optional"]
    if not missing:
        raise HTTPException(status_code=409, detail="Nothing is missing - every field is filled in.")
    last = view.get("last_reminder_at")
    if last and datetime.fromisoformat(last) > datetime.now(timezone.utc) - timedelta(hours=1):
        raise HTTPException(status_code=429, detail="A reminder was sent less than an hour ago.")
    if not case.portal_token:
        raise HTTPException(status_code=409, detail="This joiner has no welcome link. Send a new link first.")
    cand = db.get(Candidate, case.candidate_id) if case.candidate_id else None
    lines = [f"- {labels[k]}{' (needed)' if k in view['missing_required'] else ''}" for k in missing]
    msg = send_default(db, tenant, "onboarding.details_reminder", to=[case.email], purpose="email.outbound.onboarding",
                       related_entity_type="preboarding_case", related_entity_id=case.id,
                       ctx={"candidate_first_name": given_name(cand) if cand else (case.first_name or "there"), "missing": "\n".join(lines),
                            "portal_link": f"{public_app_url(db)}/welcome/{case.portal_token}"})
    welcome_steps.mark_reminded(db, case)
    log_action(db, "preboarding_case", case.id, "joining_details_reminder_sent", current_user.email, {"missing": missing, "email": msg.status})
    return {"sent": True, "status": msg.status, "missing": missing}


class LockIn(BaseModel):
    locked: bool


@router.post("/cases/{case_id}/joining-details/lock")
def lock_joining_details(case_id: UUID, body: LockIn, db: Session = Depends(get_db), current_user: User = Depends(require("onboarding.preboarding.edit"))):
    """While locked the joiner can't change their details (HR unlocks to let them edit again)."""
    from app.onboarding import welcome_steps

    case = _case_or_404(db, case_id)
    welcome_steps.set_lock(db, case, locked=body.locked, actor=current_user.email)
    log_action(db, "preboarding_case", case.id, "joining_details_locked" if body.locked else "joining_details_unlocked", current_user.email)
    return welcome_steps.hr_details_view(db, require_current_tenant(), case)


@router.get("/joining-form")
def joining_form_settings(db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    from app.onboarding import joining_form

    return joining_form.admin_view(db, require_current_tenant())


class JoiningFormIn(BaseModel):
    fields: dict = Field(default_factory=dict)
    documents: dict = Field(default_factory=dict)


@router.put("/joining-form")
def save_joining_form(body: JoiningFormIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    from app.onboarding import joining_form

    return joining_form.save(db, require_current_tenant(), body.model_dump(), actor=current_user.email)


class RevertIn(BaseModel):
    version: int


@router.post("/joining-form/revert")
def revert_joining_form(body: RevertIn, db: Session = Depends(get_db), current_user: User = Depends(require("platform.settings.configure"))):
    from app.onboarding import joining_form

    try:
        return joining_form.revert(db, require_current_tenant(), body.version, actor=current_user.email)
    except joining_form.FormSettingsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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

    # fix 2026-10-04: the built-in steps (offer, joining details, documents, day one) come first
    from app.onboarding import welcome_steps

    steps = welcome_steps.builtin_steps(db, tenant, case)
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
        steps.append({"kind": "form", "code": key, "label": form.name if form else _humanise(key), "done": key in submitted, "counted": True,
                      "fields": fields, "saved": saved if isinstance(saved, dict) else {}})
    for key in readiness["documents"]["required"]:
        d = latest.get(key)
        status = d.verification_status if d else "missing"
        steps.append({"kind": "document", "code": key, "label": doc_labels.get(key) or _humanise(key), "counted": True,
                      "done": status in ("pending", "verified"), "status": status, "rejection_reason": d.rejection_reason if d and status == "rejected" else None})
    policies = list(dict.fromkeys(readiness["policies"]["required"]))
    for key in policies:
        steps.append({"kind": "policy", "code": key, "label": _humanise(key), "done": key in acked, "counted": True})

    media = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == "welcome.video").first()
    from app.models.job_role import JobRole as _Job
    from app.recruitment.offer_welcome import contact_people, greeting_name

    application = db.get(Application, case.application_id) if case.application_id else None
    job = db.get(_Job, application.job_role_id) if application is not None else None
    cand = db.get(Candidate, case.candidate_id) if case.candidate_id else None
    for st in steps:  # fix 2026-10-05: configured steps get the same per-step state as the built-in ones
        if "state" not in st:
            st["state"] = "done" if st["done"] else ("in_progress" if st.get("status") == "pending" else "not_started")
            st["status_text"] = welcome_steps.STATE_TEXT[st["state"]]
            st.setdefault("description", None)
    counted = [s for s in steps if s.get("counted", True)]
    db.commit()  # keeps a sign link created for an older offer
    return {
        "first_name": greeting_name(db, cand, case) if cand is not None else person["first_name"], "role": person["role"],
        "joining_date": case.joining_date.isoformat(),
        "days_to_join": (case.joining_date - datetime.now(timezone.utc).date()).days, "status": case.status,
        "portal_schema": welcome_steps.PORTAL_SCHEMA,
        "steps": steps, "done": sum(1 for s in counted if s["done"]), "total": len(counted),
        "contacts": contact_people(db, tenant, job),
        "welcome": _welcome(case),
        "welcome_media": {"content_type": media.content_type, "title": media.title} if media is not None else None,
    }



# ---- fix 2026-10-04: the built-in welcome steps (public, by portal link) ----


class JoiningDetailsIn(BaseModel):
    data: dict = Field(default_factory=dict)
    submit: bool = False
    form_version: Optional[int] = None  # the settings version the form was opened with


def _portal_case(db: Session, token: str):
    portal = PreboardingPortal(db, require_current_tenant())
    try:
        return portal.authenticate(token)
    except PortalAuthError as exc:
        raise HTTPException(status_code=401, detail="This link is no longer valid. Please contact HR for a new one.") from exc


def _unlocked(db: Session, case) -> None:
    from app.models.offer import Offer

    offer = db.get(Offer, case.offer_id) if case.offer_id else None
    if offer is not None and not offer.signed:
        raise HTTPException(status_code=409, detail="This unlocks after you sign your offer.")


@public_router.put("/portal/{token}/joining-details")
def portal_joining_details(token: str, body: JoiningDetailsIn, db: Session = Depends(get_db)):
    """Autosave (submit=false) or submit (submit=true: everything checked)."""
    from app.onboarding import welcome_steps

    case = _portal_case(db, token)
    _unlocked(db, case)
    try:
        out = welcome_steps.save_joining_details(db, require_current_tenant(), case, body.data, submit=body.submit, form_version=body.form_version)
    except welcome_steps.DetailsLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    if body.submit and out["errors"]:
        raise HTTPException(status_code=400, detail={"message": "Please check the highlighted fields.", "errors": out["errors"]})
    return out


@public_router.post("/portal/{token}/joining-documents", status_code=201)
async def portal_joining_document(token: str, code: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    from app.onboarding import welcome_steps

    case = _portal_case(db, token)
    _unlocked(db, case)
    data = await file.read()
    try:
        return welcome_steps.upload_document(db, require_current_tenant(), case, code, data, file.filename or "file")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@public_router.post("/portal/{token}/day-one")
def portal_day_one(token: str, db: Session = Depends(get_db)):
    from app.onboarding import welcome_steps

    case = _portal_case(db, token)
    _unlocked(db, case)
    welcome_steps.acknowledge_day_one(db, case)
    return {"ok": True}


class PortalProblemIn(BaseModel):
    kind: str = Field(max_length=60)
    code: str = Field("", max_length=120)
    portal_schema: Optional[int] = None


@public_router.post("/portal/{token}/problem", status_code=202)
def portal_problem(token: str, body: PortalProblemIn, db: Session = Depends(get_db)):
    """fix 2026-10-05: the welcome page met a step it can't show (it showed the joiner a plain message instead).
    Logged as an error and in the audit log for admins -- once per joiner, step and day."""
    import logging

    from app.models.audit_log import AuditLog

    case = _portal_case(db, token)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    seen = (db.query(AuditLog).filter(AuditLog.entity_id == case.id, AuditLog.action == "portal_step_unrenderable", AuditLog.created_at >= today)
            .all())
    if not any((r.details or {}).get("kind") == body.kind and (r.details or {}).get("code") == body.code for r in seen):
        logging.getLogger(__name__).error("welcome portal can't show step kind=%s code=%s (case %s, page schema %s)", body.kind, body.code, case.id, body.portal_schema)
        log_action(db, "preboarding_case", case.id, "portal_step_unrenderable", "system",
                   {"kind": body.kind, "code": body.code, "page_schema": body.portal_schema})
    return {"ok": True}
