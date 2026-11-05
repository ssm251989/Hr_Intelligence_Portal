"""Assets (docs/HRMS_COMPLETE_SPEC.txt Part 11 section B): register, allocation/return
with acknowledgement, requests via workflow, maintenance log, optional straight-line
depreciation, and the onboarding/exit hooks (auto-allocate from a request / clearance
recovery items at separation)."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.metadata import MasterValue
from app.models.service_desk import Asset, AssetAllocation, AssetMaintenance, AssetRequest
from app.models.workflow import WorkflowDefinition
from app.platform.tenancy.context import TenantContext


class AssetError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_category(db: Session, tenant: TenantContext, code: str) -> None:
    exists = db.query(MasterValue).filter(
        MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "asset_category", MasterValue.code == code, MasterValue.is_active.is_(True),
    ).first()
    if exists is None:
        raise AssetError(f"{code!r} is not an active asset category")


def register_asset(db: Session, tenant: TenantContext, *, asset_tag: str, category_code: str, name: str, **fields) -> Asset:
    _require_category(db, tenant, category_code)
    allowed = {"serial_number", "purchase_date", "purchase_cost", "currency", "warranty_until", "vendor", "location_id", "depreciation_json", "custom_fields"}
    asset = Asset(tenant_id=tenant.tenant_id, asset_tag=asset_tag, category_code=category_code, name=name, **{k: v for k, v in fields.items() if k in allowed and v is not None})
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def active_allocation(db: Session, tenant: TenantContext, asset_id: UUID) -> Optional[AssetAllocation]:
    return db.query(AssetAllocation).filter(AssetAllocation.tenant_id == tenant.tenant_id, AssetAllocation.asset_id == asset_id, AssetAllocation.returned_at.is_(None)).first()


def allocate(db: Session, tenant: TenantContext, asset: Asset, *, employee_id: UUID, actor: str) -> AssetAllocation:
    if asset.status != "in_stock":
        raise AssetError(f"asset {asset.asset_tag} is {asset.status}, not in stock")
    allocation = AssetAllocation(tenant_id=tenant.tenant_id, asset_id=asset.id, employee_id=employee_id, allocated_by=actor)
    asset.status = "allocated"
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return allocation


def acknowledge(db: Session, allocation: AssetAllocation, *, text: str) -> AssetAllocation:
    if allocation.acknowledged_at is None:
        allocation.acknowledged_at = _now()
        allocation.acknowledgement_text = text
        db.commit()
        db.refresh(allocation)
    return allocation


def return_asset(db: Session, tenant: TenantContext, allocation: AssetAllocation, *, condition: str, received_by: str, notes: Optional[str] = None) -> AssetAllocation:
    if allocation.returned_at is not None:
        return allocation
    if condition not in ("good", "damaged", "lost"):
        raise AssetError("condition is good, damaged or lost")
    allocation.returned_at = _now()
    allocation.return_condition = condition
    allocation.received_by = received_by
    allocation.return_notes = notes
    asset = db.get(Asset, allocation.asset_id)
    asset.status = {"good": "in_stock", "damaged": "in_repair", "lost": "lost"}[condition]
    db.commit()
    # A return closes any clearance item that was waiting on it (exit hook).
    from app.service_desk import separations

    separations.on_asset_returned(db, tenant, allocation, actor=received_by)
    db.refresh(allocation)
    return allocation


def employee_assets(db: Session, tenant: TenantContext, employee_id: UUID) -> list[AssetAllocation]:
    return db.query(AssetAllocation).filter(AssetAllocation.tenant_id == tenant.tenant_id, AssetAllocation.employee_id == employee_id, AssetAllocation.returned_at.is_(None)).all()


def log_maintenance(db: Session, tenant: TenantContext, asset: Asset, *, performed_on: date, description: str, cost=None, vendor=None, actor: Optional[str] = None) -> AssetMaintenance:
    row = AssetMaintenance(tenant_id=tenant.tenant_id, asset_id=asset.id, performed_on=performed_on, description=description, cost=cost, vendor=vendor, created_by=actor)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def book_value(asset: Asset, *, as_of: Optional[date] = None) -> Optional[float]:
    """Straight-line depreciation, monthly, never below salvage. None when not configured."""
    config = asset.depreciation_json or {}
    if config.get("method") != "straight_line" or asset.purchase_cost is None or asset.purchase_date is None:
        return None
    as_of = as_of or date.today()
    life = int(config.get("life_months") or 0)
    salvage = Decimal(str(config.get("salvage_value", 0)))
    cost = Decimal(str(asset.purchase_cost))
    if life <= 0:
        return float(cost)
    months = max(0, (as_of.year - asset.purchase_date.year) * 12 + as_of.month - asset.purchase_date.month)
    value = cost - (cost - salvage) * Decimal(min(months, life)) / Decimal(life)
    return float(max(value, salvage).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---- requests ----


def request_asset(db: Session, tenant: TenantContext, *, employee_id: UUID, category_code: str, reason: Optional[str] = None,
                  source: str = "employee", actor: Optional[str] = None, actor_user_id: Optional[UUID] = None) -> AssetRequest:
    _require_category(db, tenant, category_code)
    request = AssetRequest(tenant_id=tenant.tenant_id, employee_id=employee_id, category_code=category_code, reason=reason, source=source)
    db.add(request)
    db.commit()
    definition = (
        db.query(WorkflowDefinition)
        .filter(WorkflowDefinition.tenant_id == tenant.tenant_id, WorkflowDefinition.key == "asset_request", WorkflowDefinition.status == "published")
        .order_by(WorkflowDefinition.version.desc())
        .first()
    )
    if definition is not None:
        from app.platform.workflow.engine import start_instance

        instance = start_instance(db, tenant, definition, entity_type="asset_request", entity_id=request.id,
                                  context={"employee_id": str(employee_id), "category": category_code}, started_by=actor, started_by_user_id=actor_user_id)
        request.workflow_instance_id = instance.id
    else:
        request.status = "approved"  # no approval workflow configured -> straight to fulfilment
    db.commit()
    db.refresh(request)
    return request


def decide_request(db: Session, request: AssetRequest, *, approve: bool) -> AssetRequest:
    if request.status != "requested":
        raise AssetError(f"request is already {request.status}")
    request.status = "approved" if approve else "rejected"
    db.commit()
    db.refresh(request)
    return request


def fulfil_request(db: Session, tenant: TenantContext, request: AssetRequest, *, actor: str, asset_id: Optional[UUID] = None) -> AssetAllocation:
    """Picks the given asset, or the first in-stock one of the requested category."""
    if request.status != "approved":
        raise AssetError("only approved requests can be fulfilled")
    query = db.query(Asset).filter(Asset.tenant_id == tenant.tenant_id, Asset.status == "in_stock", Asset.category_code == request.category_code)
    asset = query.filter(Asset.id == asset_id).first() if asset_id else query.order_by(Asset.created_at.asc()).first()
    if asset is None:
        raise AssetError(f"no in-stock {request.category_code} asset available")
    allocation = allocate(db, tenant, asset, employee_id=request.employee_id, actor=actor)
    request.status = "fulfilled"
    request.fulfilled_allocation_id = allocation.id
    db.commit()
    return allocation


def asset_to_dict(a: Asset, *, allocation: Optional[AssetAllocation] = None) -> dict:
    return {
        "id": str(a.id), "asset_tag": a.asset_tag, "category_code": a.category_code, "name": a.name, "serial_number": a.serial_number,
        "status": a.status, "warranty_until": a.warranty_until.isoformat() if a.warranty_until else None, "vendor": a.vendor,
        "book_value": book_value(a),
        "allocated_to": str(allocation.employee_id) if allocation else None,
    }
