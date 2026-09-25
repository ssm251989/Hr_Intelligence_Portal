"""Review cycles (docs/HRMS_COMPLETE_SPEC.txt Part 10 section C) -- eligibility rules,
stage fan-out (self / manager / peer via approved nomination / skip-level / reviewer),
weightage formula, anonymity enforcement, deadline reminders via comms, and the AI draft
assist (HITL, bias-language check, never auto-submits).

**Weightage formula** (one place, `compute_final_rating`):
  review.overall = sum(section_score * section.weight) / sum(section.weight)
    where the "goals" section score = sum(goal_rating * goal.weightage) / sum(goal.weightage)
  final = sum(stage_score * stage.weight) / sum(weights of stages that have a score)
    where a stage's score is the mean of its submitted reviews' overall ratings (peer: all peers).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

import json_logic
from sqlalchemy.orm import Session

from app.core_hr.context import employee_context, manager_of
from app.models.core_hr import Employee
from app.models.performance import (
    REVIEW_STAGES,
    Feedback,
    Goal,
    OneOnOne,
    RatingScale,
    Review,
    ReviewCycle,
    ReviewNomination,
)
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


class ReviewCycleError(ValueError):
    pass


def _q(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---- cycle configuration ----


def validate_cycle_config(stages: list[dict], sections: list[dict]) -> None:
    if not stages:
        raise ReviewCycleError("a cycle needs at least one stage")
    for stage in stages:
        if stage.get("stage") not in REVIEW_STAGES:
            raise ReviewCycleError(f"unknown stage {stage.get('stage')!r}")
        if float(stage.get("weight", 0)) < 0:
            raise ReviewCycleError("stage weights cannot be negative")
    if len({s["stage"] for s in stages}) != len(stages):
        raise ReviewCycleError("each stage may appear once")
    keys = [s.get("key") for s in sections]
    if len(set(keys)) != len(keys) or any(not k for k in keys):
        raise ReviewCycleError("section keys must be unique and non-empty")


def create_cycle(
    db: Session, tenant: TenantContext, *, name: str, cycle_type: str, period_start: date, period_end: date,
    stages: list[dict], sections: list[dict], rating_scale_id: Optional[UUID] = None,
    eligibility_jsonlogic: Optional[dict] = None, anonymity: Optional[dict] = None, reminder_days_before: Optional[list[int]] = None,
) -> ReviewCycle:
    validate_cycle_config(stages, sections)
    if period_end < period_start:
        raise ReviewCycleError("period_end is before period_start")
    cycle = ReviewCycle(
        tenant_id=tenant.tenant_id, name=name, cycle_type=cycle_type, period_start=period_start, period_end=period_end,
        stages_json=stages, sections_json=sections, rating_scale_id=rating_scale_id, eligibility_jsonlogic=eligibility_jsonlogic,
        anonymity_json=anonymity or {"peer_anonymous": True, "min_peer_responses": 3, "peer_visible_to_employee": True},
        reminder_days_before=reminder_days_before if reminder_days_before is not None else [3, 1],
    )
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return cycle


def _scale_bounds(db: Session, cycle: ReviewCycle) -> tuple[float, float]:
    scale = db.get(RatingScale, cycle.rating_scale_id) if cycle.rating_scale_id else None
    if scale is None or not scale.points_json:
        return 1.0, 5.0
    values = [float(p["value"]) for p in scale.points_json]
    return min(values), max(values)


# ---- eligibility ----


def is_eligible(db: Session, tenant: TenantContext, cycle: ReviewCycle, employee: Employee) -> bool:
    if employee.status not in ("active", "on_notice"):
        return False
    if cycle.eligibility_jsonlogic is None:
        return True
    ctx = employee_context(db, tenant, employee, as_of=cycle.period_end)
    try:
        return bool(json_logic.jsonLogic(cycle.eligibility_jsonlogic, ctx))
    except Exception:
        return False


def eligible_employees(db: Session, tenant: TenantContext, cycle: ReviewCycle) -> list[Employee]:
    employees = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.status.in_(("active", "on_notice"))).all()
    return [e for e in employees if is_eligible(db, tenant, cycle, e)]


# ---- launch / fan-out ----


def _ensure_review(db: Session, tenant: TenantContext, cycle: ReviewCycle, employee_id, reviewer_id, stage: str) -> bool:
    """True if a new review row was added."""
    if reviewer_id is None:
        return False
    existing = db.query(Review).filter(
        Review.tenant_id == tenant.tenant_id, Review.cycle_id == cycle.id, Review.employee_id == employee_id,
        Review.reviewer_employee_id == reviewer_id, Review.stage == stage,
    ).first()
    if existing is not None:
        return False
    db.add(Review(tenant_id=tenant.tenant_id, cycle_id=cycle.id, employee_id=employee_id, reviewer_employee_id=reviewer_id, stage=stage))
    db.flush()
    return True


def launch_cycle(db: Session, tenant: TenantContext, cycle: ReviewCycle) -> dict:
    """Idempotent: re-launching only adds reviews for newly-eligible employees."""
    if cycle.status not in ("draft", "active"):
        raise ReviewCycleError(f"cannot launch a {cycle.status} cycle")
    stages = {s["stage"] for s in cycle.stages_json}
    created = 0
    employees = eligible_employees(db, tenant, cycle)
    for employee in employees:
        manager_id = manager_of(db, tenant, employee.id, as_of=cycle.period_end)
        targets = []
        if "self" in stages:
            targets.append((employee.id, "self"))
        if "manager" in stages:
            targets.append((manager_id, "manager"))
        if "skip_level" in stages and manager_id:
            targets.append((manager_of(db, tenant, manager_id, as_of=cycle.period_end), "skip_level"))
        for reviewer_id, stage in targets:
            created += _ensure_review(db, tenant, cycle, employee.id, reviewer_id, stage)
    cycle.status = "active"
    db.commit()
    return {"eligible": len(employees), "reviews_created": created}


def nominate_peer(db: Session, tenant: TenantContext, cycle: ReviewCycle, *, employee_id: UUID, nominee_employee_id: UUID) -> ReviewNomination:
    if "peer" not in {s["stage"] for s in cycle.stages_json}:
        raise ReviewCycleError("this cycle has no peer stage")
    if employee_id == nominee_employee_id:
        raise ReviewCycleError("an employee cannot nominate themselves as a peer")
    nomination = ReviewNomination(tenant_id=tenant.tenant_id, cycle_id=cycle.id, employee_id=employee_id, nominee_employee_id=nominee_employee_id)
    db.add(nomination)
    db.commit()
    db.refresh(nomination)
    return nomination


def decide_nomination(db: Session, tenant: TenantContext, nomination: ReviewNomination, *, approve: bool, actor: str) -> ReviewNomination:
    nomination.status = "approved" if approve else "rejected"
    nomination.decided_by = actor
    if approve:
        cycle = db.get(ReviewCycle, nomination.cycle_id)
        _ensure_review(db, tenant, cycle, nomination.employee_id, nomination.nominee_employee_id, "peer")
    db.commit()
    db.refresh(nomination)
    return nomination


# ---- submission + weightage ----


def goals_section_score(db: Session, tenant: TenantContext, goal_ratings: dict) -> Optional[float]:
    """Weighted by each goal's own weightage; equal weights if every goal has 0."""
    if not goal_ratings:
        return None
    goals = {str(g.id): g for g in db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.id.in_(list(goal_ratings.keys()))).all()}
    pairs = [(float(r), float(goals[gid].weightage or 0)) for gid, r in goal_ratings.items() if gid in goals]
    if not pairs:
        return None
    total_weight = sum(w for _, w in pairs)
    if total_weight == 0:
        return _q(sum(r for r, _ in pairs) / len(pairs))
    return _q(sum(r * w for r, w in pairs) / total_weight)


def review_overall(cycle: ReviewCycle, section_scores: dict) -> Optional[float]:
    weights = {s["key"]: float(s.get("weight", 0)) for s in cycle.sections_json}
    scored = [(float(v), weights.get(k, 0)) for k, v in section_scores.items() if v is not None and k in weights]
    total = sum(w for _, w in scored)
    if not scored:
        return None
    if total == 0:
        return _q(sum(v for v, _ in scored) / len(scored))
    return _q(sum(v * w for v, w in scored) / total)


def submit_review(
    db: Session, tenant: TenantContext, review: Review, *, section_scores: Optional[dict] = None, goal_ratings: Optional[dict] = None,
    answers: Optional[dict] = None, comments: Optional[str] = None, final: bool = True,
) -> Review:
    if review.status == "submitted":
        raise ReviewCycleError("review already submitted")
    cycle = db.get(ReviewCycle, review.cycle_id)
    if cycle.status != "active":
        raise ReviewCycleError("the cycle is not accepting reviews")
    low, high = _scale_bounds(db, cycle)
    section_scores = dict(section_scores or {})
    goal_ratings = {str(k): v for k, v in (goal_ratings or {}).items()}
    for value in [*section_scores.values(), *goal_ratings.values()]:
        if value is not None and not low <= float(value) <= high:
            raise ReviewCycleError(f"rating {value} is outside the scale {low}-{high}")
    if goal_ratings and any(s["key"] == "goals" for s in cycle.sections_json):
        section_scores["goals"] = goals_section_score(db, tenant, goal_ratings)
    review.section_scores_json = section_scores
    review.goal_ratings_json = goal_ratings
    review.answers_json = answers or {}
    review.comments = comments
    review.overall_rating = review_overall(cycle, section_scores)
    if final:
        review.status = "submitted"
        review.submitted_at = datetime.now(timezone.utc)
    else:
        review.status = "draft"
    db.commit()
    db.refresh(review)
    return review


def compute_final_rating(db: Session, tenant: TenantContext, cycle: ReviewCycle, employee_id: UUID) -> Optional[float]:
    reviews = db.query(Review).filter(
        Review.tenant_id == tenant.tenant_id, Review.cycle_id == cycle.id, Review.employee_id == employee_id,
        Review.status == "submitted", Review.overall_rating.isnot(None),
    ).all()
    by_stage: dict[str, list[float]] = {}
    for r in reviews:
        by_stage.setdefault(r.stage, []).append(float(r.overall_rating))
    weighted = [
        (sum(by_stage[s["stage"]]) / len(by_stage[s["stage"]]), float(s.get("weight", 0)))
        for s in cycle.stages_json if s["stage"] in by_stage
    ]
    total = sum(w for _, w in weighted)
    if not weighted or total == 0:
        return None
    return _q(sum(score * w for score, w in weighted) / total)


# ---- anonymity enforcement ----


def reviews_for_viewer(db: Session, tenant: TenantContext, cycle: ReviewCycle, employee_id: UUID, *, viewer: str) -> dict:
    """viewer: "employee" (the reviewee), "manager", or "hr". Peer reviews: reviewer
    identity is stripped when `peer_anonymous`, and withheld entirely (to employee and
    manager) below `min_peer_responses` so a small peer group can't be de-anonymised.
    HR sees identities only if `hr_sees_peer_identity`. Unsubmitted reviews are never shown."""
    rules = {"peer_anonymous": True, "min_peer_responses": 3, "peer_visible_to_employee": True, "hr_sees_peer_identity": False, **(cycle.anonymity_json or {})}
    submitted = db.query(Review).filter(
        Review.tenant_id == tenant.tenant_id, Review.cycle_id == cycle.id, Review.employee_id == employee_id, Review.status == "submitted",
    ).all()
    peers = [r for r in submitted if r.stage == "peer"]
    others = [r for r in submitted if r.stage != "peer"]

    def _dict(r: Review, *, anonymous: bool) -> dict:
        return {
            "stage": r.stage, "overall_rating": float(r.overall_rating) if r.overall_rating is not None else None,
            "section_scores": r.section_scores_json, "answers": r.answers_json, "comments": r.comments,
            "reviewer_employee_id": None if anonymous else str(r.reviewer_employee_id),
        }

    visible = [_dict(r, anonymous=False) for r in others]
    peer_block: dict = {"count": len(peers), "withheld": False, "reviews": []}
    below_threshold = len(peers) < int(rules["min_peer_responses"])
    if viewer == "hr":
        peer_block["reviews"] = [_dict(r, anonymous=rules["peer_anonymous"] and not rules["hr_sees_peer_identity"]) for r in peers]
    elif below_threshold or (viewer == "employee" and not rules["peer_visible_to_employee"]):
        peer_block["withheld"] = True
    else:
        peer_block["reviews"] = [_dict(r, anonymous=rules["peer_anonymous"]) for r in peers]
    return {"reviews": visible, "peer": peer_block, "final_rating": compute_final_rating(db, tenant, cycle, employee_id)}


# ---- reminders ----


def due_reminders(db: Session, tenant: TenantContext, cycle: ReviewCycle, *, today: Optional[date] = None) -> list[Review]:
    today = today or datetime.now(timezone.utc).date()
    due_by_stage = {s["stage"]: date.fromisoformat(s["due_date"]) for s in cycle.stages_json if s.get("due_date")}
    offsets = set(cycle.reminder_days_before or [])
    pending = db.query(Review).filter(Review.tenant_id == tenant.tenant_id, Review.cycle_id == cycle.id, Review.status != "submitted").all()
    return [r for r in pending if r.stage in due_by_stage and (due_by_stage[r.stage] - today).days in offsets]


def send_due_reminders(db: Session, tenant: TenantContext, cycle: ReviewCycle, *, today: Optional[date] = None) -> int:
    from app.platform.comms.service import dispatch_event

    sent = 0
    for review in due_reminders(db, tenant, cycle, today=today):
        dispatch_event(db, tenant, "performance.review_due", {
            "cycle_id": str(cycle.id), "cycle_name": cycle.name, "review_id": str(review.id), "stage": review.stage,
            "reviewer_employee_id": str(review.reviewer_employee_id), "employee_id": str(review.employee_id),
        })
        sent += 1
    return sent


# ---- AI draft assist (HITL) ----


def bias_flags(db: Session, tenant: TenantContext, text: str) -> list[str]:
    """Deterministic bias-language check against the tenant's own term list (setting
    `performance.ai.bias_terms`) -- flags, never rewrites."""
    terms = SettingsService(db).get("performance.ai.bias_terms", SettingContext(tenant=tenant)) or []
    lowered = f" {text.lower()} "
    return sorted({t for t in terms if f" {t.lower()} " in lowered or f" {t.lower()}," in lowered or f" {t.lower()}." in lowered})


def draft_review_summary(db: Session, tenant: TenantContext, review: Review) -> Review:
    """Drafts a summary from the period's goals, feedback and shared 1:1 notes via the
    `llm.judgment` purpose. Stored in ai_draft_json for the reviewer to edit -- the review's
    status is never touched here."""
    from app.platform.ai import governance

    cycle = db.get(ReviewCycle, review.cycle_id)
    goals = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id, Goal.owner_employee_id == review.employee_id, Goal.status != "cancelled").all()
    feedback = db.query(Feedback).filter(Feedback.tenant_id == tenant.tenant_id, Feedback.to_employee_id == review.employee_id, Feedback.visibility != "private").all()
    one_on_ones = db.query(OneOnOne).filter(OneOnOne.tenant_id == tenant.tenant_id, OneOnOne.employee_id == review.employee_id).all()
    material = "\n".join(
        [f"Goal: {g.title} -- {float(g.progress_pct or 0)}% ({g.status})" for g in goals]
        + [f"{f.kind.title()}: {f.text_body}" for f in feedback]
        + [f"1:1 notes: {o.shared_notes}" for o in one_on_ones if o.shared_notes]
    )
    system = (
        "You draft a balanced, evidence-based performance review summary for a human reviewer to edit. "
        "Use only the material given; cite the goals/feedback you rely on; avoid language about personality, age, "
        "gender, family or health. Return plain text, at most 200 words."
    )
    try:
        summary = governance.governed_complete(
            db, tenant, feature="performance.review_draft", purpose="llm.judgment", system=system, input_refs={"review_id": str(review.id)},
            messages=[{"role": "user", "content": f"Cycle: {cycle.name}\nStage: {review.stage}\n\n{material or 'No material recorded.'}"}],
        ).text
        review.ai_draft_json = {"summary": summary, "bias_flags": bias_flags(db, tenant, summary), "source": "ai", "generated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        review.ai_draft_json = {"error": type(exc).__name__}
    db.commit()
    db.refresh(review)
    return review


def review_to_dict(r: Review) -> dict:
    return {
        "id": str(r.id), "cycle_id": str(r.cycle_id), "employee_id": str(r.employee_id),
        "reviewer_employee_id": str(r.reviewer_employee_id), "stage": r.stage, "status": r.status,
        "section_scores": r.section_scores_json, "goal_ratings": r.goal_ratings_json, "answers": r.answers_json,
        "comments": r.comments, "overall_rating": float(r.overall_rating) if r.overall_rating is not None else None,
        "ai_draft": r.ai_draft_json,
    }


def cycle_to_dict(c: ReviewCycle) -> dict:
    return {
        "id": str(c.id), "name": c.name, "cycle_type": c.cycle_type, "period_start": c.period_start.isoformat(),
        "period_end": c.period_end.isoformat(), "status": c.status, "stages": c.stages_json, "sections": c.sections_json,
        "eligibility": c.eligibility_jsonlogic, "anonymity": c.anonymity_json,
        "rating_scale_id": str(c.rating_scale_id) if c.rating_scale_id else None,
    }
