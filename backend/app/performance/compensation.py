"""Compensation planning (docs/HRMS_COMPLETE_SPEC.txt Part 10 section E): merit matrix
(rating x compa-ratio -> % range), salary bands per grade/location with compa-ratio,
department budget pools, bonus rules, promotion cases, the manager worksheet, approvals
(Part 5 workflow when a `compensation_proposal` definition is published), letters (Part 7)
and the effective-dated `compensation_records` history. Payroll is out of scope -- the
spec's own "optional export" is the CSV below."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core_hr import lifecycle
from app.models.performance import (
    CompensationBudget,
    CompensationCycle,
    CompensationProposal,
    CompensationRecord,
    MeritMatrix,
    SalaryBand,
)
from app.models.workflow import WorkflowDefinition
from app.performance.calibration import calibrated_rating
from app.platform.tenancy.context import TenantContext


class CompensationError(ValueError):
    pass


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---- merit matrix ----


def validate_cells(cells: list[dict]) -> None:
    required = ("rating_min", "rating_max", "compa_min", "compa_max", "pct_min", "pct_max")
    for i, cell in enumerate(cells):
        missing = [k for k in required if k not in cell]
        if missing:
            raise CompensationError(f"cell {i} missing {missing}")
        if cell["rating_min"] >= cell["rating_max"] or cell["compa_min"] >= cell["compa_max"] or cell["pct_min"] > cell["pct_max"]:
            raise CompensationError(f"cell {i} has an empty or inverted range")
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            if a["rating_min"] < b["rating_max"] and b["rating_min"] < a["rating_max"] and a["compa_min"] < b["compa_max"] and b["compa_min"] < a["compa_max"]:
                raise CompensationError("merit matrix cells overlap")


def upsert_matrix(db: Session, tenant: TenantContext, *, code: str, name: str, cells: list[dict], bonus_rules: Optional[dict] = None) -> MeritMatrix:
    validate_cells(cells)
    matrix = db.query(MeritMatrix).filter(MeritMatrix.tenant_id == tenant.tenant_id, MeritMatrix.code == code).first()
    if matrix is None:
        matrix = MeritMatrix(tenant_id=tenant.tenant_id, code=code, name=name)
        db.add(matrix)
    matrix.name = name
    matrix.cells_json = cells
    matrix.bonus_rules_json = bonus_rules or {}
    db.commit()
    db.refresh(matrix)
    return matrix


def merit_range(matrix: MeritMatrix, rating: float, compa_ratio: float) -> Optional[tuple[float, float]]:
    """[min, max) bounds on both axes; the top cell of an axis is inclusive of its max so
    the scale's highest rating always lands somewhere."""
    top_rating = max((c["rating_max"] for c in matrix.cells_json), default=None)
    top_compa = max((c["compa_max"] for c in matrix.cells_json), default=None)
    for cell in matrix.cells_json:
        in_rating = cell["rating_min"] <= rating < cell["rating_max"] or (rating == cell["rating_max"] == top_rating)
        in_compa = cell["compa_min"] <= compa_ratio < cell["compa_max"] or (compa_ratio == cell["compa_max"] == top_compa)
        if in_rating and in_compa:
            return float(cell["pct_min"]), float(cell["pct_max"])
    return None


# ---- salary bands / compa-ratio ----


def find_band(db: Session, tenant: TenantContext, *, grade: str, location_id: Optional[UUID], currency: str) -> Optional[SalaryBand]:
    query = db.query(SalaryBand).filter(SalaryBand.tenant_id == tenant.tenant_id, SalaryBand.grade == grade, SalaryBand.currency == currency)
    specific = query.filter(SalaryBand.location_id == location_id).first() if location_id else None
    return specific or query.filter(SalaryBand.location_id.is_(None)).first()


def compa_ratio(base: float, band: SalaryBand) -> float:
    return float((_d(base) / _d(band.mid_amount)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def band_position(base: float, band: SalaryBand) -> str:
    if _d(base) < _d(band.min_amount):
        return "below_band"
    if _d(base) > _d(band.max_amount):
        return "above_band"
    return "within_band"


# ---- compensation records ----


def current_compensation(db: Session, tenant: TenantContext, employee_id: UUID, *, as_of: Optional[date] = None) -> Optional[CompensationRecord]:
    as_of = as_of or date.today()
    return (
        db.query(CompensationRecord)
        .filter(CompensationRecord.tenant_id == tenant.tenant_id, CompensationRecord.employee_id == employee_id, CompensationRecord.effective_from <= as_of)
        .filter((CompensationRecord.effective_to.is_(None)) | (CompensationRecord.effective_to >= as_of))
        .order_by(CompensationRecord.effective_from.desc())
        .first()
    )


def record_compensation(
    db: Session, tenant: TenantContext, *, employee_id: UUID, effective_from: date, base_amount: float, currency: str,
    components: Optional[dict] = None, reason: Optional[str] = None, proposal_id: Optional[UUID] = None, created_by: Optional[str] = None,
) -> CompensationRecord:
    previous = current_compensation(db, tenant, employee_id, as_of=effective_from - timedelta(days=1))
    if previous is not None and previous.effective_to is None:
        previous.effective_to = effective_from - timedelta(days=1)
    record = CompensationRecord(
        tenant_id=tenant.tenant_id, employee_id=employee_id, effective_from=effective_from, base_amount=base_amount,
        currency=currency, components_json=components, reason=reason, proposal_id=proposal_id, created_by=created_by,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# ---- worksheet / proposals ----


def build_worksheet(db: Session, tenant: TenantContext, comp_cycle: CompensationCycle, employee_ids: list[UUID]) -> list[CompensationProposal]:
    """Creates (or refreshes the guideline on) one draft proposal per employee: current
    base, calibrated rating, compa-ratio and the merit matrix's guideline range. Employees
    with no compensation record are skipped (nothing to plan against)."""
    matrix = db.get(MeritMatrix, comp_cycle.merit_matrix_id) if comp_cycle.merit_matrix_id else None
    proposals = []
    for employee_id in employee_ids:
        comp = current_compensation(db, tenant, employee_id)
        if comp is None:
            continue
        employment = lifecycle.get_current_employment(db, tenant, employee_id)
        rating = calibrated_rating(db, tenant, comp_cycle.review_cycle_id, employee_id) if comp_cycle.review_cycle_id else None
        band = find_band(db, tenant, grade=employment.grade, location_id=employment.location_id, currency=comp.currency) if employment and employment.grade else None
        ratio = compa_ratio(float(comp.base_amount), band) if band else None
        guideline = merit_range(matrix, rating, ratio) if matrix and rating is not None and ratio is not None else None

        proposal = db.query(CompensationProposal).filter(
            CompensationProposal.tenant_id == tenant.tenant_id, CompensationProposal.comp_cycle_id == comp_cycle.id, CompensationProposal.employee_id == employee_id,
        ).first()
        if proposal is None:
            proposal = CompensationProposal(tenant_id=tenant.tenant_id, comp_cycle_id=comp_cycle.id, employee_id=employee_id)
            db.add(proposal)
        if proposal.status in ("draft", None):
            proposal.department_id = employment.department_id if employment else None
            proposal.current_base = comp.base_amount
            proposal.rating = rating
            proposal.compa_ratio = ratio
            proposal.guideline_min_pct, proposal.guideline_max_pct = guideline if guideline else (None, None)
            if guideline and not proposal.merit_pct:
                proposal.merit_pct = guideline[0]
            bonus_pct = (matrix.bonus_rules_json or {}).get(str(int(round(rating)))) if matrix and rating is not None else None
            if bonus_pct is not None and not proposal.bonus_amount:
                proposal.bonus_amount = _money(_d(comp.base_amount) * _d(bonus_pct) / 100)
        proposals.append(proposal)
    db.commit()
    return proposals


def update_proposal(
    proposal: CompensationProposal, *, merit_pct: Optional[float] = None, bonus_amount: Optional[float] = None,
    promotion_to_grade: Optional[str] = None, justification: Optional[str] = None,
) -> None:
    if proposal.status != "draft":
        raise CompensationError("only draft proposals can be edited")
    if merit_pct is not None:
        if merit_pct < 0:
            raise CompensationError("merit % cannot be negative")
        proposal.merit_pct = merit_pct
    if bonus_amount is not None:
        proposal.bonus_amount = bonus_amount
    if promotion_to_grade is not None:
        proposal.promotion_to_grade = promotion_to_grade or None
    if justification is not None:
        proposal.justification = justification


def outside_guideline(proposal: CompensationProposal) -> bool:
    if proposal.guideline_min_pct is None or proposal.guideline_max_pct is None:
        return False
    return not float(proposal.guideline_min_pct) <= float(proposal.merit_pct) <= float(proposal.guideline_max_pct)


def budget_usage(db: Session, tenant: TenantContext, comp_cycle: CompensationCycle, department_id: Optional[UUID]) -> dict:
    budget = db.query(CompensationBudget).filter(
        CompensationBudget.tenant_id == tenant.tenant_id, CompensationBudget.comp_cycle_id == comp_cycle.id, CompensationBudget.department_id == department_id,
    ).first()
    proposals = db.query(CompensationProposal).filter(
        CompensationProposal.tenant_id == tenant.tenant_id, CompensationProposal.comp_cycle_id == comp_cycle.id,
        CompensationProposal.department_id == department_id, CompensationProposal.status != "rejected",
    ).all()
    merit_used = sum((_d(p.current_base) * _d(p.merit_pct) / 100 for p in proposals), Decimal(0))
    bonus_used = sum((_d(p.bonus_amount) for p in proposals), Decimal(0))
    merit_pool = _d(budget.merit_pool) if budget else Decimal(0)
    bonus_pool = _d(budget.bonus_pool) if budget else Decimal(0)
    return {
        "merit_pool": _money(merit_pool), "merit_used": _money(merit_used), "merit_remaining": _money(merit_pool - merit_used),
        "bonus_pool": _money(bonus_pool), "bonus_used": _money(bonus_used), "bonus_remaining": _money(bonus_pool - bonus_used),
        "over_budget": bool(budget) and (merit_used > merit_pool or bonus_used > bonus_pool),
    }


def submit_proposal(db: Session, tenant: TenantContext, proposal: CompensationProposal, *, actor: str, actor_user_id: Optional[UUID] = None) -> CompensationProposal:
    if proposal.status != "draft":
        raise CompensationError("proposal already submitted")
    if outside_guideline(proposal) and not (proposal.justification or "").strip():
        raise CompensationError("a merit % outside the matrix guideline needs a justification")
    comp_cycle = db.get(CompensationCycle, proposal.comp_cycle_id)
    if budget_usage(db, tenant, comp_cycle, proposal.department_id)["over_budget"] and not (proposal.justification or "").strip():
        raise CompensationError("the department is over budget -- add a justification to submit anyway")
    proposal.status = "submitted"
    definition = (
        db.query(WorkflowDefinition)
        .filter(WorkflowDefinition.tenant_id == tenant.tenant_id, WorkflowDefinition.key == "compensation_proposal", WorkflowDefinition.status == "published")
        .order_by(WorkflowDefinition.version.desc())
        .first()
    )
    db.commit()
    if definition is not None:
        from app.platform.workflow.engine import start_instance

        instance = start_instance(
            db, tenant, definition, entity_type="compensation_proposal", entity_id=proposal.id,
            context={"employee_id": str(proposal.employee_id), "merit_pct": float(proposal.merit_pct), "outside_guideline": outside_guideline(proposal),
                     "promotion": bool(proposal.promotion_to_grade)},
            started_by=actor, started_by_user_id=actor_user_id,
        )
        proposal.workflow_instance_id = instance.id
        db.commit()
    db.refresh(proposal)
    return proposal


def decide_proposal(db: Session, tenant: TenantContext, proposal: CompensationProposal, *, approve: bool, actor: str) -> CompensationProposal:
    if proposal.status != "submitted":
        raise CompensationError("only submitted proposals can be decided")
    proposal.status = "approved" if approve else "rejected"
    proposal.decided_by = actor
    db.commit()
    db.refresh(proposal)
    return proposal


def apply_proposal(db: Session, tenant: TenantContext, proposal: CompensationProposal, *, actor: str, letter_template_key: Optional[str] = None) -> dict:
    """Approved -> new effective-dated compensation record (+ promotion via Part 7 lifecycle,
    + optional letter). Idempotent: an applied proposal returns its existing record."""
    if proposal.status == "applied":
        record = db.query(CompensationRecord).filter(CompensationRecord.tenant_id == tenant.tenant_id, CompensationRecord.proposal_id == proposal.id).first()
        return {"record_id": str(record.id) if record else None, "already_applied": True}
    if proposal.status != "approved":
        raise CompensationError("only approved proposals can be applied")
    comp_cycle = db.get(CompensationCycle, proposal.comp_cycle_id)
    current = current_compensation(db, tenant, proposal.employee_id, as_of=comp_cycle.effective_date - timedelta(days=1))
    new_base = _money(_d(proposal.current_base) * (1 + _d(proposal.merit_pct) / 100))
    record = record_compensation(
        db, tenant, employee_id=proposal.employee_id, effective_from=comp_cycle.effective_date, base_amount=new_base,
        currency=current.currency if current else comp_cycle.currency, components=current.components_json if current else None,
        reason=f"{comp_cycle.name}: merit {float(proposal.merit_pct)}%", proposal_id=proposal.id, created_by=actor,
    )
    if proposal.promotion_to_grade:
        lifecycle.apply_event(
            db, tenant, employee_id=proposal.employee_id, event_type="promotion", effective_from=comp_cycle.effective_date,
            changes={"grade": proposal.promotion_to_grade}, reason=comp_cycle.name, created_by=actor,
        )
    letter_id = None
    if letter_template_key:
        from app.core_hr import letters

        try:
            letter_id = letters.generate_letter(
                db, tenant, employee_id=proposal.employee_id, template_key=letter_template_key,
                context={"new_base": new_base, "merit_pct": float(proposal.merit_pct), "bonus": float(proposal.bonus_amount or 0),
                         "effective_date": comp_cycle.effective_date.isoformat(), "new_grade": proposal.promotion_to_grade},
                generated_by=actor,
            ).id
        except letters.LetterTemplateNotFoundError:
            letter_id = None
    proposal.status = "applied"
    db.commit()
    return {"record_id": str(record.id), "new_base": new_base, "letter_id": str(letter_id) if letter_id else None, "already_applied": False}


def export_csv(db: Session, tenant: TenantContext, comp_cycle: CompensationCycle) -> str:
    rows = db.query(CompensationProposal).filter(CompensationProposal.tenant_id == tenant.tenant_id, CompensationProposal.comp_cycle_id == comp_cycle.id).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["employee_id", "current_base", "rating", "compa_ratio", "guideline_min_pct", "guideline_max_pct", "merit_pct", "new_base", "bonus_amount", "promotion_to_grade", "status"])
    for p in rows:
        new_base = _money(_d(p.current_base) * (1 + _d(p.merit_pct) / 100))
        writer.writerow([p.employee_id, p.current_base, p.rating, p.compa_ratio, p.guideline_min_pct, p.guideline_max_pct, p.merit_pct, new_base, p.bonus_amount, p.promotion_to_grade or "", p.status])
    return out.getvalue()


def proposal_to_dict(p: CompensationProposal) -> dict:
    def _f(v):
        return float(v) if v is not None else None

    return {
        "id": str(p.id), "employee_id": str(p.employee_id), "department_id": str(p.department_id) if p.department_id else None,
        "current_base": _f(p.current_base), "rating": _f(p.rating), "compa_ratio": _f(p.compa_ratio),
        "guideline": [_f(p.guideline_min_pct), _f(p.guideline_max_pct)], "merit_pct": _f(p.merit_pct),
        "bonus_amount": _f(p.bonus_amount), "promotion_to_grade": p.promotion_to_grade, "justification": p.justification,
        "status": p.status, "outside_guideline": outside_guideline(p),
    }
