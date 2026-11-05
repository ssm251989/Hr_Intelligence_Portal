"""Organisation model (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 1) -- legal entities,
business units, departments (a tree via `parent_id`), locations, cost centers, positions,
and the org chart API. Export to PNG/PDF and the Leaflet locations-map (section 1's own
"Leaflet map of locations & headcount") are frontend visualization features this part's
own scoped-down UI doesn't build -- same class of reduction as every other part's admin
surface; the org CHART API itself (the data, not the rendering) is real."""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import Department, Position
from app.platform.tenancy.context import TenantContext


class OrgChartCycleError(Exception):
    pass


def would_create_cycle(db: Session, tenant: TenantContext, position_id: UUID, proposed_reports_to_id: Optional[UUID]) -> bool:
    """Walks proposed_reports_to_id's own chain of reports_to_position_id -- if it ever
    reaches position_id itself, setting this link would create a cycle (section's own
    TESTS: "org chart cycles prevention")."""
    if proposed_reports_to_id is None:
        return False
    seen: set[UUID] = set()
    current = proposed_reports_to_id
    while current is not None:
        if current == position_id:
            return True
        if current in seen:
            return False  # an existing cycle elsewhere -- not this call's problem to solve
        seen.add(current)
        parent = db.get(Position, current)
        current = parent.reports_to_position_id if parent else None
    return False


def set_reports_to(db: Session, tenant: TenantContext, position_id: UUID, reports_to_position_id: Optional[UUID]) -> Position:
    position = db.get(Position, position_id)
    if position is None or position.tenant_id != tenant.tenant_id:
        raise ValueError("Position not found")
    if would_create_cycle(db, tenant, position_id, reports_to_position_id):
        raise OrgChartCycleError(f"Setting reports_to to {reports_to_position_id} would create a cycle")
    position.reports_to_position_id = reports_to_position_id
    db.commit()
    db.refresh(position)
    return position


def org_chart_by_position(db: Session, tenant: TenantContext, root_position_id: Optional[UUID] = None) -> list[dict]:
    """Lazy tree (section's own "lazy tree, search") -- returns only ONE level (the
    root's direct reports, or every position with no reports_to_position_id if
    root_position_id is None) rather than eagerly materializing the whole org; a caller
    fetches deeper levels with a follow-up call per node, the same "load what's visible,
    not everything" principle every other lazy-tree UI in this app already uses."""
    query = db.query(Position).filter(Position.tenant_id == tenant.tenant_id)
    query = query.filter(Position.reports_to_position_id == root_position_id) if root_position_id else query.filter(Position.reports_to_position_id.is_(None))
    return [
        {"id": str(p.id), "code": p.code, "title": p.title, "status": p.status, "is_critical": p.is_critical, "has_children": _has_children(db, tenant, p.id)}
        for p in query.order_by(Position.title).all()
    ]


def _has_children(db: Session, tenant: TenantContext, position_id: UUID) -> bool:
    return db.query(Position).filter(Position.tenant_id == tenant.tenant_id, Position.reports_to_position_id == position_id).first() is not None


def department_tree(db: Session, tenant: TenantContext, root_id: Optional[UUID] = None) -> list[dict]:
    query = db.query(Department).filter(Department.tenant_id == tenant.tenant_id)
    query = query.filter(Department.parent_id == root_id) if root_id else query.filter(Department.parent_id.is_(None))
    return [{"id": str(d.id), "name": d.name} for d in query.order_by(Department.name).all()]


def search_positions(db: Session, tenant: TenantContext, query_text: str, *, limit: int = 25) -> list[Position]:
    pattern = f"%{query_text}%"
    return (
        db.query(Position)
        .filter(Position.tenant_id == tenant.tenant_id)
        .filter((Position.title.ilike(pattern)) | (Position.code.ilike(pattern)))
        .limit(limit)
        .all()
    )
