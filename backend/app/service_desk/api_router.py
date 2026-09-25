"""Helpdesk / assets / separation API (docs/HRMS_COMPLETE_SPEC.txt Part 11).

Agent/HR endpoints are gated by `helpdesk.*`, `assets.*`, `separation.*`; self-service
under `/me/...` (gated by `<module>.self.*`) is always scoped to the caller's own employee
record. Confidential tickets are only visible to holders of `helpdesk.ticket.view_sensitive`,
their assignee, and the requester.
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
from app.models.core_hr import Employee
from app.models.service_desk import (
    Asset,
    AssetAllocation,
    AssetRequest,
    BusinessCalendar,
    ClearanceItem,
    KbArticle,
    Separation,
    SlaPolicy,
    Ticket,
    TicketAssignmentRule,
    TicketComment,
    TicketQueue,
)
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant
from app.service_desk import assets, separations, tickets

router = APIRouter(prefix="/api/v1/service-desk", tags=["service-desk"])


def _get(db: Session, model, row_id: UUID, label: str):
    tenant = require_current_tenant()
    row = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.id == row_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _my_employee(db: Session, user: User, *, required: bool = True) -> Optional[Employee]:
    tenant = require_current_tenant()
    employee = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()
    if employee is None and required:
        raise HTTPException(status_code=404, detail="Your login isn't linked to an employee record yet. Ask HR to link it.")
    return employee


# ---- helpdesk configuration ----


class CalendarUpsert(BaseModel):
    code: str
    name: str
    timezone: str
    location_id: Optional[UUID] = None
    working_days: list[int] = [0, 1, 2, 3, 4]
    start_time: str = "09:00"
    end_time: str = "18:00"
    holidays: list[str] = []


@router.put("/calendars")
def upsert_calendar(payload: CalendarUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.sla.configure"))):
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(payload.timezone)
        date.fromisoformat(payload.holidays[0]) if payload.holidays else None
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown timezone or a holiday isn't YYYY-MM-DD")
    if any(d not in range(7) for d in payload.working_days):
        raise HTTPException(status_code=400, detail="working_days are 0 (Mon) .. 6 (Sun)")
    tenant = require_current_tenant()
    row = db.query(BusinessCalendar).filter(BusinessCalendar.tenant_id == tenant.tenant_id, BusinessCalendar.code == payload.code).first()
    if row is None:
        row = BusinessCalendar(tenant_id=tenant.tenant_id, code=payload.code, name=payload.name, timezone=payload.timezone)
        db.add(row)
    row.name, row.timezone, row.location_id = payload.name, payload.timezone, payload.location_id
    row.working_days, row.start_time, row.end_time, row.holidays_json = payload.working_days, payload.start_time, payload.end_time, payload.holidays
    db.commit()
    return {"id": str(row.id), "code": row.code}


class SlaUpsert(BaseModel):
    name: str
    category_code: Optional[str] = None
    priority: str
    response_minutes: int
    resolution_minutes: int
    calendar_id: Optional[UUID] = None
    use_requester_location_calendar: bool = True
    escalation: list[dict] = []


@router.put("/sla-policies")
def upsert_sla(payload: SlaUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.sla.configure"))):
    if payload.response_minutes <= 0 or payload.resolution_minutes < payload.response_minutes:
        raise HTTPException(status_code=400, detail="Resolution time must be at least the response time, both positive")
    tenant = require_current_tenant()
    query = db.query(SlaPolicy).filter(SlaPolicy.tenant_id == tenant.tenant_id, SlaPolicy.priority == payload.priority)
    query = query.filter(SlaPolicy.category_code == payload.category_code) if payload.category_code else query.filter(SlaPolicy.category_code.is_(None))
    row = query.first()
    if row is None:
        row = SlaPolicy(tenant_id=tenant.tenant_id, priority=payload.priority, category_code=payload.category_code, name=payload.name, response_minutes=0, resolution_minutes=0)
        db.add(row)
    row.name, row.response_minutes, row.resolution_minutes = payload.name, payload.response_minutes, payload.resolution_minutes
    row.calendar_id, row.use_requester_location_calendar, row.escalation_json = payload.calendar_id, payload.use_requester_location_calendar, payload.escalation
    db.commit()
    return {"id": str(row.id)}


@router.get("/sla-policies")
def list_sla(db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.sla.view"))):
    tenant = require_current_tenant()
    return [{"id": str(p.id), "name": p.name, "category_code": p.category_code, "priority": p.priority, "response_minutes": p.response_minutes,
             "resolution_minutes": p.resolution_minutes, "escalation": p.escalation_json} for p in db.query(SlaPolicy).filter(SlaPolicy.tenant_id == tenant.tenant_id).all()]


class QueueUpsert(BaseModel):
    code: str
    name: str
    lead_user_id: Optional[UUID] = None
    confidential: bool = False


@router.put("/queues")
def upsert_queue(payload: QueueUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.queue.configure"))):
    tenant = require_current_tenant()
    row = db.query(TicketQueue).filter(TicketQueue.tenant_id == tenant.tenant_id, TicketQueue.code == payload.code).first()
    if row is None:
        row = TicketQueue(tenant_id=tenant.tenant_id, code=payload.code, name=payload.name)
        db.add(row)
    row.name, row.lead_user_id, row.confidential = payload.name, payload.lead_user_id, payload.confidential
    db.commit()
    return {"id": str(row.id)}


class AssignmentRuleCreate(BaseModel):
    category_code: Optional[str] = None
    strategy: str
    queue_code: str
    agents: list[dict] = []
    required_skills: list[str] = []
    priority: int = 100


@router.post("/assignment-rules", status_code=201)
def create_assignment_rule(payload: AssignmentRuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.queue.configure"))):
    if payload.strategy not in ("round_robin", "skill", "queue"):
        raise HTTPException(status_code=400, detail="strategy is round_robin, skill or queue")
    if payload.strategy != "queue" and any("user_id" not in a for a in payload.agents):
        raise HTTPException(status_code=400, detail="each agent needs a user_id")
    row = TicketAssignmentRule(tenant_id=require_current_tenant().tenant_id, category_code=payload.category_code, strategy=payload.strategy,
                               queue_code=payload.queue_code, agents_json=payload.agents, required_skills_json=payload.required_skills, priority=payload.priority)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


# ---- tickets ----


class TicketCreate(BaseModel):
    category_code: str
    subcategory_code: Optional[str] = None
    subject: str
    description: Optional[str] = None
    priority: str = "medium"
    channel: str = "portal"


def _ticket_view(db: Session, ticket: Ticket) -> dict:
    return tickets.ticket_to_dict(ticket, sla=tickets.sla_status(db, ticket))


@router.post("/me/tickets", status_code=201)
def raise_ticket(payload: TicketCreate, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.create"))):
    me = _my_employee(db, current_user, required=False)
    try:
        ticket = tickets.create_ticket(db, require_current_tenant(), requester_employee_id=me.id if me else None, requester_user_id=current_user.id,
                                       requester_email=current_user.email, **payload.model_dump())
    except tickets.TicketError as exc:
        raise _bad(exc)
    return _ticket_view(db, ticket)


@router.get("/me/tickets")
def my_tickets(db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    tenant = require_current_tenant()
    rows = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.requester_user_id == current_user.id).order_by(Ticket.created_at.desc()).all()
    return [_ticket_view(db, t) for t in rows]


@router.get("/tickets")
def list_tickets(status: Optional[str] = None, queue_code: Optional[str] = None, assignee: Optional[str] = None, page: int = 1, page_size: int = 25,
                 db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.ticket.view"))):
    tenant = require_current_tenant()
    confidential_ok = has_permission(db, tenant, current_user, "helpdesk.ticket.view_sensitive")
    query = tickets.visible_query(db, tenant, user=current_user, can_view_confidential=confidential_ok)
    if status:
        query = query.filter(Ticket.status == status)
    if queue_code:
        query = query.filter(Ticket.queue_code == queue_code)
    if assignee == "me":
        query = query.filter(Ticket.assignee_user_id == current_user.id)
    page_size = max(1, min(page_size, 100))
    total = query.count()
    rows = query.order_by(Ticket.created_at.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_ticket_view(db, t) for t in rows]}


def _visible_ticket(db: Session, ticket_id: UUID, user: User) -> Ticket:
    tenant = require_current_tenant()
    ticket = _get(db, Ticket, ticket_id, "Ticket")
    me = _my_employee(db, user, required=False)
    if not tickets.can_view(ticket, user=user, employee_id=me.id if me else None,
                            is_agent=has_permission(db, tenant, user, "helpdesk.ticket.view"),
                            can_view_confidential=has_permission(db, tenant, user, "helpdesk.ticket.view_sensitive")):
        raise HTTPException(status_code=404, detail="Ticket not found")  # never confirm a confidential ticket exists
    return ticket


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    tenant = require_current_tenant()
    ticket = _visible_ticket(db, ticket_id, current_user)
    is_agent = has_permission(db, tenant, current_user, "helpdesk.ticket.view")
    comments = db.query(TicketComment).filter(TicketComment.tenant_id == tenant.tenant_id, TicketComment.ticket_id == ticket.id).order_by(TicketComment.created_at.asc()).all()
    return {**_ticket_view(db, ticket), "comments": [
        {"author": c.author, "body": c.body, "internal": c.internal, "is_agent": c.author_is_agent, "at": c.created_at.isoformat() if c.created_at else None}
        for c in comments if is_agent or not c.internal
    ]}


class CommentCreate(BaseModel):
    body: str
    internal: bool = False


@router.post("/tickets/{ticket_id}/comments", status_code=201)
def comment(ticket_id: UUID, payload: CommentCreate, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    tenant = require_current_tenant()
    ticket = _visible_ticket(db, ticket_id, current_user)
    is_agent = has_permission(db, tenant, current_user, "helpdesk.ticket.edit") and ticket.requester_user_id != current_user.id
    try:
        row = tickets.add_comment(db, tenant, ticket, author=current_user.email, body=payload.body, is_agent=is_agent, internal=payload.internal)
    except tickets.TicketError as exc:
        raise _bad(exc)
    return {"id": str(row.id)}


class StatusChange(BaseModel):
    status: str


@router.post("/tickets/{ticket_id}/status")
def ticket_status(ticket_id: UUID, payload: StatusChange, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.ticket.edit"))):
    ticket = _visible_ticket(db, ticket_id, current_user)
    try:
        tickets.change_status(db, require_current_tenant(), ticket, payload.status)
    except tickets.TicketError as exc:
        raise _bad(exc)
    return _ticket_view(db, ticket)


class AssignRequest(BaseModel):
    assignee_user_id: Optional[UUID] = None
    queue_code: Optional[str] = None


@router.post("/tickets/{ticket_id}/assign")
def ticket_assign(ticket_id: UUID, payload: AssignRequest, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.ticket.edit"))):
    ticket = _visible_ticket(db, ticket_id, current_user)
    if payload.queue_code:
        ticket.queue_code = payload.queue_code
    ticket.assignee_user_id = payload.assignee_user_id
    db.commit()
    log_action(db, "ticket", ticket.id, "ticket_reassigned", current_user.email, {"assignee": str(payload.assignee_user_id) if payload.assignee_user_id else None})
    return _ticket_view(db, ticket)


class Csat(BaseModel):
    score: int
    comment: Optional[str] = None


@router.post("/me/tickets/{ticket_id}/csat")
def ticket_csat(ticket_id: UUID, payload: Csat, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    ticket = _get(db, Ticket, ticket_id, "Ticket")
    if ticket.requester_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the requester can rate a ticket")
    try:
        tickets.record_csat(db, ticket, score=payload.score, comment=payload.comment)
    except tickets.TicketError as exc:
        raise _bad(exc)
    return {"csat_score": ticket.csat_score}


@router.post("/tickets/process-escalations")
def run_escalations(db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.sla.configure"))):
    return {"escalated": tickets.process_escalations(db, require_current_tenant())}


@router.post("/inbound/{inbound_message_id}/to-ticket", status_code=201)
def inbound_to_ticket(inbound_message_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.ticket.create"))):
    """Turn an unmatched message from the helpdesk mailbox into a ticket (the poller calls
    tickets.ticket_from_email directly for mailboxes routed to email.inbound.helpdesk)."""
    from app.models.comms import InboundMessage

    row = _get(db, InboundMessage, inbound_message_id, "Inbound message")
    try:
        return _ticket_view(db, tickets.ticket_from_email(db, require_current_tenant(), row))
    except tickets.TicketError as exc:
        raise _bad(exc)


# ---- knowledge base ----


class KbUpsert(BaseModel):
    slug: str
    title: str
    body: str
    category_code: Optional[str] = None
    tags: list[str] = []
    status: str = "draft"


@router.put("/kb")
def upsert_kb(payload: KbUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.kb.edit"))):
    if payload.status not in ("draft", "published", "archived"):
        raise HTTPException(status_code=400, detail="status is draft, published or archived")
    tenant = require_current_tenant()
    row = db.query(KbArticle).filter(KbArticle.tenant_id == tenant.tenant_id, KbArticle.slug == payload.slug).first()
    if row is None:
        row = KbArticle(tenant_id=tenant.tenant_id, slug=payload.slug, title=payload.title, body=payload.body)
        db.add(row)
    row.title, row.body, row.category_code, row.tags_json, row.status = payload.title, payload.body, payload.category_code, payload.tags, payload.status
    db.commit()
    return {"id": str(row.id), "slug": row.slug, "status": row.status}


@router.get("/kb/search")
def kb_search(q: str, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    """Shown before a ticket is raised -- the deflection step."""
    return [{"id": str(a.id), "slug": a.slug, "title": a.title, "excerpt": a.body[:280]} for a in tickets.search_kb(db, require_current_tenant(), q)]


class Deflection(BaseModel):
    helpful: bool


@router.post("/kb/{article_id}/deflected")
def kb_deflected(article_id: UUID, payload: Deflection, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    tickets.record_deflection(db, _get(db, KbArticle, article_id, "Article"), helpful=payload.helpful)
    return {"ok": True}


# ---- assets ----


class AssetCreate(BaseModel):
    asset_tag: str
    category_code: str
    name: str
    serial_number: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_cost: Optional[float] = None
    currency: Optional[str] = None
    warranty_until: Optional[date] = None
    vendor: Optional[str] = None
    location_id: Optional[UUID] = None
    depreciation_json: Optional[dict] = None


@router.post("/assets", status_code=201)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.create"))):
    try:
        asset = assets.register_asset(db, require_current_tenant(), **payload.model_dump())
    except assets.AssetError as exc:
        raise _bad(exc)
    return assets.asset_to_dict(asset)


@router.get("/assets")
def list_assets(status: Optional[str] = None, category_code: Optional[str] = None, page: int = 1, page_size: int = 25,
                db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.view"))):
    tenant = require_current_tenant()
    query = db.query(Asset).filter(Asset.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(Asset.status == status)
    if category_code:
        query = query.filter(Asset.category_code == category_code)
    page_size = max(1, min(page_size, 100))
    total = query.count()
    rows = query.order_by(Asset.asset_tag).offset((max(page, 1) - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [assets.asset_to_dict(a, allocation=assets.active_allocation(db, tenant, a.id)) for a in rows]}


class Allocate(BaseModel):
    employee_id: UUID


@router.post("/assets/{asset_id}/allocate", status_code=201)
def allocate_asset(asset_id: UUID, payload: Allocate, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.edit"))):
    try:
        allocation = assets.allocate(db, require_current_tenant(), _get(db, Asset, asset_id, "Asset"), employee_id=payload.employee_id, actor=current_user.email)
    except assets.AssetError as exc:
        raise _bad(exc)
    return {"allocation_id": str(allocation.id)}


class AssetReturn(BaseModel):
    condition: str
    notes: Optional[str] = None


@router.post("/allocations/{allocation_id}/return")
def return_asset(allocation_id: UUID, payload: AssetReturn, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.edit"))):
    try:
        allocation = assets.return_asset(db, require_current_tenant(), _get(db, AssetAllocation, allocation_id, "Allocation"),
                                         condition=payload.condition, received_by=current_user.email, notes=payload.notes)
    except assets.AssetError as exc:
        raise _bad(exc)
    return {"returned_at": allocation.returned_at.isoformat()}


class Acknowledge(BaseModel):
    text: str


@router.post("/me/allocations/{allocation_id}/acknowledge")
def acknowledge_asset(allocation_id: UUID, payload: Acknowledge, db: Session = Depends(get_db), current_user: User = Depends(require("assets.self.view"))):
    me = _my_employee(db, current_user)
    allocation = _get(db, AssetAllocation, allocation_id, "Allocation")
    if allocation.employee_id != me.id:
        raise HTTPException(status_code=404, detail="Allocation not found")
    assets.acknowledge(db, allocation, text=payload.text)
    return {"acknowledged_at": allocation.acknowledged_at.isoformat()}


@router.get("/me/assets")
def my_assets(db: Session = Depends(get_db), current_user: User = Depends(require("assets.self.view"))):
    me = _my_employee(db, current_user)
    tenant = require_current_tenant()
    return [{**assets.asset_to_dict(db.get(Asset, a.asset_id)), "allocation_id": str(a.id), "acknowledged": a.acknowledged_at is not None}
            for a in assets.employee_assets(db, tenant, me.id)]


class AssetRequestCreate(BaseModel):
    category_code: str
    reason: Optional[str] = None


@router.post("/me/asset-requests", status_code=201)
def request_asset(payload: AssetRequestCreate, db: Session = Depends(get_db), current_user: User = Depends(require("assets.self.create"))):
    me = _my_employee(db, current_user)
    try:
        row = assets.request_asset(db, require_current_tenant(), employee_id=me.id, actor=current_user.email, actor_user_id=current_user.id, **payload.model_dump())
    except assets.AssetError as exc:
        raise _bad(exc)
    return {"id": str(row.id), "status": row.status}


class Decision(BaseModel):
    approve: bool


@router.post("/asset-requests/{request_id}/decision")
def decide_asset_request(request_id: UUID, payload: Decision, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.approve"))):
    try:
        row = assets.decide_request(db, _get(db, AssetRequest, request_id, "Request"), approve=payload.approve)
    except assets.AssetError as exc:
        raise _bad(exc)
    return {"id": str(row.id), "status": row.status}


class Fulfil(BaseModel):
    asset_id: Optional[UUID] = None


@router.post("/asset-requests/{request_id}/fulfil")
def fulfil_asset_request(request_id: UUID, payload: Fulfil, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.edit"))):
    try:
        allocation = assets.fulfil_request(db, require_current_tenant(), _get(db, AssetRequest, request_id, "Request"), actor=current_user.email, asset_id=payload.asset_id)
    except assets.AssetError as exc:
        raise _bad(exc)
    return {"allocation_id": str(allocation.id)}


class Maintenance(BaseModel):
    performed_on: date
    description: str
    cost: Optional[float] = None
    vendor: Optional[str] = None


@router.post("/assets/{asset_id}/maintenance", status_code=201)
def log_maintenance(asset_id: UUID, payload: Maintenance, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.edit"))):
    row = assets.log_maintenance(db, require_current_tenant(), _get(db, Asset, asset_id, "Asset"), actor=current_user.email, **payload.model_dump())
    return {"id": str(row.id)}


# ---- separation ----


class ResignationCreate(BaseModel):
    requested_lwd: Optional[date] = None
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None


@router.post("/me/resignation", status_code=201)
def resign(payload: ResignationCreate, db: Session = Depends(get_db), current_user: User = Depends(require("separation.self.create"))):
    me = _my_employee(db, current_user)
    try:
        row = separations.initiate(db, require_current_tenant(), employee_id=me.id, separation_type="resignation", actor=current_user.email,
                                   actor_user_id=current_user.id, **payload.model_dump())
    except separations.SeparationError as exc:
        raise _bad(exc)
    return separations.exit_summary(db, row)


class SeparationCreate(BaseModel):
    employee_id: UUID
    separation_type: str
    submitted_on: Optional[date] = None
    requested_lwd: Optional[date] = None
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None


@router.post("/separations", status_code=201)
def initiate_separation(payload: SeparationCreate, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.create"))):
    try:
        row = separations.initiate(db, require_current_tenant(), actor=current_user.email, actor_user_id=current_user.id, **payload.model_dump())
    except separations.SeparationError as exc:
        raise _bad(exc)
    log_action(db, "separation", row.id, "separation_initiated", current_user.email, {"type": row.separation_type})
    return separations.exit_summary(db, row)


@router.get("/separations")
def list_separations(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.view"))):
    tenant = require_current_tenant()
    query = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(Separation.status == status)
    return [separations.exit_summary(db, s) for s in query.order_by(Separation.created_at.desc()).all()]


@router.get("/separations/{separation_id}")
def get_separation(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.view"))):
    row = _get(db, Separation, separation_id, "Separation")
    items = db.query(ClearanceItem).filter(ClearanceItem.tenant_id == row.tenant_id, ClearanceItem.separation_id == row.id).all()
    return {**separations.exit_summary(db, row), "clearance": [separations.item_to_dict(i) for i in items],
            "relieving_blockers": separations.relieving_blockers(db, row), "exit_interview": row.exit_interview_json,
            "exit_interview_ai_summary": row.exit_interview_ai_summary_json, "absconding_notices": row.absconding_notices_json}


class Retention(BaseModel):
    notes: str
    retained: bool


@router.post("/separations/{separation_id}/retention")
def retention(separation_id: UUID, payload: Retention, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.edit"))):
    try:
        row = separations.record_retention(db, _get(db, Separation, separation_id, "Separation"), actor=current_user.email, **payload.model_dump())
    except separations.SeparationError as exc:
        raise _bad(exc)
    return separations.exit_summary(db, row)


class LwdApproval(BaseModel):
    lwd: date
    waived_days: int = 0
    buyout_days: int = 0


@router.post("/separations/{separation_id}/approve-lwd")
def approve_lwd(separation_id: UUID, payload: LwdApproval, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.approve"))):
    try:
        row = separations.approve_lwd(db, require_current_tenant(), _get(db, Separation, separation_id, "Separation"), actor=current_user.email, **payload.model_dump())
    except separations.SeparationError as exc:
        raise _bad(exc)
    return separations.exit_summary(db, row)


@router.post("/separations/{separation_id}/withdraw")
def withdraw(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.edit"))):
    try:
        row = separations.withdraw(db, _get(db, Separation, separation_id, "Separation"), actor=current_user.email)
    except separations.SeparationError as exc:
        raise _bad(exc)
    return separations.exit_summary(db, row)


class ClearanceUpdate(BaseModel):
    waive: bool = False
    notes: Optional[str] = None
    amount_due: Optional[float] = None


@router.post("/clearance-items/{item_id}/clear")
def clear_item(item_id: UUID, payload: ClearanceUpdate, db: Session = Depends(get_db), current_user: User = Depends(require("separation.clearance.edit"))):
    try:
        item = separations.clear_item(db, _get(db, ClearanceItem, item_id, "Clearance item"), actor=current_user.email, **payload.model_dump())
    except separations.SeparationError as exc:
        raise _bad(exc)
    return separations.item_to_dict(item)


class KtTask(BaseModel):
    title: str
    owner_user_id: Optional[UUID] = None
    blocks_relieving: bool = False


@router.post("/separations/{separation_id}/kt-tasks", status_code=201)
def add_kt(separation_id: UUID, payload: KtTask, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.edit"))):
    item = separations.add_kt_task(db, require_current_tenant(), _get(db, Separation, separation_id, "Separation"), **payload.model_dump())
    return separations.item_to_dict(item)


class ExitInterview(BaseModel):
    answers: dict


@router.post("/separations/{separation_id}/exit-interview")
def exit_interview(separation_id: UUID, payload: ExitInterview, summarize: bool = False, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.edit"))):
    tenant = require_current_tenant()
    row = separations.submit_exit_interview(db, _get(db, Separation, separation_id, "Separation"), answers=payload.answers)
    if summarize:
        row = separations.summarize_exit_interview(db, tenant, row)
    return {"exit_interview": row.exit_interview_json, "ai_summary": row.exit_interview_ai_summary_json}


class AbscondingNotice(BaseModel):
    template_key: str
    context: dict = {}


@router.post("/separations/{separation_id}/absconding-notices", status_code=201)
def absconding_notice(separation_id: UUID, payload: AbscondingNotice, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.edit"))):
    from app.core_hr.letters import LetterTemplateNotFoundError

    try:
        return separations.issue_absconding_notice(db, require_current_tenant(), _get(db, Separation, separation_id, "Separation"), actor=current_user.email, **payload.model_dump())
    except (separations.SeparationError, LetterTemplateNotFoundError) as exc:
        raise _bad(exc)


class RelievingLetter(BaseModel):
    template_key: Optional[str] = None
    experience_template_key: Optional[str] = None


@router.post("/separations/{separation_id}/relieving-letter")
def relieving_letter(separation_id: UUID, payload: RelievingLetter, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.approve"))):
    from app.core_hr.letters import LetterTemplateNotFoundError

    try:
        return separations.issue_relieving_letter(db, require_current_tenant(), _get(db, Separation, separation_id, "Separation"), actor=current_user.email, **payload.model_dump())
    except separations.ClearanceBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (separations.SeparationError, LetterTemplateNotFoundError) as exc:
        raise _bad(exc)


class Complete(BaseModel):
    rehire_eligible: bool
    alumni_opt_in: bool = False
    regretted: Optional[bool] = None


@router.post("/separations/{separation_id}/complete")
def complete(separation_id: UUID, payload: Complete, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.approve"))):
    try:
        row = separations.complete(db, require_current_tenant(), _get(db, Separation, separation_id, "Separation"), actor=current_user.email, **payload.model_dump())
    except separations.ClearanceBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except separations.SeparationError as exc:
        raise _bad(exc)
    log_action(db, "separation", row.id, "separation_completed", current_user.email, {"rehire_eligible": payload.rehire_eligible})
    return separations.exit_summary(db, row)


@router.get("/separations-export", response_class=PlainTextResponse)
def export_separations(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.export"))):
    tenant = require_current_tenant()
    query = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(Separation.status == status)
    return PlainTextResponse(separations.export_csv(db, query.all()), media_type="text/csv")
