"""CTC breakup builder (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 7) -- tenant-defined
compensation components applied against one Offer's base CTC. Display-only, NOT payroll
(spec's own wording, see app/models/offer_component.py's own docstring) -- plain Python
arithmetic, not a JSONLogic formula engine, since section 7 only asks for "formulas" in
the loose sense of fixed-amount vs. percentage-of-base, not arbitrary expressions."""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.offer import Offer
from app.models.offer_component import OfferComponent
from app.platform.tenancy.context import TenantContext


def create_component(db: Session, tenant: TenantContext, *, code: str, name: str, type: str, value: float, order: float = 0) -> OfferComponent:
    component = OfferComponent(tenant_id=tenant.tenant_id, code=code, name=name, type=type, value=value, order=order)
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


def list_components(db: Session, tenant: TenantContext, *, active_only: bool = True) -> list[OfferComponent]:
    query = db.query(OfferComponent).filter(OfferComponent.tenant_id == tenant.tenant_id)
    if active_only:
        query = query.filter(OfferComponent.is_active.is_(True))
    return query.order_by(OfferComponent.order).all()


def compute_ctc_breakup(db: Session, tenant: TenantContext, *, base_ctc: float) -> dict:
    """Every active component applied against `base_ctc` -- "fixed" components contribute
    their own value unchanged, "percentage_of_base" components contribute `value * base_ctc`
    (value is a fraction, e.g. 0.4 = 40%). Returns {"base_ctc", "components": [...], "total"}."""
    components = list_components(db, tenant)
    breakdown = []
    total = 0.0
    for component in components:
        amount = float(component.value) if component.type == "fixed" else float(component.value) * base_ctc
        breakdown.append({"code": component.code, "name": component.name, "type": component.type, "amount": round(amount, 2)})
        total += amount
    return {"base_ctc": base_ctc, "components": breakdown, "total": round(total, 2)}


def apply_ctc_breakup_to_offer(db: Session, tenant: TenantContext, offer_id: UUID, *, base_ctc: float) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None or offer.tenant_id != tenant.tenant_id:
        raise ValueError("Offer not found")
    offer.ctc_breakup_json = compute_ctc_breakup(db, tenant, base_ctc=base_ctc)
    db.commit()
    db.refresh(offer)
    return offer


def record_counter_offer(db: Session, tenant: TenantContext, offer_id: UUID, *, amount: float, notes: Optional[str] = None) -> Offer:
    from datetime import datetime, timezone

    offer = db.get(Offer, offer_id)
    if offer is None or offer.tenant_id != tenant.tenant_id:
        raise ValueError("Offer not found")
    entries = list(offer.counter_offer_json or [])
    entries.append({"amount": amount, "notes": notes, "recorded_at": datetime.now(timezone.utc).isoformat()})
    offer.counter_offer_json = entries
    db.commit()
    db.refresh(offer)
    return offer


def set_joining_date(db: Session, tenant: TenantContext, offer_id: UUID, *, joining_date) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None or offer.tenant_id != tenant.tenant_id:
        raise ValueError("Offer not found")
    offer.joining_date = joining_date
    db.commit()
    db.refresh(offer)
    return offer
