"""Talent & succession (docs/HRMS_COMPLETE_SPEC.txt Part 10 section F): talent profiles,
critical positions (Part 7's `positions.is_critical`), successor slates with readiness,
flight risk (AI estimate + manager input -- the manager's call is the one that counts),
career paths, and an internal gig/project/IJP marketplace."""

from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import Position
from app.models.performance import (
    FLIGHT_RISK_LEVELS,
    OPPORTUNITY_TYPES,
    READINESS_LEVELS,
    InternalApplication,
    InternalOpportunity,
    SuccessionCandidate,
    SuccessionSlate,
    TalentProfile,
)
from app.platform.tenancy.context import TenantContext

_READINESS_RANK = {level: i for i, level in enumerate(READINESS_LEVELS)}  # ready_now first


class TalentError(ValueError):
    pass


# ---- talent profile + flight risk ----


def get_or_create_profile(db: Session, tenant: TenantContext, employee_id: UUID) -> TalentProfile:
    profile = db.query(TalentProfile).filter(TalentProfile.tenant_id == tenant.tenant_id, TalentProfile.employee_id == employee_id).first()
    if profile is None:
        profile = TalentProfile(tenant_id=tenant.tenant_id, employee_id=employee_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def update_profile(db: Session, profile: TalentProfile, **fields) -> TalentProfile:
    for key in ("aspirations", "mobility_json", "career_path_json"):
        if key in fields and fields[key] is not None:
            setattr(profile, key, fields[key])
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    return profile


def set_manager_flight_risk(db: Session, profile: TalentProfile, *, level: str, notes: Optional[str] = None) -> TalentProfile:
    if level not in FLIGHT_RISK_LEVELS:
        raise TalentError(f"flight risk is one of {FLIGHT_RISK_LEVELS}")
    profile.flight_risk_manager = level
    profile.flight_risk_notes = notes
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    return profile


def record_ai_flight_risk(db: Session, profile: TalentProfile, *, score: float, factors: dict) -> TalentProfile:
    """An estimate (0-1) from Part 12's predictive layer -- stored, labelled, never acted on
    automatically."""
    if not 0 <= score <= 1:
        raise TalentError("score must be between 0 and 1")
    profile.flight_risk_ai = score
    profile.flight_risk_ai_factors_json = {**factors, "label": "estimate"}
    db.commit()
    db.refresh(profile)
    return profile


def effective_flight_risk(profile: TalentProfile) -> Optional[str]:
    """HITL: the manager's assessment wins; the AI estimate only fills the gap, flagged."""
    if profile.flight_risk_manager:
        return profile.flight_risk_manager
    if profile.flight_risk_ai is None:
        return None
    score = float(profile.flight_risk_ai)
    return "high" if score >= 0.66 else "medium" if score >= 0.33 else "low"


# ---- succession ----


def get_or_create_slate(db: Session, tenant: TenantContext, position_id: UUID) -> SuccessionSlate:
    position = db.get(Position, position_id)
    if position is None or position.tenant_id != tenant.tenant_id:
        raise TalentError("position not found")
    slate = db.query(SuccessionSlate).filter(SuccessionSlate.tenant_id == tenant.tenant_id, SuccessionSlate.position_id == position_id).first()
    if slate is None:
        slate = SuccessionSlate(tenant_id=tenant.tenant_id, position_id=position_id)
        db.add(slate)
        db.commit()
        db.refresh(slate)
    return slate


def add_successor(
    db: Session, tenant: TenantContext, slate: SuccessionSlate, *, employee_id: UUID, readiness: str, rank: int = 1,
    development_actions: Optional[list] = None, assessed_by: Optional[str] = None,
) -> SuccessionCandidate:
    if readiness not in READINESS_LEVELS:
        raise TalentError(f"readiness is one of {READINESS_LEVELS}")
    candidate = db.query(SuccessionCandidate).filter(
        SuccessionCandidate.tenant_id == tenant.tenant_id, SuccessionCandidate.slate_id == slate.id, SuccessionCandidate.employee_id == employee_id,
    ).first()
    if candidate is None:
        candidate = SuccessionCandidate(tenant_id=tenant.tenant_id, slate_id=slate.id, employee_id=employee_id, readiness=readiness)
        db.add(candidate)
    candidate.readiness = readiness
    candidate.rank = rank
    candidate.development_actions_json = development_actions or []
    candidate.assessed_by = assessed_by
    candidate.assessed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(candidate)
    return candidate


def slate_candidates(db: Session, tenant: TenantContext, slate: SuccessionSlate) -> list[SuccessionCandidate]:
    rows = db.query(SuccessionCandidate).filter(SuccessionCandidate.tenant_id == tenant.tenant_id, SuccessionCandidate.slate_id == slate.id).all()
    return sorted(rows, key=lambda c: (_READINESS_RANK[c.readiness], c.rank))


def slate_readiness(db: Session, tenant: TenantContext, slate: SuccessionSlate) -> dict:
    """Bench strength: coverage is "covered" with >=1 ready-now successor, "at_risk" with
    only future-ready ones, "uncovered" with none."""
    candidates = slate_candidates(db, tenant, slate)
    counts = Counter(c.readiness for c in candidates)
    coverage = "covered" if counts["ready_now"] else "at_risk" if candidates else "uncovered"
    return {
        "slate_id": str(slate.id), "position_id": str(slate.position_id), "coverage": coverage,
        "counts": {level: counts.get(level, 0) for level in READINESS_LEVELS},
        "successors": [
            {"employee_id": str(c.employee_id), "readiness": c.readiness, "rank": c.rank, "development_actions": c.development_actions_json}
            for c in candidates
        ],
    }


def critical_positions_report(db: Session, tenant: TenantContext) -> list[dict]:
    positions = db.query(Position).filter(Position.tenant_id == tenant.tenant_id, Position.is_critical.is_(True)).all()
    report = []
    for position in positions:
        slate = db.query(SuccessionSlate).filter(SuccessionSlate.tenant_id == tenant.tenant_id, SuccessionSlate.position_id == position.id).first()
        report.append({"position_id": str(position.id), "title": position.title, **(slate_readiness(db, tenant, slate) if slate else {"coverage": "uncovered", "successors": []})})
    return report


# ---- internal marketplace ----


def post_opportunity(db: Session, tenant: TenantContext, *, type: str, title: str, description: Optional[str] = None, skills: Optional[list] = None,
                     department_id: Optional[UUID] = None, position_id: Optional[UUID] = None, posted_by: Optional[str] = None, closes_on=None) -> InternalOpportunity:
    if type not in OPPORTUNITY_TYPES:
        raise TalentError(f"type is one of {OPPORTUNITY_TYPES}")
    row = InternalOpportunity(tenant_id=tenant.tenant_id, type=type, title=title, description=description, skills_json=skills or [],
                              department_id=department_id, position_id=position_id, posted_by=posted_by, closes_on=closes_on)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def apply_internal(db: Session, tenant: TenantContext, opportunity: InternalOpportunity, *, employee_id: UUID, note: Optional[str] = None) -> InternalApplication:
    if opportunity.status != "open":
        raise TalentError("this opportunity is closed")
    existing = db.query(InternalApplication).filter(
        InternalApplication.tenant_id == tenant.tenant_id, InternalApplication.opportunity_id == opportunity.id, InternalApplication.employee_id == employee_id,
    ).first()
    if existing is not None:
        return existing
    application = InternalApplication(tenant_id=tenant.tenant_id, opportunity_id=opportunity.id, employee_id=employee_id, note=note)
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def skill_matches(db: Session, tenant: TenantContext, opportunity: InternalOpportunity, employee_skills: list[str]) -> dict:
    wanted = {s.lower() for s in opportunity.skills_json or []}
    have = {s.lower() for s in employee_skills}
    return {"matched": sorted(wanted & have), "missing": sorted(wanted - have), "match_pct": round(100 * len(wanted & have) / len(wanted)) if wanted else 0}
