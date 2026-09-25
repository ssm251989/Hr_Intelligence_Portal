"""HR helpdesk (docs/HRMS_COMPLETE_SPEC.txt Part 11 section A): tickets on `ticket_category`
masters, SLA policy per category/priority with business-hours timers from the requester's
location calendar, assignment rules (round-robin / skill / queue), escalation, CSAT,
email-to-ticket (`email.inbound.helpdesk`), knowledge base with deflection tracking, and
confidential categories (POSH / grievance / whistle-blower) with restricted visibility.

A category master value's `attributes_json` carries its behaviour: {"confidential": true,
"queue": "<queue code>"} -- tenant data, not code.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core_hr import lifecycle
from app.models.core_hr import Employee
from app.models.metadata import MasterValue
from app.models.service_desk import (
    TICKET_CHANNELS,
    TICKET_PRIORITIES,
    BusinessCalendar,
    KbArticle,
    SlaPolicy,
    Ticket,
    TicketAssignmentRule,
    TicketComment,
    TicketQueue,
)
from app.models.user import User
from app.platform.metadata.sequences import SequenceNotFoundError, define, next_value
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext
from app.service_desk.business_hours import Hours, add_business_minutes, business_minutes_between

TICKET_SEQUENCE_KEY = "helpdesk.ticket_number"
DEFAULT_TICKET_PATTERN = "TKT-{SEQ:6}"
OPEN_STATUSES = ("open", "in_progress", "waiting_on_requester")


class TicketError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant: TenantContext, key: str):
    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _category(db: Session, tenant: TenantContext, code: str) -> MasterValue:
    value = db.query(MasterValue).filter(
        MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "ticket_category", MasterValue.code == code, MasterValue.is_active.is_(True),
    ).first()
    if value is None:
        raise TicketError(f"{code!r} is not an active ticket category")
    return value


def _ticket_number(db: Session, tenant: TenantContext) -> str:
    try:
        return next_value(db, tenant, TICKET_SEQUENCE_KEY)
    except SequenceNotFoundError:
        define(db, tenant, key=TICKET_SEQUENCE_KEY, pattern=DEFAULT_TICKET_PATTERN, reset="never")
        return next_value(db, tenant, TICKET_SEQUENCE_KEY)


# ---- SLA ----


def find_policy(db: Session, tenant: TenantContext, category_code: str, priority: str) -> Optional[SlaPolicy]:
    base = db.query(SlaPolicy).filter(SlaPolicy.tenant_id == tenant.tenant_id, SlaPolicy.priority == priority)
    return base.filter(SlaPolicy.category_code == category_code).first() or base.filter(SlaPolicy.category_code.is_(None)).first()


def resolve_calendar(db: Session, tenant: TenantContext, policy: Optional[SlaPolicy], requester_employee_id: Optional[UUID]) -> Optional[BusinessCalendar]:
    if policy is not None and policy.use_requester_location_calendar and requester_employee_id:
        employment = lifecycle.get_current_employment(db, tenant, requester_employee_id)
        if employment and employment.location_id:
            calendar = db.query(BusinessCalendar).filter(BusinessCalendar.tenant_id == tenant.tenant_id, BusinessCalendar.location_id == employment.location_id).first()
            if calendar is not None:
                return calendar
    if policy is not None and policy.calendar_id:
        return db.get(BusinessCalendar, policy.calendar_id)
    return db.query(BusinessCalendar).filter(BusinessCalendar.tenant_id == tenant.tenant_id, BusinessCalendar.code == "default").first()


def _add(start: datetime, minutes: int, calendar: Optional[BusinessCalendar]) -> datetime:
    """No calendar configured -> wall-clock minutes (24x7), never a silent failure."""
    if calendar is None:
        return start + timedelta(minutes=minutes)
    return add_business_minutes(start, minutes, Hours.from_calendar(calendar))


def _elapsed(a: datetime, b: datetime, calendar: Optional[BusinessCalendar]) -> int:
    if calendar is None:
        return max(0, int((b - a).total_seconds() // 60))
    return business_minutes_between(a, b, Hours.from_calendar(calendar))


def apply_sla(db: Session, tenant: TenantContext, ticket: Ticket, *, start: Optional[datetime] = None) -> None:
    policy = find_policy(db, tenant, ticket.category_code, ticket.priority)
    ticket.sla_policy_id = policy.id if policy else None
    if policy is None:
        ticket.response_due_at = ticket.resolution_due_at = None
        return
    calendar = resolve_calendar(db, tenant, policy, ticket.requester_employee_id)
    ticket.calendar_id = calendar.id if calendar else None
    start = start or ticket.created_at or _now()
    ticket.response_due_at = _add(start, policy.response_minutes, calendar)
    ticket.resolution_due_at = _add(start, policy.resolution_minutes, calendar)


def sla_status(db: Session, ticket: Ticket, *, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    policy = db.get(SlaPolicy, ticket.sla_policy_id) if ticket.sla_policy_id else None
    if policy is None:
        return {"has_sla": False}
    calendar = db.get(BusinessCalendar, ticket.calendar_id) if ticket.calendar_id else None
    effective_now = ticket.paused_at or ticket.resolved_at or now
    responded = ticket.first_responded_at
    total = policy.resolution_minutes
    remaining = _elapsed(effective_now, ticket.resolution_due_at, calendar) if ticket.resolution_due_at and effective_now < ticket.resolution_due_at else 0
    return {
        "has_sla": True,
        "response_due_at": ticket.response_due_at.isoformat() if ticket.response_due_at else None,
        "resolution_due_at": ticket.resolution_due_at.isoformat() if ticket.resolution_due_at else None,
        "response_breached": bool(ticket.response_due_at and (responded or now) > ticket.response_due_at),
        "resolution_breached": bool(ticket.resolution_due_at and effective_now > ticket.resolution_due_at),
        "resolution_elapsed_pct": round(100 * (total - remaining) / total, 1) if total else 100.0,
        "paused": ticket.paused_at is not None,
    }


# ---- assignment ----


def _open_load(db: Session, tenant: TenantContext, user_id: str) -> int:
    return db.query(func.count(Ticket.id)).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.assignee_user_id == user_id, Ticket.status.in_(OPEN_STATUSES)).scalar() or 0


def assign(db: Session, tenant: TenantContext, ticket: Ticket) -> Optional[str]:
    rules = db.query(TicketAssignmentRule).filter(TicketAssignmentRule.tenant_id == tenant.tenant_id).order_by(TicketAssignmentRule.priority.asc()).all()
    rule = next((r for r in rules if r.category_code == ticket.category_code), None) or next((r for r in rules if r.category_code is None), None)
    if rule is None:
        return None
    ticket.queue_code = ticket.queue_code or rule.queue_code
    agents = list(rule.agents_json or [])
    if rule.strategy == "queue" or not agents:
        return None
    if rule.strategy == "round_robin":
        agent = agents[rule.cursor % len(agents)]
        rule.cursor = (rule.cursor + 1) % len(agents)
    else:  # skill
        needed = set(rule.required_skills_json or [])
        qualified = [a for a in agents if needed <= set(a.get("skills", []))]
        if not qualified:
            return None
        agent = min(qualified, key=lambda a: (_open_load(db, tenant, a["user_id"]), a["user_id"]))
    ticket.assignee_user_id = agent["user_id"]
    return agent["user_id"]


# ---- lifecycle ----


def create_ticket(
    db: Session, tenant: TenantContext, *, category_code: str, subject: str, description: Optional[str] = None,
    priority: str = "medium", channel: str = "portal", subcategory_code: Optional[str] = None,
    requester_employee_id: Optional[UUID] = None, requester_user_id: Optional[UUID] = None, requester_email: Optional[str] = None,
    inbound_message_id: Optional[UUID] = None, now: Optional[datetime] = None,
) -> Ticket:
    if priority not in TICKET_PRIORITIES:
        raise TicketError(f"priority must be one of {TICKET_PRIORITIES}")
    if channel not in TICKET_CHANNELS:
        raise TicketError(f"channel must be one of {TICKET_CHANNELS}")
    category = _category(db, tenant, category_code)
    if subcategory_code:
        sub = _category(db, tenant, subcategory_code)
        if sub.parent_id != category.id:
            raise TicketError(f"{subcategory_code!r} is not a subcategory of {category_code!r}")
    attrs = category.attributes_json or {}
    queue_code = attrs.get("queue")
    confidential = bool(attrs.get("confidential"))
    if queue_code:
        queue = db.query(TicketQueue).filter(TicketQueue.tenant_id == tenant.tenant_id, TicketQueue.code == queue_code).first()
        confidential = confidential or bool(queue and queue.confidential)
    created = now or _now()
    ticket = Ticket(
        tenant_id=tenant.tenant_id, number=_ticket_number(db, tenant), category_code=category_code, subcategory_code=subcategory_code,
        priority=priority, subject=subject, description=description, channel=channel, requester_employee_id=requester_employee_id,
        requester_user_id=requester_user_id, requester_email=requester_email, queue_code=queue_code, confidential=confidential,
        inbound_message_id=inbound_message_id, created_at=created,
    )
    db.add(ticket)
    db.flush()
    apply_sla(db, tenant, ticket, start=created)
    assign(db, tenant, ticket)
    db.commit()
    db.refresh(ticket)
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, "helpdesk.ticket_created", {"ticket_id": str(ticket.id), "number": ticket.number, "category": category_code,
                                                           "confidential": confidential, "requester_email": requester_email})
    return ticket


def add_comment(db: Session, tenant: TenantContext, ticket: Ticket, *, author: str, body: str, is_agent: bool, internal: bool = False,
                now: Optional[datetime] = None) -> TicketComment:
    if internal and not is_agent:
        raise TicketError("only agents can add internal notes")
    comment = TicketComment(tenant_id=tenant.tenant_id, ticket_id=ticket.id, author=author, body=body, author_is_agent=is_agent, internal=internal)
    db.add(comment)
    if is_agent and not internal and ticket.first_responded_at is None:
        ticket.first_responded_at = now or _now()
        if ticket.status == "open":
            ticket.status = "in_progress"
    if not is_agent and ticket.status == "waiting_on_requester":
        _resume(db, ticket, now=now)
        ticket.status = "in_progress"
    db.commit()
    db.refresh(comment)
    return comment


def _resume(db: Session, ticket: Ticket, *, now: Optional[datetime] = None) -> None:
    """Leaving waiting_on_requester: the resolution due date moves out by the business
    minutes spent paused -- the clock only runs while it's the helpdesk's move."""
    if ticket.paused_at is None:
        return
    now = now or _now()
    calendar = db.get(BusinessCalendar, ticket.calendar_id) if ticket.calendar_id else None
    paused_minutes = _elapsed(ticket.paused_at, now, calendar)
    if ticket.resolution_due_at is not None and paused_minutes:
        ticket.resolution_due_at = _add(ticket.resolution_due_at, paused_minutes, calendar)
    ticket.paused_at = None


def change_status(db: Session, tenant: TenantContext, ticket: Ticket, status: str, *, now: Optional[datetime] = None) -> Ticket:
    now = now or _now()
    allowed = {
        "open": {"in_progress", "waiting_on_requester", "resolved", "cancelled"},
        "in_progress": {"waiting_on_requester", "resolved", "cancelled"},
        "waiting_on_requester": {"in_progress", "resolved", "cancelled"},
        "resolved": {"closed", "in_progress"},  # reopen
        "closed": set(),
        "cancelled": set(),
    }
    if status not in allowed.get(ticket.status, set()):
        raise TicketError(f"cannot move a {ticket.status} ticket to {status}")
    if ticket.status == "waiting_on_requester":
        _resume(db, ticket, now=now)
    if status == "waiting_on_requester":
        ticket.paused_at = now
    if status == "resolved":
        ticket.resolved_at = now
    if status == "in_progress" and ticket.status == "resolved":
        ticket.resolved_at = None
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    return ticket


def record_csat(db: Session, ticket: Ticket, *, score: int, comment: Optional[str] = None) -> Ticket:
    if ticket.status not in ("resolved", "closed"):
        raise TicketError("CSAT can only be given once the ticket is resolved")
    if not 1 <= score <= 5:
        raise TicketError("score is 1-5")
    ticket.csat_score = score
    ticket.csat_comment = comment
    db.commit()
    db.refresh(ticket)
    return ticket


def process_escalations(db: Session, tenant: TenantContext, *, now: Optional[datetime] = None) -> int:
    """Escalation workflow: each policy's `escalation_json` steps [{"at_pct": 80}, {"at_pct": 100}]
    raise `escalation_level` once per step and fire `helpdesk.ticket_escalated` (recipients
    come from the tenant's own notification rule). Callable from a scheduler."""
    from app.platform.comms.service import dispatch_event

    now = now or _now()
    escalated = 0
    tickets = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.status.in_(("open", "in_progress")), Ticket.sla_policy_id.isnot(None)).all()
    for ticket in tickets:
        policy = db.get(SlaPolicy, ticket.sla_policy_id)
        steps = sorted(policy.escalation_json or [], key=lambda s: s.get("at_pct", 100))
        pct = sla_status(db, ticket, now=now)["resolution_elapsed_pct"]
        reached = sum(1 for step in steps if pct >= step.get("at_pct", 100))
        if reached > ticket.escalation_level:
            ticket.escalation_level = reached
            db.commit()
            dispatch_event(db, tenant, "helpdesk.ticket_escalated", {"ticket_id": str(ticket.id), "number": ticket.number, "level": reached,
                                                                     "queue": ticket.queue_code, "elapsed_pct": pct})
            escalated += 1
    return escalated


# ---- visibility ----


def can_view(ticket: Ticket, *, user: User, employee_id: Optional[UUID], is_agent: bool, can_view_confidential: bool) -> bool:
    if ticket.requester_user_id == user.id or (employee_id and ticket.requester_employee_id == employee_id):
        return True
    if not is_agent:
        return False
    if ticket.confidential:
        return can_view_confidential or ticket.assignee_user_id == user.id
    return True


def visible_query(db: Session, tenant: TenantContext, *, user: User, can_view_confidential: bool):
    query = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id)
    if not can_view_confidential:
        query = query.filter(or_(Ticket.confidential.is_(False), Ticket.assignee_user_id == user.id))
    return query


# ---- email-to-ticket ----


def ticket_from_email(db: Session, tenant: TenantContext, inbound) -> Ticket:
    """For a message that arrived on a mailbox routed to `email.inbound.helpdesk` with no
    existing thread: the sender is matched to an employee (personal email) or user."""
    category = _setting(db, tenant, "helpdesk.email.default_category")
    if not category:
        raise TicketError("set helpdesk.email.default_category before enabling email-to-ticket")
    sender = (inbound.from_address or "").lower()
    user = db.query(User).filter(func.lower(User.email) == sender).first()
    employee = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, func.lower(Employee.personal_email) == sender).first()
    if employee is None and user is not None:
        employee = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()
    ticket = create_ticket(
        db, tenant, category_code=category, subject=inbound.subject or "(no subject)", description=inbound.body_ref, channel="email",
        requester_employee_id=employee.id if employee else None, requester_user_id=user.id if user else None, requester_email=sender,
        inbound_message_id=inbound.id,
    )
    inbound.routed_entity_type, inbound.routed_entity_id, inbound.status = "ticket", ticket.id, "routed"
    db.commit()
    return ticket


def _reply_handler(db: Session, tenant: TenantContext, message, row) -> None:
    """Replies whose thread key is "ticket-<number>" become requester comments."""
    from app.platform.comms.inbound import _NotMyThreadError

    key = row.thread_key or ""
    if not key.startswith("ticket-"):
        raise _NotMyThreadError()
    ticket = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.number == key[len("ticket-"):]).first()
    if ticket is None:
        raise _NotMyThreadError()
    add_comment(db, tenant, ticket, author=row.from_address, body=row.body_ref or "", is_agent=False)
    row.routed_entity_type, row.routed_entity_id = "ticket", ticket.id


def register_inbound() -> None:
    from app.platform.comms.inbound import register_inbound_handler

    register_inbound_handler("helpdesk.ticket_reply", _reply_handler)


# ---- knowledge base / deflection ----


def search_kb(db: Session, tenant: TenantContext, query_text: str, *, limit: int = 5) -> list[KbArticle]:
    words = [w for w in query_text.lower().split() if len(w) > 2][:8]
    if not words:
        return []
    query = db.query(KbArticle).filter(KbArticle.tenant_id == tenant.tenant_id, KbArticle.status == "published")
    articles = query.filter(or_(*[KbArticle.title.ilike(f"%{w}%") | KbArticle.body.ilike(f"%{w}%") for w in words])).all()

    def _score(a: KbArticle) -> int:
        text = f"{a.title} {a.title} {a.body}".lower()  # title counts double
        return sum(text.count(w) for w in words)

    return sorted(articles, key=_score, reverse=True)[:limit]


def record_deflection(db: Session, article: KbArticle, *, helpful: bool) -> None:
    """The requester found the answer instead of raising a ticket."""
    article.deflection_count += 1
    if helpful:
        article.helpful_count += 1
    db.commit()


def ticket_to_dict(t: Ticket, *, sla: Optional[dict] = None) -> dict:
    return {
        "id": str(t.id), "number": t.number, "category_code": t.category_code, "subcategory_code": t.subcategory_code,
        "priority": t.priority, "subject": t.subject, "description": t.description, "channel": t.channel, "status": t.status,
        "confidential": t.confidential, "queue_code": t.queue_code, "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
        "requester_employee_id": str(t.requester_employee_id) if t.requester_employee_id else None,
        "created_at": t.created_at.isoformat() if t.created_at else None, "escalation_level": t.escalation_level,
        "csat_score": t.csat_score, "sla": sla,
    }
