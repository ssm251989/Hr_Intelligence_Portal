"""Part 15 step 15.6 (L T1-T7, X1-X5): read-only helpers the new Helpdesk / Assets / Exits
pages need that the Part 11 service-desk endpoints don't return (friendly names instead of
ids, lists the original API has no GET for). No new tables, no writes -- every change still
goes through /api/v1/service-desk/*.

- GET /api/v1/ui/servicedesk/categories?kind=ticket|asset|exit_reason   friendly category names
- GET /api/v1/ui/servicedesk/tickets-meta?ids=a,b                          names + clocks for a page of tickets
- GET /api/v1/ui/servicedesk/agents                                        people a ticket can be given to + teams
- GET /api/v1/ui/servicedesk/people?q=&ids=                                employee picker / id -> name
- GET /api/v1/ui/servicedesk/assets-meta?ids=a,b                           current holder + handover state
- GET /api/v1/ui/servicedesk/catalogue                                     asset categories with in-stock counts
- GET /api/v1/ui/servicedesk/me/asset-requests                             my asset requests
- GET /api/v1/ui/servicedesk/asset-requests?status=                        requests for approvers / fulfilment
- GET /api/v1/ui/servicedesk/me/separation                                 my resignation + clearance progress
- GET /api/v1/ui/servicedesk/separations-overview?include_closed=          HR list + clearance board data
- GET /api/v1/ui/servicedesk/separations/{id}/letters                      relieving / experience letter HTML

Every query filters on the current company's tenant_id explicitly.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.core_hr import Employee, LetterRecord
from app.models.metadata import MasterValue
from app.models.service_desk import (
    Asset,
    AssetAllocation,
    AssetRequest,
    ClearanceItem,
    Separation,
    Ticket,
    TicketAssignmentRule,
    TicketQueue,
)
from app.models.user import User
from app.platform.iam.authz import effective_permissions, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/servicedesk", tags=["ui-servicedesk"])

CATEGORY_TYPES = {"ticket": "ticket_category", "asset": "asset_category", "exit_reason": "exit_reason"}
OPEN_SEPARATION = ("submitted", "retention", "approved", "clearance")


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _ids(raw: Optional[str]) -> list[UUID]:
    out: list[UUID] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(UUID(part))
        except ValueError:
            continue
    return out[:100]


def _label(value: MasterValue, locale: str) -> str:
    labels = value.label_i18n or {}
    return labels.get(locale) or labels.get("en") or next(iter(labels.values()), None) or value.code.replace("_", " ").capitalize()


def _employee_name(e: Optional[Employee]) -> Optional[str]:
    if e is None:
        return None
    first = e.preferred_name or e.first_name
    return " ".join(p for p in (first, e.last_name) if p)


def _user_name(u: Optional[User]) -> Optional[str]:
    if u is None:
        return None
    return u.full_name or u.email


def _any_of(*codes: str):
    def _dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        perms = effective_permissions(db, require_current_tenant(), current_user)
        if not any(c in perms for c in codes):
            raise HTTPException(status_code=403, detail="You don't have access to this.")
        return current_user

    return _dependency


def _my_employee(db: Session, user: User) -> Optional[Employee]:
    tenant = require_current_tenant()
    return db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.user_id == user.id).first()


# ---- shared ----


# Part 20.0-D: hrctl seed-masters never seeded these three lists, so a company had NO asset types /
# ticket topics / exit reasons and every dropdown fed by them was empty. A list that has never had a
# single value gets these defaults the first time it is read (editable in Settings > Helpdesk & assets).
DEFAULT_CATEGORIES = {
    "asset_category": (("laptop", "Laptop", "laptop"), ("desktop", "Desktop", "desktop"), ("monitor", "Monitor", "desktop"),
                       ("mobile_phone", "Mobile phone", "phone"), ("sim_card", "SIM card", "phone"), ("id_card", "ID card", "id_card"),
                       ("access_card", "Access card", "key"), ("headset", "Headset", "headphone"), ("keyboard_mouse", "Keyboard/Mouse", "keyboard"),
                       ("other", "Other", "package")),
    "exit_reason": (("better_offer", "Better offer elsewhere", None), ("personal", "Personal reasons", None), ("relocation", "Moving to another city", None),
                    ("higher_studies", "Higher studies", None), ("health", "Health", None), ("role_fit", "Role or work not a good fit", None),
                    ("manager_team", "Manager or team", None), ("pay", "Pay", None), ("performance", "Performance (company decision)", None),
                    ("other", "Other", None)),
    "ticket_category": (("it", "IT & devices", "laptop"), ("payroll", "Pay & payslips", "money"), ("leave", "Leave & attendance", "calendar"),
                        ("policy", "Policies", "page"), ("other", "Something else", "speech")),
}


def ensure_defaults(db: Session, tenant, type_code: str) -> int:
    """Seeds a list that has never had any value (active or not). Returns how many were added."""
    if db.query(MasterValue.id).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == type_code).first() is not None:
        return 0
    from app.platform.metadata.masters import register_master_types

    register_master_types(db)
    for i, (code, label, emoji) in enumerate(DEFAULT_CATEGORIES.get(type_code, ()), start=1):
        db.add(MasterValue(tenant_id=tenant.tenant_id, type_code=type_code, code=code, label_i18n={"en": label}, sort=i,
                           attributes_json={"emoji": emoji} if emoji else {}))
    db.commit()
    log_action(db, "master_list", None, "default_values_added", "system", {"type": type_code, "count": len(DEFAULT_CATEGORIES.get(type_code, ()))})
    return len(DEFAULT_CATEGORIES.get(type_code, ()))


def _category_row(v: MasterValue, locale: str) -> dict:
    return {"code": v.code, "label": _label(v, locale), "parent_code": None, "emoji": (v.attributes_json or {}).get("emoji"),
            "hint": (v.attributes_json or {}).get("hint"), "active": bool(v.is_active), "label_i18n": v.label_i18n or {}}


@router.get("/categories")
def categories(kind: str = "ticket", locale: str = "en", include_inactive: bool = False, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    type_code = CATEGORY_TYPES.get(kind)
    if type_code is None:
        raise HTTPException(status_code=400, detail="kind is ticket, asset or exit_reason")
    tenant = require_current_tenant()
    ensure_defaults(db, tenant, type_code)
    query = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == type_code)
    if not include_inactive:
        query = query.filter(MasterValue.is_active.is_(True))
    return [_category_row(v, locale) for v in query.order_by(MasterValue.sort, MasterValue.code).all()]


class CategoryIn(BaseModel):
    kind: str
    label: str = Field(..., min_length=1, max_length=80)


def _can_edit_categories(db: Session, user: User, kind: str) -> None:
    from app.platform.iam.authz import has_permission

    tenant = require_current_tenant()
    needed = {"asset": ("assets.asset.edit", "assets.asset.create"), "exit_reason": ("separation.case.edit",), "ticket": ("helpdesk.ticket.edit",)}
    if not any(has_permission(db, tenant, user, p) for p in (*needed.get(kind, ()), "platform.settings.configure")):
        raise HTTPException(status_code=403, detail="You don't have permission to change this list.")


@router.post("/categories", status_code=201)
def add_category(body: CategoryIn, locale: str = "en", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Part 20.0-D: "Add asset type" right inside the dropdown (and the Settings list)."""
    import re as _re

    type_code = CATEGORY_TYPES.get(body.kind)
    if type_code is None:
        raise HTTPException(status_code=400, detail="kind is ticket, asset or exit_reason")
    _can_edit_categories(db, current_user, body.kind)
    tenant = require_current_tenant()
    ensure_defaults(db, tenant, type_code)
    label = body.label.strip()
    rows = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == type_code).all()
    same = next((v for v in rows if (_label(v, "en") or "").strip().lower() == label.lower()), None)
    if same is not None:
        if not same.is_active:
            same.is_active = True
            db.commit()
        return _category_row(same, locale)
    base = _re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "type"
    code, n = base, 2
    while any(v.code == code for v in rows):
        code, n = f"{base}_{n}", n + 1
    value = MasterValue(tenant_id=tenant.tenant_id, type_code=type_code, code=code, label_i18n={"en": label}, sort=len(rows) + 1, attributes_json={})
    db.add(value)
    db.commit()
    log_action(db, "master_list", value.id, "list_value_added", current_user.email, {"type": type_code, "label": label})
    return _category_row(value, locale)


class CategoryPatch(BaseModel):
    label: Optional[str] = Field(None, max_length=80)
    active: Optional[bool] = None


@router.patch("/categories/{kind}/{code}")
def edit_category(kind: str, code: str, body: CategoryPatch, locale: str = "en", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Rename or switch off (never delete: assets / exits / tickets keep pointing at the code)."""
    type_code = CATEGORY_TYPES.get(kind)
    if type_code is None:
        raise HTTPException(status_code=400, detail="kind is ticket, asset or exit_reason")
    _can_edit_categories(db, current_user, kind)
    tenant = require_current_tenant()
    value = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == type_code, MasterValue.code == code).first()
    if value is None:
        raise HTTPException(status_code=404, detail="That item isn't on the list.")
    if body.label is not None and body.label.strip():
        value.label_i18n = {**(value.label_i18n or {}), locale if locale in ("en", "hi", "ta") else "en": body.label.strip()}
    if body.active is not None:
        value.is_active = body.active
    db.commit()
    log_action(db, "master_list", value.id, "list_value_changed", current_user.email, {"type": type_code, "code": code, "active": value.is_active})
    return _category_row(value, locale)


@router.get("/people")
def people(q: Optional[str] = None, ids: Optional[str] = None, db: Session = Depends(get_db),
           current_user: User = Depends(_any_of("assets.asset.view", "assets.asset.edit", "separation.case.view", "helpdesk.ticket.view"))):
    tenant = require_current_tenant()
    query = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id)
    wanted = _ids(ids)
    if wanted:
        query = query.filter(Employee.id.in_(wanted))
    elif q:
        like = f"%{q.strip()}%"
        query = query.filter((Employee.first_name.ilike(like)) | (Employee.last_name.ilike(like)) | (Employee.employee_code.ilike(like))
                             | (Employee.preferred_name.ilike(like)))
        query = query.filter(Employee.status.in_(("active", "on_notice", "probation")))
    else:
        query = query.filter(Employee.status.in_(("active", "on_notice", "probation")))
    rows = query.order_by(Employee.first_name).limit(100 if wanted else 20).all()
    return [{"id": str(e.id), "name": _employee_name(e), "code": e.employee_code, "status": e.status} for e in rows]


# ---- helpdesk ----


@router.get("/tickets-meta")
def tickets_meta(ids: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.self.view"))):
    """Names and clocks for tickets the caller can already see (requester or agent)."""
    tenant = require_current_tenant()
    wanted = _ids(ids)
    if not wanted:
        return {}
    perms = effective_permissions(db, tenant, current_user)
    me = _my_employee(db, current_user)
    rows = db.query(Ticket).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.id.in_(wanted)).all()
    queues = {q.code: q.name for q in db.query(TicketQueue).filter(TicketQueue.tenant_id == tenant.tenant_id).all()}
    out: dict[str, dict] = {}
    for t in rows:
        mine = t.requester_user_id == current_user.id or (me is not None and t.requester_employee_id == me.id)
        agent = "helpdesk.ticket.view" in perms and (not t.confidential or "helpdesk.ticket.view_sensitive" in perms or t.assignee_user_id == current_user.id)
        if not (mine or agent):
            continue
        requester = db.get(Employee, t.requester_employee_id) if t.requester_employee_id else None
        assignee = db.get(User, t.assignee_user_id) if t.assignee_user_id else None
        out[str(t.id)] = {
            "first_responded_at": _iso(t.first_responded_at), "resolved_at": _iso(t.resolved_at), "paused_at": _iso(t.paused_at),
            "response_due_at": _iso(t.response_due_at), "resolution_due_at": _iso(t.resolution_due_at),
            "escalation_level": t.escalation_level, "csat_score": t.csat_score,
            "requester_name": _employee_name(requester) or (t.requester_email if agent else None),
            "assignee_name": _user_name(assignee), "team_name": queues.get(t.queue_code) if t.queue_code else None,
            "created_at": _iso(t.created_at),
        }
    return out


@router.get("/agents")
def agents(db: Session = Depends(get_db), current_user: User = Depends(require("helpdesk.ticket.view"))):
    """Agents named in assignment rules, team leads and current assignees, plus the teams."""
    tenant = require_current_tenant()
    ids: set[str] = {str(current_user.id)}
    for rule in db.query(TicketAssignmentRule).filter(TicketAssignmentRule.tenant_id == tenant.tenant_id).all():
        for a in rule.agents_json or []:
            if isinstance(a, dict) and a.get("user_id"):
                ids.add(str(a["user_id"]))
    queues = db.query(TicketQueue).filter(TicketQueue.tenant_id == tenant.tenant_id).order_by(TicketQueue.name).all()
    ids.update(str(q.lead_user_id) for q in queues if q.lead_user_id)
    for (uid,) in db.query(Ticket.assignee_user_id).filter(Ticket.tenant_id == tenant.tenant_id, Ticket.assignee_user_id.isnot(None)).distinct().limit(200).all():
        ids.add(str(uid))
    users = db.query(User).filter(User.id.in_([UUID(i) for i in ids])).all()
    return {
        "agents": sorted(({"id": str(u.id), "name": _user_name(u), "me": u.id == current_user.id} for u in users), key=lambda a: (not a["me"], a["name"] or "")),
        "teams": [{"code": q.code, "name": q.name} for q in queues if not q.confidential or q.lead_user_id == current_user.id],
    }


# ---- assets ----


@router.get("/assets-meta")
def assets_meta(ids: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("assets.asset.view"))):
    tenant = require_current_tenant()
    wanted = _ids(ids)
    if not wanted:
        return {}
    out: dict[str, dict] = {}
    rows = (
        db.query(AssetAllocation)
        .filter(AssetAllocation.tenant_id == tenant.tenant_id, AssetAllocation.asset_id.in_(wanted), AssetAllocation.returned_at.is_(None))
        .all()
    )
    for a in rows:
        employee = db.get(Employee, a.employee_id)
        out[str(a.asset_id)] = {"allocation_id": str(a.id), "employee_id": str(a.employee_id), "employee_name": _employee_name(employee),
                                "allocated_at": _iso(a.allocated_at), "acknowledged_at": _iso(a.acknowledged_at)}
    return out


@router.get("/catalogue")
def catalogue(locale: str = "en", db: Session = Depends(get_db), current_user: User = Depends(require("assets.self.view"))):
    tenant = require_current_tenant()
    cats = (
        db.query(MasterValue)
        .filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "asset_category", MasterValue.is_active.is_(True))
        .order_by(MasterValue.sort, MasterValue.code)
        .all()
    )
    out = []
    for c in cats:
        in_stock = db.query(Asset).filter(Asset.tenant_id == tenant.tenant_id, Asset.category_code == c.code, Asset.status == "in_stock").count()
        attrs = c.attributes_json or {}
        out.append({"code": c.code, "label": _label(c, locale), "in_stock": in_stock, "emoji": attrs.get("emoji"), "hint": attrs.get("hint")})
    return out


def _request_row(db: Session, r: AssetRequest, *, with_name: bool) -> dict:
    row = {"id": str(r.id), "category_code": r.category_code, "reason": r.reason, "status": r.status, "source": r.source,
           "created_at": _iso(r.created_at), "employee_id": str(r.employee_id)}
    if r.fulfilled_allocation_id:
        allocation = db.get(AssetAllocation, r.fulfilled_allocation_id)
        asset = db.get(Asset, allocation.asset_id) if allocation else None
        row["fulfilled_asset"] = {"name": asset.name, "asset_tag": asset.asset_tag} if asset else None
    if with_name:
        row["employee_name"] = _employee_name(db.get(Employee, r.employee_id))
    return row


@router.get("/me/asset-requests")
def my_asset_requests(db: Session = Depends(get_db), current_user: User = Depends(require("assets.self.view"))):
    tenant = require_current_tenant()
    me = _my_employee(db, current_user)
    if me is None:
        return []
    rows = db.query(AssetRequest).filter(AssetRequest.tenant_id == tenant.tenant_id, AssetRequest.employee_id == me.id).order_by(AssetRequest.created_at.desc()).limit(50).all()
    return [_request_row(db, r, with_name=False) for r in rows]


@router.get("/asset-requests")
def asset_requests(status: Optional[str] = None, db: Session = Depends(get_db),
                   current_user: User = Depends(_any_of("assets.asset.approve", "assets.asset.edit"))):
    tenant = require_current_tenant()
    query = db.query(AssetRequest).filter(AssetRequest.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(AssetRequest.status.in_([s for s in status.split(",") if s]))
    rows = query.order_by(AssetRequest.created_at.desc()).limit(100).all()
    return [_request_row(db, r, with_name=True) for r in rows]


# ---- exits ----


def _letters(db: Session, s: Separation) -> dict:
    def one(letter_id):
        if not letter_id:
            return None
        rec = db.get(LetterRecord, letter_id)
        return {"id": str(rec.id), "generated_at": _iso(rec.generated_at)} if rec else None

    return {"relieving": one(s.relieving_letter_id), "experience": one(s.experience_letter_id)}


def _items(db: Session, s: Separation) -> list[dict]:
    rows = db.query(ClearanceItem).filter(ClearanceItem.tenant_id == s.tenant_id, ClearanceItem.separation_id == s.id).all()
    owners = {u.id: u for u in db.query(User).filter(User.id.in_([r.owner_user_id for r in rows if r.owner_user_id])).all()} if rows else {}
    return [{"id": str(r.id), "department": r.department, "kind": r.kind, "title": r.title, "status": r.status, "blocks_relieving": r.blocks_relieving,
             "owner_name": _user_name(owners.get(r.owner_user_id)) if r.owner_user_id else None, "cleared_by": r.cleared_by,
             "cleared_at": _iso(r.cleared_at), "notes": r.notes, "amount_due": float(r.amount_due) if r.amount_due is not None else None,
             "asset_allocation_id": str(r.asset_allocation_id) if r.asset_allocation_id else None} for r in rows]


def _separation_row(db: Session, s: Separation, *, with_items: bool, interview: bool = False) -> dict:
    """`interview`: include the exit interview answers / AI summary -- only for separation_hr.exit_interview.view
    (fix 2026-10-06: managers and the employee's own page never get them here)."""
    from app.employees.exit_interview import status_of
    employee = db.get(Employee, s.employee_id)
    items = _items(db, s)
    row = {
        "id": str(s.id), "employee_id": str(s.employee_id), "employee_name": _employee_name(employee), "employee_code": employee.employee_code if employee else None,
        "type": s.separation_type, "status": s.status, "submitted_on": _iso(s.submitted_on), "requested_lwd": _iso(s.requested_lwd),
        "approved_lwd": _iso(s.approved_lwd), "notice_period_days": s.notice_period_days, "reason_code": s.reason_code, "reason_text": s.reason_text,
        "items_total": len(items), "items_pending": sum(1 for i in items if i.get("status") == "pending"),
        "blocking_pending": sum(1 for i in items if i.get("status") == "pending" and i.get("blocks_relieving")),
        "exit_interview_done": bool((s.exit_interview_json or {}).get("submitted_at")),
        "exit_interview_status": status_of(s),
        **({"exit_interview": s.exit_interview_json, "exit_interview_ai_summary": s.exit_interview_ai_summary_json} if interview else {}),
        "letters": _letters(db, s), "rehire_eligible": s.rehire_eligible,
    }
    if with_items:
        row["items"] = items
    return row


@router.get("/me/separation")
def my_separation(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    me = _my_employee(db, current_user)
    if me is None:
        return {"linked": False, "separation": None, "notice_period_days": None}
    from app.service_desk.separations import notice_period_days

    try:
        notice = notice_period_days(db, tenant, me)
    except Exception:  # settings not seeded yet -- the form just doesn't show the estimate
        notice = None
    s = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == me.id).order_by(Separation.created_at.desc()).first()
    row = _separation_row(db, s, with_items=True) if s is not None else None
    if row:
        # an employee sees progress, not HR's notes or the AI summary
        row.pop("exit_interview_ai_summary", None)
        row.pop("exit_interview", None)
        for item in row.get("items", []):
            item.pop("notes", None)
    return {"linked": True, "employee_status": me.status, "separation": row, "notice_period_days": notice}


@router.get("/separations-overview")
def separations_overview(include_closed: bool = False, db: Session = Depends(get_db), current_user: User = Depends(require("separation.case.view"))):
    tenant = require_current_tenant()
    query = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id)
    if not include_closed:
        query = query.filter(Separation.status.in_(OPEN_SEPARATION))
    rows = query.order_by(Separation.created_at.desc()).limit(200).all()
    from app.platform.iam.authz import has_permission

    hr = has_permission(db, tenant, current_user, "separation_hr.exit_interview.view")
    return {"today": datetime.now(timezone.utc).date().isoformat(), "items": [_separation_row(db, s, with_items=True, interview=hr) for s in rows]}


@router.get("/separations/{separation_id}/letters")
def separation_letters(separation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    s = db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.id == separation_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Exit not found")
    me = _my_employee(db, current_user)
    own = me is not None and s.employee_id == me.id
    if not own and "separation.case.view" not in effective_permissions(db, tenant, current_user):
        raise HTTPException(status_code=404, detail="Exit not found")

    def one(letter_id):
        if not letter_id:
            return None
        rec = db.query(LetterRecord).filter(LetterRecord.tenant_id == tenant.tenant_id, LetterRecord.id == letter_id).first()
        return {"id": str(rec.id), "generated_at": _iso(rec.generated_at), "html": rec.rendered_html} if rec else None

    return {"relieving": one(s.relieving_letter_id), "experience": one(s.experience_letter_id)}
