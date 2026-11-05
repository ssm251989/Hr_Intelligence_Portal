"""Performance / compensation / talent API (docs/HRMS_COMPLETE_SPEC.txt Part 10).

HR/manager endpoints are gated by `performance.*` / `compensation.planning.*`. Employee
self-service lives under `/me/...`, gated by `performance.self.*` and always resolved to
the caller's OWN employee record -- never an id from the request.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.core_hr.context import manager_of
from app.models.core_hr import Employee
from app.models.performance import (
    CalibrationEntry,
    CalibrationSession,
    CompensationBudget,
    CompensationCycle,
    CompensationProposal,
    Feedback,
    Goal,
    InternalOpportunity,
    OneOnOne,
    RatingScale,
    Review,
    ReviewCycle,
    ReviewNomination,
    SalaryBand,
)
from app.models.user import User
from app.performance import calibration, compensation, goals, reviews, talent
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])


def _get(db: Session, model, row_id: UUID, label: str):
    tenant = require_current_tenant()
    row = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.id == row_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _my_employee(db: Session, user: User) -> Employee:
    tenant = require_current_tenant()
    employee = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail="Your login isn't linked to an employee record yet. Ask HR to link it.")
    return employee


# ---- goals ----


class GoalCreate(BaseModel):
    title: str
    level: str = "individual"
    owner_employee_id: Optional[UUID] = None
    parent_goal_id: Optional[UUID] = None
    weightage: float = 0
    kpi: Optional[dict] = None
    cycle_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    description: Optional[str] = None
    external_ref: Optional[str] = None
    due_date: Optional[date] = None


class CheckinCreate(BaseModel):
    progress_pct: Optional[float] = None
    current_value: Optional[float] = None
    confidence: Optional[int] = None
    comment: Optional[str] = None


@router.post("/goals", status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.create"))):
    try:
        return goals.goal_to_dict(goals.create_goal(db, require_current_tenant(), **payload.model_dump()))
    except goals.GoalValidationError as exc:
        raise _bad(exc)


@router.get("/goals")
def list_goals(employee_id: Optional[UUID] = None, cycle_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.view"))):
    tenant = require_current_tenant()
    query = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id)
    if employee_id:
        query = query.filter(Goal.owner_employee_id == employee_id)
    if cycle_id:
        query = query.filter(Goal.cycle_id == cycle_id)
    return [goals.goal_to_dict(g) for g in query.order_by(Goal.created_at.asc()).all()]


@router.get("/goals/tree")
def goal_tree(root_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.view"))):
    return goals.alignment_tree(db, require_current_tenant(), root_id)


@router.get("/goals/weightage/{employee_id}")
def goal_weightage(employee_id: UUID, cycle_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.view"))):
    return goals.validate_weightage(db, require_current_tenant(), employee_id, cycle_id=cycle_id)


@router.post("/goals/{goal_id}/checkins", status_code=201)
def goal_checkin(goal_id: UUID, payload: CheckinCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.edit"))):
    goal = _get(db, Goal, goal_id, "Goal")
    try:
        goals.check_in(db, require_current_tenant(), goal, actor=current_user.email, **payload.model_dump())
    except goals.GoalValidationError as exc:
        raise _bad(exc)
    return goals.goal_to_dict(goal)


class IntegrationProgress(BaseModel):
    external_ref: str
    current_value: Optional[float] = None
    progress_pct: Optional[float] = None


@router.post("/goals/integration-progress")
def integration_progress(payload: IntegrationProgress, db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.edit"))):
    """Called by a connection's inbound webhook handler (Jira/CRM) with a service identity."""
    try:
        rows = goals.apply_integration_progress(db, require_current_tenant(), **payload.model_dump())
    except goals.GoalValidationError as exc:
        raise _bad(exc)
    return {"goals_updated": len(rows)}


# ---- continuous performance ----


class FeedbackCreate(BaseModel):
    to_employee_id: UUID
    kind: str = "feedback"
    visibility: str = "private"
    text_body: str
    value_code: Optional[str] = None


@router.post("/me/feedback", status_code=201)
def give_feedback(payload: FeedbackCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.edit"))):
    me = _my_employee(db, current_user)
    if payload.to_employee_id == me.id:
        raise HTTPException(status_code=400, detail="You can't give feedback to yourself")
    row = Feedback(tenant_id=require_current_tenant().tenant_id, from_employee_id=me.id, **payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.get("/me/feedback")
def my_feedback(db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    """What the employee received. Private feedback shows its sender only to the recipient."""
    me = _my_employee(db, current_user)
    rows = db.query(Feedback).filter(Feedback.tenant_id == me.tenant_id, Feedback.to_employee_id == me.id).order_by(Feedback.created_at.desc()).all()
    return [{"id": str(f.id), "kind": f.kind, "visibility": f.visibility, "text": f.text_body, "from_employee_id": str(f.from_employee_id), "value_code": f.value_code} for f in rows]


@router.get("/praise")
def public_praise(db: Session = Depends(get_db), current_user: User = Depends(require("performance.feedback.view"))):
    tenant = require_current_tenant()
    rows = db.query(Feedback).filter(Feedback.tenant_id == tenant.tenant_id, Feedback.kind == "praise", Feedback.visibility == "public").order_by(Feedback.created_at.desc()).limit(100).all()
    return [{"id": str(f.id), "from_employee_id": str(f.from_employee_id), "to_employee_id": str(f.to_employee_id), "text": f.text_body, "value_code": f.value_code} for f in rows]


class OneOnOneCreate(BaseModel):
    employee_id: UUID
    manager_employee_id: UUID
    scheduled_for: Optional[str] = None
    agenda: list = []


class OneOnOneUpdate(BaseModel):
    shared_notes: Optional[str] = None
    manager_private_notes: Optional[str] = None
    agenda: Optional[list] = None
    action_items: Optional[list] = None


@router.post("/one-on-ones", status_code=201)
def create_one_on_one(payload: OneOnOneCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.one_on_one.create"))):
    row = OneOnOne(tenant_id=require_current_tenant().tenant_id, employee_id=payload.employee_id, manager_employee_id=payload.manager_employee_id,
                   scheduled_for=payload.scheduled_for, agenda_json=payload.agenda)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.patch("/one-on-ones/{row_id}")
def update_one_on_one(row_id: UUID, payload: OneOnOneUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.one_on_one.edit"))):
    row = _get(db, OneOnOne, row_id, "1:1")
    if payload.shared_notes is not None:
        row.shared_notes = payload.shared_notes
    if payload.manager_private_notes is not None:
        row.manager_private_notes = payload.manager_private_notes
    if payload.agenda is not None:
        row.agenda_json = payload.agenda
    if payload.action_items is not None:
        row.action_items_json = payload.action_items
    db.commit()
    return {"id": str(row.id)}


@router.get("/me/one-on-ones")
def my_one_on_ones(db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    me = _my_employee(db, current_user)
    rows = db.query(OneOnOne).filter(OneOnOne.tenant_id == me.tenant_id, OneOnOne.employee_id == me.id).all()
    # manager_private_notes deliberately omitted
    return [{"id": str(o.id), "scheduled_for": o.scheduled_for.isoformat() if o.scheduled_for else None, "agenda": o.agenda_json,
             "shared_notes": o.shared_notes, "action_items": o.action_items_json} for o in rows]


@router.get("/manager-nudges")
def manager_nudges(manager_employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.one_on_one.view"))):
    """Reportees with no 1:1 in the last 30 days and no feedback given in the last 60."""
    from datetime import datetime, timedelta, timezone

    from app.models.core_hr import EmploymentRecord

    tenant = require_current_tenant()
    today = datetime.now(timezone.utc)
    reportee_ids = {
        r.employee_id for r in db.query(EmploymentRecord).filter(
            EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.manager_employee_id == manager_employee_id, EmploymentRecord.effective_to.is_(None),
        ).all()
    }
    nudges = []
    for employee_id in reportee_ids:
        last_1on1 = db.query(OneOnOne).filter(OneOnOne.tenant_id == tenant.tenant_id, OneOnOne.employee_id == employee_id, OneOnOne.created_at >= today - timedelta(days=30)).first()
        last_fb = db.query(Feedback).filter(Feedback.tenant_id == tenant.tenant_id, Feedback.from_employee_id == manager_employee_id, Feedback.to_employee_id == employee_id, Feedback.created_at >= today - timedelta(days=60)).first()
        reasons = ([] if last_1on1 else ["no 1:1 in 30 days"]) + ([] if last_fb else ["no feedback in 60 days"])
        if reasons:
            nudges.append({"employee_id": str(employee_id), "reasons": reasons})
    return nudges


# ---- rating scales + review cycles ----


class RatingScaleCreate(BaseModel):
    code: str
    name: str
    points: list[dict]


@router.post("/rating-scales", status_code=201)
def create_rating_scale(payload: RatingScaleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.configure"))):
    if not payload.points or any("value" not in p or "label" not in p for p in payload.points):
        raise HTTPException(status_code=400, detail="Each point needs a value and a label")
    row = RatingScale(tenant_id=require_current_tenant().tenant_id, code=payload.code, name=payload.name, points_json=sorted(payload.points, key=lambda p: p["value"]))
    db.add(row)
    db.commit()
    return {"id": str(row.id), "code": row.code, "points": row.points_json}


@router.get("/rating-scales")
def list_rating_scales(db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.view"))):
    tenant = require_current_tenant()
    return [{"id": str(r.id), "code": r.code, "name": r.name, "points": r.points_json} for r in db.query(RatingScale).filter(RatingScale.tenant_id == tenant.tenant_id).all()]


class CycleCreate(BaseModel):
    name: str
    cycle_type: str
    period_start: date
    period_end: date
    stages: list[dict]
    sections: list[dict]
    rating_scale_id: Optional[UUID] = None
    eligibility_jsonlogic: Optional[dict] = None
    anonymity: Optional[dict] = None
    reminder_days_before: Optional[list[int]] = None


@router.post("/cycles", status_code=201)
def create_cycle(payload: CycleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.configure"))):
    try:
        return reviews.cycle_to_dict(reviews.create_cycle(db, require_current_tenant(), **payload.model_dump()))
    except reviews.ReviewCycleError as exc:
        raise _bad(exc)


@router.get("/cycles")
def list_cycles(db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.view"))):
    tenant = require_current_tenant()
    return [reviews.cycle_to_dict(c) for c in db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tenant.tenant_id).order_by(ReviewCycle.period_start.desc()).all()]


@router.get("/cycles/{cycle_id}/eligibility-preview")
def eligibility_preview(cycle_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.view"))):
    """Simulate before launch (Part 14 section 7)."""
    cycle = _get(db, ReviewCycle, cycle_id, "Cycle")
    employees = reviews.eligible_employees(db, require_current_tenant(), cycle)
    return {"eligible_count": len(employees), "employees": [{"id": str(e.id), "employee_code": e.employee_code, "name": e.first_name} for e in employees[:200]]}


@router.post("/cycles/{cycle_id}/launch")
def launch_cycle(cycle_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.configure"))):
    try:
        result = reviews.launch_cycle(db, require_current_tenant(), _get(db, ReviewCycle, cycle_id, "Cycle"))
    except reviews.ReviewCycleError as exc:
        raise _bad(exc)
    log_action(db, "review_cycle", cycle_id, "review_cycle_launched", current_user.email, result)
    return result


@router.post("/cycles/{cycle_id}/send-reminders")
def send_reminders(cycle_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.cycle.configure"))):
    return {"reminders_sent": reviews.send_due_reminders(db, require_current_tenant(), _get(db, ReviewCycle, cycle_id, "Cycle"))}


class NominationCreate(BaseModel):
    employee_id: UUID
    nominee_employee_id: UUID


@router.post("/cycles/{cycle_id}/nominations", status_code=201)
def nominate(cycle_id: UUID, payload: NominationCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.review.create"))):
    try:
        row = reviews.nominate_peer(db, require_current_tenant(), _get(db, ReviewCycle, cycle_id, "Cycle"), **payload.model_dump())
    except reviews.ReviewCycleError as exc:
        raise _bad(exc)
    return {"id": str(row.id), "status": row.status}


class NominationDecision(BaseModel):
    approve: bool


@router.post("/nominations/{nomination_id}/decision")
def decide_nomination(nomination_id: UUID, payload: NominationDecision, db: Session = Depends(get_db), current_user: User = Depends(require("performance.review.edit"))):
    row = reviews.decide_nomination(db, require_current_tenant(), _get(db, ReviewNomination, nomination_id, "Nomination"), approve=payload.approve, actor=current_user.email)
    return {"id": str(row.id), "status": row.status}


class ReviewSubmit(BaseModel):
    section_scores: dict = {}
    goal_ratings: dict = {}
    answers: dict = {}
    comments: Optional[str] = None
    final: bool = True


def _submit(db: Session, review: Review, payload: ReviewSubmit) -> dict:
    try:
        return reviews.review_to_dict(reviews.submit_review(db, require_current_tenant(), review, **payload.model_dump()))
    except reviews.ReviewCycleError as exc:
        raise _bad(exc)


@router.get("/me/reviews/to-write")
def my_pending_reviews(db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    me = _my_employee(db, current_user)
    rows = db.query(Review).filter(Review.tenant_id == me.tenant_id, Review.reviewer_employee_id == me.id, Review.status != "submitted").all()
    return [reviews.review_to_dict(r) for r in rows]


@router.post("/me/reviews/{review_id}")
def submit_my_review(review_id: UUID, payload: ReviewSubmit, db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.edit"))):
    me = _my_employee(db, current_user)
    review = _get(db, Review, review_id, "Review")
    if review.reviewer_employee_id != me.id:
        raise HTTPException(status_code=403, detail="You are not the reviewer on this review")
    return _submit(db, review, payload)


@router.post("/me/reviews/{review_id}/ai-draft")
def ai_draft_my_review(review_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.edit"))):
    me = _my_employee(db, current_user)
    review = _get(db, Review, review_id, "Review")
    if review.reviewer_employee_id != me.id:
        raise HTTPException(status_code=403, detail="You are not the reviewer on this review")
    return reviews.review_to_dict(reviews.draft_review_summary(db, require_current_tenant(), review))


@router.get("/me/cycles/{cycle_id}/results")
def my_results(cycle_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    me = _my_employee(db, current_user)
    return reviews.reviews_for_viewer(db, require_current_tenant(), _get(db, ReviewCycle, cycle_id, "Cycle"), me.id, viewer="employee")


@router.get("/cycles/{cycle_id}/employees/{employee_id}/results")
def employee_results(cycle_id: UUID, employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.review.view"))):
    tenant = require_current_tenant()
    cycle = _get(db, ReviewCycle, cycle_id, "Cycle")
    viewer = "hr" if has_permission(db, tenant, current_user, "performance.review.view_sensitive") else "manager"
    return reviews.reviews_for_viewer(db, tenant, cycle, employee_id, viewer=viewer)


@router.post("/reviews/{review_id}/submit")
def submit_review_as_admin(review_id: UUID, payload: ReviewSubmit, db: Session = Depends(get_db), current_user: User = Depends(require("performance.review.edit"))):
    return _submit(db, _get(db, Review, review_id, "Review"), payload)


# ---- calibration ----


class CalibrationOpen(BaseModel):
    name: str
    distribution: dict = {}
    tolerance_pct: float = 5
    enforcement: str = "soft"


@router.post("/cycles/{cycle_id}/calibration", status_code=201)
def open_calibration(cycle_id: UUID, payload: CalibrationOpen, db: Session = Depends(get_db), current_user: User = Depends(require("performance.calibration.create"))):
    try:
        session = calibration.open_session(db, require_current_tenant(), _get(db, ReviewCycle, cycle_id, "Cycle"), **payload.model_dump())
    except calibration.CalibrationError as exc:
        raise _bad(exc)
    return {"id": str(session.id)}


@router.get("/calibration/{session_id}")
def calibration_view(session_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.calibration.view"))):
    tenant = require_current_tenant()
    session = _get(db, CalibrationSession, session_id, "Calibration session")
    return {
        "status": session.status, "enforcement": session.enforcement,
        "entries": [{"id": str(e.id), "employee_id": str(e.employee_id), "original_rating": float(e.original_rating) if e.original_rating is not None else None,
                     "performance_rating": float(e.performance_rating) if e.performance_rating is not None else None, "potential_rating": e.potential_rating}
                    for e in calibration.entries(db, tenant, session)],
        "guideline": calibration.guideline_check(db, tenant, session),
        "nine_box": calibration.nine_box(db, tenant, session),
        "normalisation": calibration.normalisation_report(db, tenant, session),
    }


class CalibrationAdjust(BaseModel):
    reason: str
    performance_rating: Optional[float] = None
    potential_rating: Optional[int] = None


@router.post("/calibration/entries/{entry_id}/adjust")
def calibration_adjust(entry_id: UUID, payload: CalibrationAdjust, db: Session = Depends(get_db), current_user: User = Depends(require("performance.calibration.edit"))):
    tenant = require_current_tenant()
    entry = _get(db, CalibrationEntry, entry_id, "Calibration entry")
    try:
        calibration.adjust(db, tenant, entry, actor=current_user.email, **payload.model_dump())
    except calibration.CalibrationError as exc:
        raise _bad(exc)
    return {"id": str(entry.id), "audit": calibration.audit_trail(db, tenant, entry)}


@router.post("/calibration/{session_id}/finalize")
def calibration_finalize(session_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.calibration.approve"))):
    try:
        return calibration.finalize(db, require_current_tenant(), _get(db, CalibrationSession, session_id, "Calibration session"), actor=current_user.email)
    except calibration.CalibrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---- compensation ----


class SalaryBandUpsert(BaseModel):
    grade: str
    location_id: Optional[UUID] = None
    currency: str
    min_amount: float
    mid_amount: float
    max_amount: float


@router.put("/compensation/salary-bands")
def upsert_band(payload: SalaryBandUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.configure"))):
    if not payload.min_amount <= payload.mid_amount <= payload.max_amount:
        raise HTTPException(status_code=400, detail="Band must satisfy min <= mid <= max")
    tenant = require_current_tenant()
    band = db.query(SalaryBand).filter(SalaryBand.tenant_id == tenant.tenant_id, SalaryBand.grade == payload.grade, SalaryBand.currency == payload.currency,
                                       SalaryBand.location_id == payload.location_id if payload.location_id else SalaryBand.location_id.is_(None)).first()
    if band is None:
        band = SalaryBand(tenant_id=tenant.tenant_id, grade=payload.grade, location_id=payload.location_id, currency=payload.currency, min_amount=0, mid_amount=0, max_amount=0)
        db.add(band)
    band.min_amount, band.mid_amount, band.max_amount = payload.min_amount, payload.mid_amount, payload.max_amount
    db.commit()
    return {"id": str(band.id)}


@router.get("/compensation/salary-bands")
def list_bands(db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view_sensitive"))):
    tenant = require_current_tenant()
    return [{"id": str(b.id), "grade": b.grade, "location_id": str(b.location_id) if b.location_id else None, "currency": b.currency,
             "min": float(b.min_amount), "mid": float(b.mid_amount), "max": float(b.max_amount)} for b in db.query(SalaryBand).filter(SalaryBand.tenant_id == tenant.tenant_id).all()]


class MeritMatrixUpsert(BaseModel):
    code: str
    name: str
    cells: list[dict]
    bonus_rules: dict = {}


@router.put("/compensation/merit-matrices")
def upsert_merit_matrix(payload: MeritMatrixUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.configure"))):
    try:
        matrix = compensation.upsert_matrix(db, require_current_tenant(), **payload.model_dump())
    except compensation.CompensationError as exc:
        raise _bad(exc)
    return {"id": str(matrix.id), "code": matrix.code}


class MeritLookup(BaseModel):
    matrix_code: str
    rating: float
    compa_ratio: float


@router.post("/compensation/merit-matrices/lookup")
def merit_lookup(payload: MeritLookup, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view"))):
    from app.models.performance import MeritMatrix

    tenant = require_current_tenant()
    matrix = db.query(MeritMatrix).filter(MeritMatrix.tenant_id == tenant.tenant_id, MeritMatrix.code == payload.matrix_code).first()
    if matrix is None:
        raise HTTPException(status_code=404, detail="Merit matrix not found")
    found = compensation.merit_range(matrix, payload.rating, payload.compa_ratio)
    return {"range": list(found) if found else None}


class CompCycleCreate(BaseModel):
    name: str
    effective_date: date
    currency: str
    review_cycle_id: Optional[UUID] = None
    merit_matrix_id: Optional[UUID] = None


@router.post("/compensation/cycles", status_code=201)
def create_comp_cycle(payload: CompCycleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.configure"))):
    row = CompensationCycle(tenant_id=require_current_tenant().tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


class BudgetUpsert(BaseModel):
    department_id: Optional[UUID] = None
    merit_pool: float = 0
    bonus_pool: float = 0


@router.put("/compensation/cycles/{cycle_id}/budgets")
def upsert_budget(cycle_id: UUID, payload: BudgetUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.configure"))):
    tenant = require_current_tenant()
    _get(db, CompensationCycle, cycle_id, "Compensation cycle")
    budget = db.query(CompensationBudget).filter(CompensationBudget.tenant_id == tenant.tenant_id, CompensationBudget.comp_cycle_id == cycle_id,
                                                 CompensationBudget.department_id == payload.department_id).first()
    if budget is None:
        budget = CompensationBudget(tenant_id=tenant.tenant_id, comp_cycle_id=cycle_id, department_id=payload.department_id)
        db.add(budget)
    budget.merit_pool, budget.bonus_pool = payload.merit_pool, payload.bonus_pool
    db.commit()
    return {"id": str(budget.id)}


class WorksheetBuild(BaseModel):
    employee_ids: list[UUID]


@router.post("/compensation/cycles/{cycle_id}/worksheet")
def build_worksheet(cycle_id: UUID, payload: WorksheetBuild, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.create"))):
    rows = compensation.build_worksheet(db, require_current_tenant(), _get(db, CompensationCycle, cycle_id, "Compensation cycle"), payload.employee_ids)
    return [compensation.proposal_to_dict(p) for p in rows]


@router.get("/compensation/cycles/{cycle_id}/worksheet")
def get_worksheet(cycle_id: UUID, department_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view"))):
    tenant = require_current_tenant()
    comp_cycle = _get(db, CompensationCycle, cycle_id, "Compensation cycle")
    query = db.query(CompensationProposal).filter(CompensationProposal.tenant_id == tenant.tenant_id, CompensationProposal.comp_cycle_id == cycle_id)
    if department_id:
        query = query.filter(CompensationProposal.department_id == department_id)
    return {"proposals": [compensation.proposal_to_dict(p) for p in query.all()], "budget": compensation.budget_usage(db, tenant, comp_cycle, department_id)}


class ProposalUpdate(BaseModel):
    merit_pct: Optional[float] = None
    bonus_amount: Optional[float] = None
    promotion_to_grade: Optional[str] = None
    justification: Optional[str] = None


@router.patch("/compensation/proposals/{proposal_id}")
def update_proposal(proposal_id: UUID, payload: ProposalUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.edit"))):
    proposal = _get(db, CompensationProposal, proposal_id, "Proposal")
    try:
        compensation.update_proposal(proposal, **payload.model_dump())
    except compensation.CompensationError as exc:
        raise _bad(exc)
    db.commit()
    return compensation.proposal_to_dict(proposal)


@router.post("/compensation/proposals/{proposal_id}/submit")
def submit_proposal(proposal_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.edit"))):
    try:
        proposal = compensation.submit_proposal(db, require_current_tenant(), _get(db, CompensationProposal, proposal_id, "Proposal"), actor=current_user.email, actor_user_id=current_user.id)
    except compensation.CompensationError as exc:
        raise _bad(exc)
    return compensation.proposal_to_dict(proposal)


class ProposalDecision(BaseModel):
    approve: bool
    letter_template_key: Optional[str] = None


@router.post("/compensation/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: UUID, payload: ProposalDecision, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.approve"))):
    tenant = require_current_tenant()
    try:
        proposal = compensation.decide_proposal(db, tenant, _get(db, CompensationProposal, proposal_id, "Proposal"), approve=payload.approve, actor=current_user.email)
        result = compensation.apply_proposal(db, tenant, proposal, actor=current_user.email, letter_template_key=payload.letter_template_key) if payload.approve else {}
    except compensation.CompensationError as exc:
        raise _bad(exc)
    log_action(db, "compensation_proposal", proposal_id, "compensation_proposal_decided", current_user.email, {"approve": payload.approve})
    return {**compensation.proposal_to_dict(proposal), **result}


@router.get("/compensation/cycles/{cycle_id}/export", response_class=PlainTextResponse)
def export_comp_cycle(cycle_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.export"))):
    return PlainTextResponse(compensation.export_csv(db, require_current_tenant(), _get(db, CompensationCycle, cycle_id, "Compensation cycle")), media_type="text/csv")


@router.get("/compensation/compa-ratio/{employee_id}")
def compa_ratio(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view_sensitive"))):
    from app.core_hr import lifecycle

    tenant = require_current_tenant()
    comp = compensation.current_compensation(db, tenant, employee_id)
    employment = lifecycle.get_current_employment(db, tenant, employee_id)
    if comp is None or employment is None or not employment.grade:
        raise HTTPException(status_code=404, detail="No current compensation or grade for this employee")
    band = compensation.find_band(db, tenant, grade=employment.grade, location_id=employment.location_id, currency=comp.currency)
    if band is None:
        raise HTTPException(status_code=404, detail=f"No salary band for grade {employment.grade}")
    return {"compa_ratio": compensation.compa_ratio(float(comp.base_amount), band), "position": compensation.band_position(float(comp.base_amount), band)}


# ---- talent & succession ----


class TalentUpdate(BaseModel):
    aspirations: Optional[str] = None
    mobility_json: Optional[dict] = None
    career_path_json: Optional[list] = None


@router.get("/talent/{employee_id}")
def get_talent(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.talent.view"))):
    profile = talent.get_or_create_profile(db, require_current_tenant(), employee_id)
    return {"employee_id": str(employee_id), "aspirations": profile.aspirations, "mobility": profile.mobility_json, "career_path": profile.career_path_json,
            "flight_risk": talent.effective_flight_risk(profile), "flight_risk_manager": profile.flight_risk_manager,
            "flight_risk_ai_estimate": float(profile.flight_risk_ai) if profile.flight_risk_ai is not None else None}


@router.patch("/talent/{employee_id}")
def update_talent(employee_id: UUID, payload: TalentUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.talent.edit"))):
    profile = talent.update_profile(db, talent.get_or_create_profile(db, require_current_tenant(), employee_id), **payload.model_dump())
    return {"employee_id": str(profile.employee_id)}


class FlightRisk(BaseModel):
    level: str
    notes: Optional[str] = None


@router.post("/talent/{employee_id}/flight-risk")
def set_flight_risk(employee_id: UUID, payload: FlightRisk, db: Session = Depends(get_db), current_user: User = Depends(require("performance.talent.edit"))):
    try:
        profile = talent.set_manager_flight_risk(db, talent.get_or_create_profile(db, require_current_tenant(), employee_id), **payload.model_dump())
    except talent.TalentError as exc:
        raise _bad(exc)
    return {"flight_risk": talent.effective_flight_risk(profile)}


class SuccessorAdd(BaseModel):
    employee_id: UUID
    readiness: str
    rank: int = 1
    development_actions: list = []


@router.post("/succession/positions/{position_id}/successors", status_code=201)
def add_successor(position_id: UUID, payload: SuccessorAdd, db: Session = Depends(get_db), current_user: User = Depends(require("performance.succession.edit"))):
    tenant = require_current_tenant()
    try:
        slate = talent.get_or_create_slate(db, tenant, position_id)
        talent.add_successor(db, tenant, slate, assessed_by=current_user.email, **payload.model_dump())
    except talent.TalentError as exc:
        raise _bad(exc)
    return talent.slate_readiness(db, tenant, slate)


@router.get("/succession/positions/{position_id}")
def get_slate(position_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("performance.succession.view"))):
    tenant = require_current_tenant()
    try:
        return talent.slate_readiness(db, tenant, talent.get_or_create_slate(db, tenant, position_id))
    except talent.TalentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/succession/critical-positions")
def critical_positions(db: Session = Depends(get_db), current_user: User = Depends(require("performance.succession.view"))):
    return talent.critical_positions_report(db, require_current_tenant())


class OpportunityCreate(BaseModel):
    type: str
    title: str
    description: Optional[str] = None
    skills: list[str] = []
    department_id: Optional[UUID] = None
    position_id: Optional[UUID] = None
    closes_on: Optional[date] = None


@router.post("/marketplace", status_code=201)
def post_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db), current_user: User = Depends(require("performance.marketplace.create"))):
    try:
        row = talent.post_opportunity(db, require_current_tenant(), posted_by=current_user.email, **payload.model_dump())
    except talent.TalentError as exc:
        raise _bad(exc)
    return {"id": str(row.id)}


@router.get("/marketplace")
def list_opportunities(db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    tenant = require_current_tenant()
    rows = db.query(InternalOpportunity).filter(InternalOpportunity.tenant_id == tenant.tenant_id, InternalOpportunity.status == "open").order_by(InternalOpportunity.created_at.desc()).all()
    return [{"id": str(o.id), "type": o.type, "title": o.title, "description": o.description, "skills": o.skills_json, "closes_on": o.closes_on.isoformat() if o.closes_on else None} for o in rows]


class InternalApply(BaseModel):
    note: Optional[str] = None


@router.post("/me/marketplace/{opportunity_id}/apply", status_code=201)
def apply_opportunity(opportunity_id: UUID, payload: InternalApply, db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.edit"))):
    me = _my_employee(db, current_user)
    try:
        row = talent.apply_internal(db, require_current_tenant(), _get(db, InternalOpportunity, opportunity_id, "Opportunity"), employee_id=me.id, note=payload.note)
    except talent.TalentError as exc:
        raise _bad(exc)
    return {"id": str(row.id), "status": row.status, "manager_employee_id": str(manager_of(db, require_current_tenant(), me.id) or "") or None}
