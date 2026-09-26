"""Part 15.4 -- read helpers for the restyled Screening / Shortlisting pages
(docs/HRMS_COMPLETE_SPEC.txt section L "SCREENING & SHORTLISTING" S1-S7, K F1).

Nothing here changes how screening or shortlisting decide anything. It only:
  * lists the same rows as GET /candidates/applications and GET /shortlisting/list, with the
    same filters, but highest score first (S3);
  * counts scores so the threshold slider can say "N candidates pass" live (S4);
  * returns the audited score breakdown + evidence lines from the parsed resume for the
    hover card and the compare-3 dialog (S1, S2, S5);
  * serves the company's "Rejection Reason" picklist to recruiters (S7) -- the metadata
    endpoint for masters is gated by settings permissions, which recruiters don't have;
  * shows the auto-shortlist undo window and lets a recruiter undo inside it (K F1).

Register in app/main.py:
    from app.experience.ui_screening_router import router as ui_screening_router
    app.include_router(ui_screening_router)
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.candidates.router import _filtered_candidate_applications_query, row_to_item
from app.core.database import get_db
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.metadata import MasterValue
from app.models.user import User
from app.platform.tenancy.context import get_current_tenant
from app.schemas.candidates_dashboard import CandidatesListPage
from app.shortlisting.service import shortlisting_scope_condition

router = APIRouter(prefix="/api/v1/ui/screening", tags=["ui-screening"])

_Scope = Literal["screening", "shortlisting"]
_ShortlistStatus = Literal["under_review", "shortlisted", "on_hold", "not_shortlisted"]

# Audit actions a (future) auto-shortlist step writes. Kept as a tuple so either spelling works.
AUTO_SHORTLIST_ACTIONS = ("ai_auto_shortlisted", "auto_shortlisted")
AUTO_SHORTLIST_UNDONE = "auto_shortlist_undone"
# K F1 default: 4 business hours (Mon-Fri, 09:00-18:00 company time). An auto-shortlist entry
# that records its own `undo_until` wins over this computed default.
UNDO_BUSINESS_HOURS = 4
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18

# Used only when the company hasn't filled the Rejection Reason master yet.
DEFAULT_REJECT_REASONS = [
    ("skills_gap", "Key skills missing"),
    ("experience_low", "Not enough experience"),
    ("experience_high", "Over-qualified for this role"),
    ("salary_mismatch", "Salary expectations don't match"),
    ("location", "Location or commute doesn't work"),
    ("notice_period", "Notice period too long"),
    ("role_filled", "Role already filled"),
    ("other", "Other"),
]


def _score_expr():
    return func.coalesce(Application.composite_score, Application.match_score)


def _apply_shortlist_status(query, shortlist_status: Optional[str]):
    if shortlist_status is None:
        return query.filter(shortlisting_scope_condition())
    if shortlist_status == "under_review":
        return query.filter(Application.status == "screened")
    if shortlist_status == "shortlisted":
        return query.filter(Application.status == "hr_selected")
    if shortlist_status == "not_shortlisted":
        return query.filter(Application.status == "hr_rejected")
    return query.filter(Application.status == "on_hold", Application.previous_status == "screened")


def _base_query(
    db: Session, *, scope: str, status: Optional[str], shortlist_status: Optional[str], job_role_id, source, location,
    search, experience_min, experience_max, applied_after, applied_before, match_score_min, match_score_max,
):
    query = _filtered_candidate_applications_query(
        db, job_role_id=job_role_id, status=status if scope == "screening" else None, source=source, location=location,
        search=search, experience_min=experience_min, experience_max=experience_max, applied_after=applied_after,
        applied_before=applied_before, match_score_min=match_score_min, match_score_max=match_score_max,
        score_field="composite_score",
    )
    if scope == "shortlisting":
        query = _apply_shortlist_status(query, shortlist_status)
    return query


@router.get("/list", response_model=CandidatesListPage)
def list_sorted(
    scope: _Scope = Query("screening"),
    sort: Literal["score", "newest"] = Query("score"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    job_role_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    shortlist_status: Optional[_ShortlistStatus] = Query(None),
    source: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    experience_min: Optional[float] = Query(None),
    experience_max: Optional[float] = Query(None),
    applied_after: Optional[date] = Query(None),
    applied_before: Optional[date] = Query(None),
    match_score_min: Optional[float] = Query(None, ge=0, le=100),
    match_score_max: Optional[float] = Query(None, ge=0, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Same rows/filters as the Screening List (GET /candidates/applications, composite score
    filter) or the Shortlisting List (GET /shortlisting/list) -- S3: highest score first."""
    query = _base_query(
        db, scope=scope, status=status, shortlist_status=shortlist_status, job_role_id=job_role_id, source=source,
        location=location, search=search, experience_min=experience_min, experience_max=experience_max,
        applied_after=applied_after, applied_before=applied_before, match_score_min=match_score_min,
        match_score_max=match_score_max,
    )
    total = query.count()
    order = (
        [_score_expr().desc().nullslast(), Application.created_at.desc()]
        if sort == "score"
        else [Application.created_at.desc()]
    )
    rows = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
    items = [row_to_item(a, c, title, suitable, action, details) for a, c, title, suitable, action, details in rows]
    return CandidatesListPage(total=total, page=page, page_size=page_size, items=items)


class ScoreCounts(BaseModel):
    total: int
    scored: int
    # counts[s] = number of candidates whose (rounded) score is exactly s, s = 0..100
    counts: list[int]


@router.get("/score-counts", response_model=ScoreCounts)
def score_counts(
    scope: _Scope = Query("screening"),
    search: Optional[str] = Query(None),
    job_role_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    shortlist_status: Optional[_ShortlistStatus] = Query(None),
    source: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    experience_min: Optional[float] = Query(None),
    experience_max: Optional[float] = Query(None),
    applied_after: Optional[date] = Query(None),
    applied_before: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """S4: one small histogram so the slider can show "N candidates pass" for ANY position
    without another request. Score-range filters are deliberately not applied here."""
    query = _base_query(
        db, scope=scope, status=status, shortlist_status=shortlist_status, job_role_id=job_role_id, source=source,
        location=location, search=search, experience_min=experience_min, experience_max=experience_max,
        applied_after=applied_after, applied_before=applied_before, match_score_min=None, match_score_max=None,
    )
    counts = [0] * 101
    total = 0
    scored = 0
    for application, *_rest in query.all():
        total += 1
        value = application.composite_score if application.composite_score is not None else application.match_score
        if value is None:
            continue
        scored += 1
        counts[max(0, min(100, int(round(float(value)))))] += 1
    return ScoreCounts(total=total, scored=scored, counts=counts)


# ---- score breakdown, evidence, auto-shortlist window ----


class Evidence(BaseModel):
    kind: Literal["skill", "experience", "certificate", "education", "gap"]
    text: str


class AutoShortlistInfo(BaseModel):
    at: datetime
    undo_until: datetime
    can_undo: bool
    recruiter_notified: bool
    notified_to: Optional[str] = None
    breakdown: dict[str, Optional[float]] = {}
    undone: bool = False


class ScreeningDetail(BaseModel):
    application_id: uuid.UUID
    score: Optional[float]
    recommendation: Optional[str]
    breakdown: dict[str, Optional[float]]
    matched_skills: list[str]
    missing_skills: list[str]
    missing_required_skills: list[str]
    experience_years: Optional[float]
    current_title: Optional[str]
    evidence: list[Evidence]
    screened_at: Optional[datetime]
    auto_shortlist: Optional[AutoShortlistInfo] = None


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _breakdown(details: dict) -> dict[str, Optional[float]]:
    return {
        "skills": _num(details.get("skills_score")),
        "experience": _num(details.get("experience_score")),
        "location": _num(details.get("location_score")),
        "certificates": _num(details.get("certificates_score")),
        "resume_match": _num(details.get("resume_matcher_score")),
    }


def _company_tz() -> ZoneInfo:
    ctx = get_current_tenant()
    try:
        return ZoneInfo(ctx.tz if ctx else "Asia/Kolkata")
    except Exception:  # unknown zone name -> UTC
        return ZoneInfo("UTC")


def _add_business_hours(start: datetime, hours: int, tz: ZoneInfo) -> datetime:
    """start + N working hours (Mon-Fri, BUSINESS_START..END company time)."""
    local = start.astimezone(tz)
    remaining = timedelta(hours=hours)
    while remaining > timedelta(0):
        day_start = local.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
        day_end = local.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
        if local.weekday() >= 5 or local >= day_end:
            local = (local + timedelta(days=1)).replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
            continue
        if local < day_start:
            local = day_start
        step = min(remaining, day_end - local)
        local += step
        remaining -= step
    return local.astimezone(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _auto_shortlist_info(db: Session, application: Application) -> Optional[AutoShortlistInfo]:
    entry = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "application", AuditLog.entity_id == application.id, AuditLog.action.in_(AUTO_SHORTLIST_ACTIONS))
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    if entry is None:
        return None
    details = entry.details or {}
    at = entry.created_at if entry.created_at.tzinfo else entry.created_at.replace(tzinfo=timezone.utc)
    undo_until = _parse_dt(details.get("undo_until")) or _add_business_hours(at, UNDO_BUSINESS_HOURS, _company_tz())
    undone = (
        db.query(AuditLog.id)
        .filter(AuditLog.entity_type == "application", AuditLog.entity_id == application.id,
                AuditLog.action == AUTO_SHORTLIST_UNDONE, AuditLog.created_at >= entry.created_at)
        .first()
        is not None
    )
    now = datetime.now(timezone.utc)
    return AutoShortlistInfo(
        at=at,
        undo_until=undo_until,
        can_undo=(not undone) and application.status == "hr_selected" and now < undo_until,
        recruiter_notified=bool(details.get("recruiter_notified") or details.get("notified_to")),
        notified_to=details.get("notified_to"),
        breakdown=_breakdown(details.get("breakdown") or details),
        undone=undone,
    )


def _evidence(parsed: dict, matched: list[str], missing_required: list[str]) -> list[Evidence]:
    """S2: lines taken from the candidate's parsed resume (never invented)."""
    lines: list[Evidence] = []
    years = parsed.get("total_experience_years")
    for job in (parsed.get("work_history") or [])[:3]:
        title, company = (job or {}).get("title"), (job or {}).get("company")
        if not title and not company:
            continue
        span = " – ".join(p for p in [(job or {}).get("start"), (job or {}).get("end")] if p)
        text = " at ".join(p for p in [title, company] if p)
        lines.append(Evidence(kind="experience", text=f"{text}{f' ({span})' if span else ''}"))
    if years is not None and not lines:
        lines.append(Evidence(kind="experience", text=f"{years:g} years of experience"))
    if matched:
        lines.append(Evidence(kind="skill", text=", ".join(matched[:8])))
    for cert in (parsed.get("certificates") or [])[:2]:
        if cert:
            lines.append(Evidence(kind="certificate", text=str(cert)))
    for edu in (parsed.get("education") or [])[:1]:
        text = ", ".join(str(p) for p in [(edu or {}).get("degree"), (edu or {}).get("institution"), (edu or {}).get("year")] if p)
        if text:
            lines.append(Evidence(kind="education", text=text))
    if missing_required:
        lines.append(Evidence(kind="gap", text=", ".join(missing_required[:6])))
    return lines


def _detail(db: Session, application: Application, candidate: Candidate) -> ScreeningDetail:
    entry = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "application", AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    details = (entry.details or {}) if entry else {}
    parsed = candidate.parsed_fields or {}
    missing = [str(s) for s in (application.missing_skills or details.get("missing_skills") or [])]
    missing_set = {s.lower() for s in missing}
    matched = [str(s) for s in (parsed.get("skills") or []) if str(s).lower() not in missing_set]
    missing_required = [str(s) for s in (details.get("missing_required_skills") or [])]
    history = parsed.get("work_history") or []
    score = application.composite_score if application.composite_score is not None else application.match_score
    return ScreeningDetail(
        application_id=application.id,
        score=_num(score),
        recommendation=details.get("recommendation"),
        breakdown=_breakdown(details) if entry else {"resume_match": _num(application.match_score)},
        matched_skills=matched,
        missing_skills=missing,
        missing_required_skills=missing_required,
        experience_years=_num(parsed.get("total_experience_years")),
        current_title=(history[0] or {}).get("title") if history else None,
        evidence=_evidence(parsed, matched, missing_required),
        screened_at=entry.created_at if entry else None,
        auto_shortlist=_auto_shortlist_info(db, application),
    )


@router.get("/details", response_model=list[ScreeningDetail])
def screening_details(
    application_ids: list[uuid.UUID] = Query(..., description="Up to 50 applications (one table page)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(application_ids) > 50:
        raise HTTPException(status_code=400, detail="Ask for 50 applications or fewer at a time")
    rows = (
        db.query(Application, Candidate)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .filter(Application.id.in_(application_ids))
        .all()
    )
    return [_detail(db, application, candidate) for application, candidate in rows]


# ---- S7 rejection reasons ----


class RejectReason(BaseModel):
    code: str
    label: str
    label_i18n: dict[str, str] = {}


@router.get("/reject-reasons", response_model=list[RejectReason])
def reject_reasons(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The company's own "Rejection Reason" master (Settings -> Lists); a sensible starter
    list until one is set up."""
    now = datetime.now(timezone.utc)
    values = (
        db.query(MasterValue)
        .filter(MasterValue.type_code == "rejection_reason", MasterValue.is_active.is_(True))
        .filter((MasterValue.effective_from.is_(None)) | (MasterValue.effective_from <= now))
        .filter((MasterValue.effective_to.is_(None)) | (MasterValue.effective_to >= now))
        .order_by(MasterValue.sort, MasterValue.code)
        .all()
    )
    if values:
        out = []
        for v in values:
            labels = {k: str(val) for k, val in (v.label_i18n or {}).items() if val}
            out.append(RejectReason(code=v.code, label=labels.get("en") or next(iter(labels.values()), v.code), label_i18n=labels))
        return out
    return [RejectReason(code=code, label=label) for code, label in DEFAULT_REJECT_REASONS]


# ---- K F1 undo an auto-shortlist inside its window ----


class UndoResult(BaseModel):
    application_id: uuid.UUID
    status: str


@router.post("/applications/{application_id}/undo-auto-shortlist", response_model=UndoResult)
def undo_auto_shortlist(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_not_on_hold(application)
    info = _auto_shortlist_info(db, application)
    if info is None:
        raise HTTPException(status_code=400, detail="This candidate was shortlisted by a person, not automatically")
    if not info.can_undo:
        raise HTTPException(status_code=409, detail="The undo window has closed for this candidate")
    previous = application.status
    application.status = "screened"
    db.commit()
    log_action(db, "application", application.id, AUTO_SHORTLIST_UNDONE, current_user.email,
               {"previous_status": previous, "new_status": "screened", "undo_until": info.undo_until.isoformat()})
    return UndoResult(application_id=application.id, status=application.status)
