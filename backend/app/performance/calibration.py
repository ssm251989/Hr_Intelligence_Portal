"""Calibration (docs/HRMS_COMPLETE_SPEC.txt Part 10 section D): distribution guidelines
(soft = warn, hard = block finalize), 9-box grid (performance x potential), drag-to-adjust
with a mandatory-reason audit row per move, and a before/after normalisation report."""

from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.performance import CalibrationAudit, CalibrationEntry, CalibrationSession, RatingScale, Review, ReviewCycle
from app.performance.reviews import compute_final_rating
from app.platform.tenancy.context import TenantContext

NINE_BOX_LABELS = {
    (3, 3): "Future leader", (2, 3): "Growth employee", (1, 3): "Enigma",
    (3, 2): "High performer", (2, 2): "Core player", (1, 2): "Dilemma",
    (3, 1): "Trusted professional", (2, 1): "Effective", (1, 1): "Under-performer",
}


class CalibrationError(ValueError):
    pass


def open_session(
    db: Session, tenant: TenantContext, cycle: ReviewCycle, *, name: str, distribution: Optional[dict] = None,
    tolerance_pct: float = 5, enforcement: str = "soft",
) -> CalibrationSession:
    """Seeds one entry per employee with a computed final rating (original_rating is
    frozen here so the normalisation report always compares against it)."""
    if distribution and abs(sum(float(v) for v in distribution.values()) - 100) > 0.01:
        raise CalibrationError("distribution targets must sum to 100")
    session = CalibrationSession(
        tenant_id=tenant.tenant_id, cycle_id=cycle.id, name=name, distribution_json=distribution or {},
        tolerance_pct=tolerance_pct, enforcement=enforcement,
    )
    db.add(session)
    db.flush()
    employee_ids = {r.employee_id for r in db.query(Review.employee_id).filter(Review.tenant_id == tenant.tenant_id, Review.cycle_id == cycle.id).all()}
    for employee_id in employee_ids:
        rating = compute_final_rating(db, tenant, cycle, employee_id)
        if rating is None:
            continue
        db.add(CalibrationEntry(tenant_id=tenant.tenant_id, session_id=session.id, employee_id=employee_id, original_rating=rating, performance_rating=rating))
    cycle.status = "calibration"
    db.commit()
    db.refresh(session)
    return session


def entries(db: Session, tenant: TenantContext, session: CalibrationSession) -> list[CalibrationEntry]:
    return db.query(CalibrationEntry).filter(CalibrationEntry.tenant_id == tenant.tenant_id, CalibrationEntry.session_id == session.id).all()


def adjust(
    db: Session, tenant: TenantContext, entry: CalibrationEntry, *, actor: str, reason: str,
    performance_rating: Optional[float] = None, potential_rating: Optional[int] = None,
) -> CalibrationEntry:
    session = db.get(CalibrationSession, entry.session_id)
    if session.status != "open":
        raise CalibrationError("session is finalized")
    if not reason or not reason.strip():
        raise CalibrationError("every calibration move needs a reason")
    if potential_rating is not None and potential_rating not in (1, 2, 3):
        raise CalibrationError("potential is 1 (low), 2 (medium) or 3 (high)")
    for field, new in (("performance_rating", performance_rating), ("potential_rating", potential_rating)):
        if new is None:
            continue
        old = getattr(entry, field)
        if old is not None and float(old) == float(new):
            continue
        setattr(entry, field, new)
        db.add(CalibrationAudit(tenant_id=tenant.tenant_id, entry_id=entry.id, field=field, old_value=None if old is None else str(old), new_value=str(new), reason=reason, actor=actor))
    db.commit()
    db.refresh(entry)
    return entry


def audit_trail(db: Session, tenant: TenantContext, entry: CalibrationEntry) -> list[dict]:
    rows = db.query(CalibrationAudit).filter(CalibrationAudit.tenant_id == tenant.tenant_id, CalibrationAudit.entry_id == entry.id).order_by(CalibrationAudit.created_at.asc()).all()
    return [{"field": r.field, "old": r.old_value, "new": r.new_value, "reason": r.reason, "actor": r.actor, "at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def _bucket(value) -> str:
    return str(int(round(float(value))))


def distribution(values: list) -> dict:
    counts = Counter(_bucket(v) for v in values if v is not None)
    total = sum(counts.values())
    return {k: round(100 * c / total, 2) for k, c in sorted(counts.items())} if total else {}


def guideline_check(db: Session, tenant: TenantContext, session: CalibrationSession) -> dict:
    actual = distribution([e.performance_rating for e in entries(db, tenant, session)])
    target = {str(k): float(v) for k, v in (session.distribution_json or {}).items()}
    tolerance = float(session.tolerance_pct)
    deviations = {b: round(actual.get(b, 0) - t, 2) for b, t in target.items()}
    breaches = {b: d for b, d in deviations.items() if abs(d) > tolerance}
    return {"actual": actual, "target": target, "deviations": deviations, "breaches": breaches, "within_guideline": not breaches}


def _performance_band(db: Session, cycle: ReviewCycle, rating: float) -> int:
    scale = db.get(RatingScale, cycle.rating_scale_id) if cycle.rating_scale_id else None
    values = sorted(float(p["value"]) for p in scale.points_json) if scale and scale.points_json else [1, 2, 3, 4, 5]
    low, high = values[0], values[-1]
    third = (high - low) / 3 or 1
    if rating < low + third:
        return 1
    if rating < low + 2 * third:
        return 2
    return 3


def nine_box(db: Session, tenant: TenantContext, session: CalibrationSession) -> dict:
    cycle = db.get(ReviewCycle, session.cycle_id)
    grid: dict[str, list[str]] = {}
    unplaced = []
    for e in entries(db, tenant, session):
        if e.performance_rating is None or e.potential_rating is None:
            unplaced.append(str(e.employee_id))
            continue
        box = (_performance_band(db, cycle, float(e.performance_rating)), int(e.potential_rating))
        grid.setdefault(f"{box[0]}x{box[1]}", []).append(str(e.employee_id))
    return {
        "boxes": {key: {"label": NINE_BOX_LABELS[tuple(int(x) for x in key.split("x"))], "employees": ids} for key, ids in grid.items()},
        "unplaced": unplaced,
    }


def normalisation_report(db: Session, tenant: TenantContext, session: CalibrationSession) -> dict:
    rows = entries(db, tenant, session)
    changed = [e for e in rows if e.original_rating is not None and e.performance_rating is not None and float(e.original_rating) != float(e.performance_rating)]
    return {
        "before": distribution([e.original_rating for e in rows]),
        "after": distribution([e.performance_rating for e in rows]),
        "employees": len(rows), "changed": len(changed),
        "moved_up": sum(float(e.performance_rating) > float(e.original_rating) for e in changed),
        "moved_down": sum(float(e.performance_rating) < float(e.original_rating) for e in changed),
    }


def finalize(db: Session, tenant: TenantContext, session: CalibrationSession, *, actor: str) -> dict:
    check = guideline_check(db, tenant, session)
    if session.enforcement == "hard" and not check["within_guideline"]:
        raise CalibrationError(f"distribution is outside the guideline: {check['breaches']}")
    session.status = "finalized"
    session.finalized_by = actor
    session.finalized_at = datetime.now(timezone.utc)
    db.commit()
    return {**check, "warnings": [] if check["within_guideline"] else [f"bucket {b} off by {d}%" for b, d in check["breaches"].items()]}


def calibrated_rating(db: Session, tenant: TenantContext, cycle_id: UUID, employee_id: UUID) -> Optional[float]:
    """The rating compensation planning uses: the finalized calibrated one if any, else the
    computed final rating."""
    entry = (
        db.query(CalibrationEntry)
        .join(CalibrationSession, CalibrationSession.id == CalibrationEntry.session_id)
        .filter(CalibrationEntry.tenant_id == tenant.tenant_id, CalibrationSession.cycle_id == cycle_id,
                CalibrationSession.status == "finalized", CalibrationEntry.employee_id == employee_id)
        .first()
    )
    if entry is not None and entry.performance_rating is not None:
        return float(entry.performance_rating)
    cycle = db.get(ReviewCycle, cycle_id)
    return compute_final_rating(db, tenant, cycle, employee_id) if cycle else None
