"""Part 15 step 15.6 (spec section L, F1-F7): read-only helpers for the Performance,
Compensation and Succession pages. They only JOIN what the Part 10 endpoints already store
with people's names (the original endpoints return bare employee ids) -- no new tables, no
writes. Every write the pages make still goes through /api/v1/performance/*.

- GET /api/v1/ui/performance/me                        my goals tree (company > team > me),
                                                        check-in nudge, reviews I must write
- GET /api/v1/ui/performance/reviews/{id}/form          one review + its cycle's sections,
                                                        rating scale and the person's goals
- GET /api/v1/ui/performance/team                       manager table + 9-box placement
- GET /api/v1/ui/performance/people?q=                  name search for pickers
- GET /api/v1/ui/performance/compensation/cycles        pay-review cycles
- GET /api/v1/ui/performance/compensation/cycles/{id}/grid  worksheet rows with names,
                                                        band and budget (field security applied)
- GET /api/v1/ui/performance/succession                 critical roles + named successors

Every query filters on the caller's company (tenant_id) explicitly.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.core_hr import Department, Employee, EmploymentRecord, Position
from app.models.performance import (
    CompensationCycle,
    CompensationProposal,
    Goal,
    GoalCheckin,
    RatingScale,
    Review,
    ReviewCycle,
    SalaryBand,
    SuccessionCandidate,
    SuccessionSlate,
    TalentProfile,
)
from app.models.user import User
from app.platform.iam.authz import effective_permissions, require
from app.platform.iam.field_security import apply_field_security
from app.platform.iam.org_scope import direct_reportees, employee_ids_in_scope, my_employee_id
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/performance", tags=["ui-performance"])

CHECKIN_EVERY_DAYS = 30
NINE_BOX_KEY = "nine_box"  # stored inside talent_profiles.mobility_json via PATCH /talent/{id}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _f(value) -> Optional[float]:
    return float(value) if value is not None else None


def _name(e: Optional[Employee]) -> str:
    if e is None:
        return ""
    first = e.preferred_name or e.first_name or ""
    return f"{first} {e.last_name or ''}".strip()


def _employees(db: Session, tenant_id, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.query(Employee).filter(Employee.tenant_id == tenant_id, Employee.id.in_(list(ids))).all()
    return {r.id: r for r in rows}


def _current_jobs(db: Session, tenant_id, ids) -> dict:
    """employee_id -> current EmploymentRecord (effective_to NULL or in the future)."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    today = datetime.now(timezone.utc).date()
    rows = (
        db.query(EmploymentRecord)
        .filter(EmploymentRecord.tenant_id == tenant_id, EmploymentRecord.employee_id.in_(list(ids)), EmploymentRecord.effective_from <= today)
        .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= today))
        .order_by(EmploymentRecord.effective_from.asc())
        .all()
    )
    return {r.employee_id: r for r in rows}


def _departments(db: Session, tenant_id) -> dict:
    return {d.id: d.name for d in db.query(Department).filter(Department.tenant_id == tenant_id).all()}


def _last_checkins(db: Session, tenant_id, goal_ids) -> dict:
    goal_ids = list({g for g in goal_ids if g})
    if not goal_ids:
        return {}
    latest: dict = {}
    for c in db.query(GoalCheckin).filter(GoalCheckin.tenant_id == tenant_id, GoalCheckin.goal_id.in_(goal_ids)).all():
        if c.created_at and (c.goal_id not in latest or c.created_at > latest[c.goal_id]):
            latest[c.goal_id] = c.created_at
    return latest


def _checkin_due(goal: Goal, last) -> bool:
    if goal.status != "active":
        return False
    since = last or goal.created_at
    if since is None:
        return True
    return since < datetime.now(timezone.utc) - timedelta(days=CHECKIN_EVERY_DAYS)


def _scale_points(db: Session, cycle: Optional[ReviewCycle]) -> Optional[list]:
    if cycle is None or not cycle.rating_scale_id:
        return None
    scale = db.get(RatingScale, cycle.rating_scale_id)
    if scale is None or scale.tenant_id != cycle.tenant_id or not scale.points_json:
        return None
    return sorted(({"value": float(p["value"]), "label": p.get("label")} for p in scale.points_json), key=lambda p: p["value"])


def _performance_band(points: Optional[list], rating: Optional[float]) -> Optional[int]:
    if rating is None:
        return None
    values = [p["value"] for p in points] if points else [1, 2, 3, 4, 5]
    low, high = min(values), max(values)
    third = (high - low) / 3 or 1
    return 1 if rating < low + third else 2 if rating < low + 2 * third else 3


def _active_cycle(db: Session, tenant_id) -> Optional[ReviewCycle]:
    return (
        db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tenant_id, ReviewCycle.status == "active")
        .order_by(ReviewCycle.period_start.desc()).first()
    ) or db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tenant_id).order_by(ReviewCycle.period_start.desc()).first()


def _goal_row(g: Goal, last, owners: dict, me_id) -> dict:
    return {
        "id": str(g.id), "title": g.title, "description": g.description, "level": g.level,
        "parent_goal_id": str(g.parent_goal_id) if g.parent_goal_id else None,
        "owner_name": _name(owners.get(g.owner_employee_id)) or None, "is_mine": bool(me_id and g.owner_employee_id == me_id),
        "progress_pct": float(g.progress_pct or 0), "confidence": g.confidence, "status": g.status,
        "weightage": float(g.weightage or 0), "due_date": _iso(g.due_date), "last_checkin_at": _iso(last),
        "checkin_due": _checkin_due(g, last),
    }


# ---- /performance (F1, F2, my reviews) ----


@router.get("/me")
def my_performance(db: Session = Depends(get_db), current_user: User = Depends(require("performance.self.view"))):
    tenant = require_current_tenant()
    tid = tenant.tenant_id
    me = my_employee_id(db, tenant, current_user)
    team_ids = direct_reportees(db, tenant, me) if me else set()

    # Company / department / team goals are shared; individual goals only mine + my team's.
    goals = db.query(Goal).filter(Goal.tenant_id == tid, Goal.status != "cancelled").order_by(Goal.created_at.asc()).all()
    visible_people = ({me} if me else set()) | team_ids
    goals = [g for g in goals if g.level != "individual" or g.owner_employee_id in visible_people]
    owners = _employees(db, tid, [g.owner_employee_id for g in goals])
    last = _last_checkins(db, tid, [g.id for g in goals])
    rows = [_goal_row(g, last.get(g.id), owners, me) for g in goals]
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["children"] = []
    roots = []
    for r in rows:
        parent = by_id.get(r["parent_goal_id"]) if r["parent_goal_id"] else None
        (parent["children"] if parent else roots).append(r)

    def _roll(node: dict) -> float:
        if node["children"]:
            node["rolled_up_progress_pct"] = round(sum(_roll(c) for c in node["children"]) / len(node["children"]), 1)
            return node["progress_pct"] if node["progress_pct"] else node["rolled_up_progress_pct"]
        return node["progress_pct"]

    for root in roots:
        _roll(root)

    mine = [r for r in rows if r["is_mine"]]
    to_write = []
    if me:
        reviews = db.query(Review).filter(Review.tenant_id == tid, Review.reviewer_employee_id == me, Review.status != "submitted").all()
        cycles = {c.id: c for c in db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tid, ReviewCycle.id.in_([r.cycle_id for r in reviews] or [None])).all()}
        people = _employees(db, tid, [r.employee_id for r in reviews])
        for r in reviews:
            cycle = cycles.get(r.cycle_id)
            due = next((s.get("due_date") for s in (cycle.stages_json or []) if s.get("stage") == r.stage), None) if cycle else None
            to_write.append({
                "id": str(r.id), "stage": r.stage, "status": r.status, "about_me": r.employee_id == me,
                "employee_name": _name(people.get(r.employee_id)), "cycle_name": cycle.name if cycle else "",
                "cycle_open": bool(cycle and cycle.status == "active"), "due_date": due or (_iso(cycle.period_end) if cycle else None),
            })
    me_row = _employees(db, tid, [me]).get(me) if me else None
    return {
        "employee": {"id": str(me), "name": _name(me_row)} if me else None,
        "team_size": len(team_ids),
        "tree": roots,
        "my_goals": [{k: v for k, v in r.items() if k != "children"} for r in mine],
        "checkin_due_count": sum(1 for r in mine if r["checkin_due"]),
        "reviews_to_write": to_write,
    }


# ---- /performance/review/:id (F3, F4) ----


@router.get("/reviews/{review_id}/form")
def review_form(review_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    tid = tenant.tenant_id
    review = db.query(Review).filter(Review.tenant_id == tid, Review.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="We couldn't find that review.")
    perms = effective_permissions(db, tenant, current_user)
    me = my_employee_id(db, tenant, current_user)
    if me and review.reviewer_employee_id == me and "performance.self.view" in perms:
        submit_as = "me"
    elif "performance.review.edit" in perms:
        submit_as = "admin"
    else:
        raise HTTPException(status_code=403, detail="Only the person writing this review can open it.")
    cycle = db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tid, ReviewCycle.id == review.cycle_id).first()
    people = _employees(db, tid, [review.employee_id, review.reviewer_employee_id])
    goals_q = db.query(Goal).filter(Goal.tenant_id == tid, Goal.owner_employee_id == review.employee_id, Goal.status != "cancelled")
    if cycle is not None:
        cycle_goals = goals_q.filter(Goal.cycle_id == cycle.id).all()
        goals = cycle_goals or goals_q.all()
    else:
        goals = goals_q.all()
    return {
        "review": {
            "id": str(review.id), "stage": review.stage, "status": review.status, "section_scores": review.section_scores_json or {},
            "goal_ratings": review.goal_ratings_json or {}, "answers": review.answers_json or {}, "comments": review.comments,
            "overall_rating": _f(review.overall_rating), "ai_draft": review.ai_draft_json, "submitted_at": _iso(review.submitted_at),
        },
        "about_me": bool(me and review.employee_id == me),
        "employee_name": _name(people.get(review.employee_id)),
        "reviewer_name": _name(people.get(review.reviewer_employee_id)),
        "submit_as": submit_as,
        "cycle": {
            "name": cycle.name, "status": cycle.status, "period_start": _iso(cycle.period_start), "period_end": _iso(cycle.period_end),
            "sections": cycle.sections_json or [],
        } if cycle else None,
        "scale": _scale_points(db, cycle),
        "goals": [{"id": str(g.id), "title": g.title, "weightage": float(g.weightage or 0), "progress_pct": float(g.progress_pct or 0)} for g in goals],
    }


# ---- /performance/team (F5, F6) ----


@router.get("/team")
def team(scope: str = "mine", db: Session = Depends(get_db), current_user: User = Depends(require("performance.goal.view"))):
    tenant = require_current_tenant()
    tid = tenant.tenant_id
    perms = effective_permissions(db, tenant, current_user)
    me = my_employee_id(db, tenant, current_user)
    mine = direct_reportees(db, tenant, me) if me else set()
    in_scope = employee_ids_in_scope(db, tenant, current_user, "performance.goal.view")
    can_all = in_scope is None or bool(in_scope)
    if scope == "all" and can_all:
        q = db.query(Employee).filter(Employee.tenant_id == tid, Employee.status.in_(("active", "on_notice")))
        if in_scope is not None:
            q = q.filter(Employee.id.in_(list(in_scope)))
        ids = {e.id for e in q.limit(500).all()}
    else:
        scope = "mine"
        ids = mine
    ids.discard(me)
    people = _employees(db, tid, ids)
    jobs = _current_jobs(db, tid, ids)
    departments = _departments(db, tid)
    cycle = _active_cycle(db, tid)
    points = _scale_points(db, cycle)

    goals = db.query(Goal).filter(Goal.tenant_id == tid, Goal.owner_employee_id.in_(list(ids) or [None]), Goal.status != "cancelled").all()
    last = _last_checkins(db, tid, [g.id for g in goals])
    reviews = db.query(Review).filter(Review.tenant_id == tid, Review.cycle_id == cycle.id, Review.employee_id.in_(list(ids) or [None])).all() if cycle else []
    show_talent = "performance.talent.view" in perms
    talent = {p.employee_id: p for p in db.query(TalentProfile).filter(TalentProfile.tenant_id == tid, TalentProfile.employee_id.in_(list(ids) or [None])).all()} if show_talent else {}

    rows = []
    for eid, e in people.items():
        own = [g for g in goals if g.owner_employee_id == eid]
        lasts = [last[g.id] for g in own if g.id in last]
        mine_reviews = [r for r in reviews if r.employee_id == eid]
        manager_review = next((r for r in mine_reviews if r.stage == "manager"), None)
        rated = next((r for r in mine_reviews if r.status == "submitted" and r.overall_rating is not None and r.stage == "manager"), None) or \
            next((r for r in mine_reviews if r.status == "submitted" and r.overall_rating is not None), None)
        rating = _f(rated.overall_rating) if rated else None
        job = jobs.get(eid)
        profile = talent.get(eid)
        placed = (profile.mobility_json or {}).get(NINE_BOX_KEY) if profile else None
        row = {
            "employee_id": str(eid), "name": _name(e), "designation": job.designation if job else None,
            "department": departments.get(job.department_id) if job else None,
            "goals": len(own), "avg_progress": round(sum(float(g.progress_pct or 0) for g in own) / len(own), 1) if own else None,
            "last_checkin_at": _iso(max(lasts)) if lasts else None, "checkin_due": any(_checkin_due(g, last.get(g.id)) for g in own),
            "review_status": manager_review.status if manager_review else ("submitted" if mine_reviews and all(r.status == "submitted" for r in mine_reviews) else (mine_reviews[0].status if mine_reviews else None)),
            "manager_review_id": str(manager_review.id) if manager_review and me and manager_review.reviewer_employee_id == me else None,
            "rating": rating, "suggested_performance": _performance_band(points, rating),
        }
        if show_talent:
            row["nine_box"] = placed if isinstance(placed, dict) else None
            row["flight_risk"] = profile.flight_risk_manager if profile and profile.flight_risk_manager else None
        rows.append(row)
    rows.sort(key=lambda r: r["name"].lower())
    return {
        "scope": scope, "can_see_all": can_all, "has_team": bool(mine), "show_talent": show_talent,
        "can_edit_talent": "performance.talent.edit" in perms,
        "cycle": {"name": cycle.name, "status": cycle.status} if cycle else None, "scale": points, "people": rows,
    }


@router.get("/people")
def people_search(q: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    perms = effective_permissions(db, tenant, current_user)
    if not perms & {"performance.goal.view", "performance.succession.view", "compensation.planning.view"}:
        raise HTTPException(status_code=403, detail="You don't have access to the people list.")
    query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice")))
    term = q.strip()
    if term:
        like = f"%{term}%"
        query = query.filter((Employee.first_name.ilike(like)) | (Employee.last_name.ilike(like)) | (Employee.preferred_name.ilike(like)))
    rows = query.order_by(Employee.first_name.asc()).limit(25).all()
    jobs = _current_jobs(db, tenant.tenant_id, [r.id for r in rows])
    return [{"id": str(r.id), "name": _name(r), "designation": jobs[r.id].designation if r.id in jobs else None} for r in rows]


# ---- /compensation (F7) ----


@router.get("/compensation/cycles")
def comp_cycles(db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view"))):
    tenant = require_current_tenant()
    rows = db.query(CompensationCycle).filter(CompensationCycle.tenant_id == tenant.tenant_id).order_by(CompensationCycle.effective_date.desc()).all()
    return [{"id": str(c.id), "name": c.name, "effective_date": _iso(c.effective_date), "currency": c.currency, "status": c.status} for c in rows]


@router.get("/compensation/cycles/{cycle_id}/grid")
def comp_grid(cycle_id: UUID, department_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(require("compensation.planning.view"))):
    from app.performance import compensation

    tenant = require_current_tenant()
    tid = tenant.tenant_id
    cycle = db.query(CompensationCycle).filter(CompensationCycle.tenant_id == tid, CompensationCycle.id == cycle_id).first()
    if cycle is None:
        raise HTTPException(status_code=404, detail="We couldn't find that pay review.")
    perms = effective_permissions(db, tenant, current_user)
    sensitive = "compensation.planning.view_sensitive" in perms
    q = db.query(CompensationProposal).filter(CompensationProposal.tenant_id == tid, CompensationProposal.comp_cycle_id == cycle.id)
    if department_id:
        q = q.filter(CompensationProposal.department_id == department_id)
    proposals = q.all()
    ids = [p.employee_id for p in proposals]
    people = _employees(db, tid, ids)
    jobs = _current_jobs(db, tid, ids)
    departments = _departments(db, tid)
    bands = db.query(SalaryBand).filter(SalaryBand.tenant_id == tid, SalaryBand.currency == cycle.currency).all() if sensitive else []

    def _band(job):
        if not job or not job.grade:
            return None
        exact = [b for b in bands if b.grade == job.grade and b.location_id == job.location_id]
        loose = [b for b in bands if b.grade == job.grade and b.location_id is None]
        b = (exact or loose or [None])[0]
        return {"min": float(b.min_amount), "mid": float(b.mid_amount), "max": float(b.max_amount)} if b else None

    rows = []
    for p in proposals:
        job = jobs.get(p.employee_id)
        row = {
            **compensation.proposal_to_dict(p),
            "name": _name(people.get(p.employee_id)), "designation": job.designation if job else None,
            "department": departments.get(p.department_id) if p.department_id else None, "grade": job.grade if job else None,
            "band": _band(job) if sensitive else None,
        }
        rows.append(apply_field_security(db, tenant, current_user, "compensation_proposal", row))
    rows.sort(key=lambda r: (r.get("department") or "", r.get("name") or ""))

    in_worksheet = set(ids)
    candidates = []
    if "compensation.planning.create" in perms:
        scope_ids = employee_ids_in_scope(db, tenant, current_user, "compensation.planning.create")
        eq = db.query(Employee).filter(Employee.tenant_id == tid, Employee.status.in_(("active", "on_notice")))
        if scope_ids is not None:
            eq = eq.filter(Employee.id.in_(list(scope_ids) or [None]))
        candidates = [str(e.id) for e in eq.limit(1000).all() if e.id not in in_worksheet]
    used_departments = sorted({(p.department_id, departments.get(p.department_id)) for p in db.query(CompensationProposal).filter(
        CompensationProposal.tenant_id == tid, CompensationProposal.comp_cycle_id == cycle.id).all() if p.department_id}, key=lambda d: d[1] or "")
    return {
        "cycle": {"id": str(cycle.id), "name": cycle.name, "currency": cycle.currency, "effective_date": _iso(cycle.effective_date), "status": cycle.status},
        "rows": rows,
        "budget": compensation.budget_usage(db, tenant, cycle, department_id),
        "departments": [{"id": str(d), "name": n} for d, n in used_departments if n],
        "can_see_bands": sensitive,
        "not_in_worksheet": candidates,
    }


# ---- /succession ----


@router.get("/succession")
def succession(db: Session = Depends(get_db), current_user: User = Depends(require("performance.succession.view"))):
    from app.performance.talent import slate_readiness

    tenant = require_current_tenant()
    tid = tenant.tenant_id
    positions = db.query(Position).filter(Position.tenant_id == tid, Position.is_critical.is_(True)).order_by(Position.title.asc()).all()
    departments = _departments(db, tid)
    today = datetime.now(timezone.utc).date()
    holders: dict = {}
    if positions:
        recs = (
            db.query(EmploymentRecord)
            .filter(EmploymentRecord.tenant_id == tid, EmploymentRecord.position_id.in_([p.id for p in positions]), EmploymentRecord.effective_from <= today)
            .filter((EmploymentRecord.effective_to.is_(None)) | (EmploymentRecord.effective_to >= today))
            .all()
        )
        for r in recs:
            holders.setdefault(r.position_id, []).append(r.employee_id)
    slates = {s.position_id: s for s in db.query(SuccessionSlate).filter(SuccessionSlate.tenant_id == tid, SuccessionSlate.position_id.in_([p.id for p in positions] or [None])).all()}
    all_ids = {e for ids in holders.values() for e in ids}
    readiness = {}
    for pid, slate in slates.items():
        readiness[pid] = slate_readiness(db, tenant, slate)
        all_ids |= {UUID(s["employee_id"]) for s in readiness[pid]["successors"]}
    people = _employees(db, tid, all_ids)
    assessed = {(c.slate_id, c.employee_id): c.assessed_at for c in db.query(SuccessionCandidate).filter(
        SuccessionCandidate.tenant_id == tid, SuccessionCandidate.slate_id.in_([s.id for s in slates.values()] or [None])).all()}
    out = []
    for p in positions:
        info = readiness.get(p.id) or {"coverage": "uncovered", "successors": [], "counts": {}}
        slate = slates.get(p.id)
        out.append({
            "position_id": str(p.id), "title": p.title, "department": departments.get(p.department_id) if p.department_id else None,
            "grade": p.grade, "holders": [_name(people.get(e)) for e in holders.get(p.id, []) if people.get(e)],
            "coverage": info["coverage"], "counts": info.get("counts", {}),
            "successors": [
                {**s, "name": _name(people.get(UUID(s["employee_id"]))),
                 "assessed_at": _iso(assessed.get((slate.id, UUID(s["employee_id"])))) if slate else None}
                for s in info["successors"]
            ],
        })
    perms = effective_permissions(db, tenant, current_user)
    return {"positions": out, "can_edit": "performance.succession.edit" in perms}
