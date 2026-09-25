"""Separation / offboarding (docs/HRMS_COMPLETE_SPEC.txt Part 11 section C).

Flow: resignation (employee) | termination / absconding (HR) -> optional retention step ->
LWD approval (notice from employment record / `notice_period` master / setting, shortfall
covered by waiver or buyout per policy) -> clearance checklist per department (+ one
asset-recovery item per allocated asset, + access revocation as a manual item at launch,
+ knowledge-transfer tasks) -> exit interview (+ optional AI summary, HITL) -> relieving /
experience letters (BLOCKED until every blocking clearance item is cleared or waived) ->
completion (employee inactive, employment record closed at LWD, rehire flag, alumni).

Approvals run through Part 5 workflows when the tenant has published `separation_<type>`;
otherwise the HR endpoints drive each step directly.
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core_hr import lifecycle
from app.models.core_hr import Employee
from app.models.metadata import MasterValue
from app.models.service_desk import Asset, AssetAllocation, ClearanceItem, Separation, CLEARANCE_DEPARTMENTS, CLEARANCE_KINDS
from app.models.workflow import WorkflowDefinition
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

OPEN_STATUSES = ("submitted", "retention", "approved", "clearance")


class SeparationError(ValueError):
    pass


class ClearanceBlockedError(SeparationError):
    """Relieving letter requested while blocking clearance items are still pending."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant: TenantContext, key: str):
    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---- notice period ----


def notice_period_days(db: Session, tenant: TenantContext, employee: Employee) -> int:
    """employment record's own notice_period_days -> a `notice_period` master value whose
    attributes {"grades": [...], "days": N} match the grade -> `separation.default_notice_days`."""
    employment = lifecycle.get_current_employment(db, tenant, employee.id)
    if employment and employment.notice_period_days:
        return int(employment.notice_period_days)
    if employment and employment.grade:
        values = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "notice_period", MasterValue.is_active.is_(True)).all()
        for value in values:
            attrs = value.attributes_json or {}
            if employment.grade in (attrs.get("grades") or []) and attrs.get("days") is not None:
                return int(attrs["days"])
    return int(_setting(db, tenant, "separation.default_notice_days"))


def standard_lwd(separation: Separation) -> date:
    return separation.submitted_on + timedelta(days=separation.notice_period_days)


# ---- initiation ----


def _open_for(db: Session, tenant: TenantContext, employee_id: UUID) -> Optional[Separation]:
    return db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.employee_id == employee_id, Separation.status.in_(OPEN_STATUSES)).first()


def _start_workflow(db: Session, tenant: TenantContext, separation: Separation, *, actor: str, actor_user_id: Optional[UUID]) -> None:
    definition = (
        db.query(WorkflowDefinition)
        .filter(WorkflowDefinition.tenant_id == tenant.tenant_id, WorkflowDefinition.key == f"separation_{separation.separation_type}", WorkflowDefinition.status == "published")
        .order_by(WorkflowDefinition.version.desc())
        .first()
    )
    if definition is None:
        return
    from app.platform.workflow.engine import start_instance

    instance = start_instance(
        db, tenant, definition, entity_type="separation", entity_id=separation.id,
        context={"employee_id": str(separation.employee_id), "type": separation.separation_type, "requested_lwd": separation.requested_lwd.isoformat() if separation.requested_lwd else None},
        started_by=actor, started_by_user_id=actor_user_id,
    )
    separation.workflow_instance_id = instance.id
    db.commit()


def initiate(
    db: Session, tenant: TenantContext, *, employee_id: UUID, separation_type: str, actor: str, submitted_on: Optional[date] = None,
    requested_lwd: Optional[date] = None, reason_code: Optional[str] = None, reason_text: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
) -> Separation:
    employee = db.get(Employee, employee_id)
    if employee is None or employee.tenant_id != tenant.tenant_id:
        raise SeparationError("employee not found")
    if employee.status not in ("active", "on_notice"):
        raise SeparationError(f"employee is {employee.status}")
    if _open_for(db, tenant, employee_id) is not None:
        raise SeparationError("this employee already has an open separation")
    submitted_on = submitted_on or _now().date()
    if requested_lwd is not None and requested_lwd < submitted_on:
        raise SeparationError("last working day cannot be before the submission date")
    separation = Separation(
        tenant_id=tenant.tenant_id, employee_id=employee_id, separation_type=separation_type, initiated_by=actor,
        reason_code=reason_code, reason_text=reason_text, voluntary=separation_type in ("resignation", "retirement"),
        submitted_on=submitted_on, notice_period_days=notice_period_days(db, tenant, employee), requested_lwd=requested_lwd,
    )
    if separation_type == "resignation" and _setting(db, tenant, "separation.retention_step_enabled"):
        separation.status = "retention"
    db.add(separation)
    employee.status = "on_notice"
    db.commit()
    db.refresh(separation)
    _start_workflow(db, tenant, separation, actor=actor, actor_user_id=actor_user_id)
    return separation


def record_retention(db: Session, separation: Separation, *, notes: str, retained: bool, actor: str) -> Separation:
    if separation.status != "retention":
        raise SeparationError("no retention discussion pending")
    separation.retention_notes = notes
    if retained:
        return withdraw(db, separation, actor=actor)
    separation.status = "submitted"
    db.commit()
    db.refresh(separation)
    return separation


def withdraw(db: Session, separation: Separation, *, actor: str) -> Separation:
    if separation.status not in ("submitted", "retention", "approved"):
        raise SeparationError(f"a {separation.status} separation cannot be withdrawn")
    separation.status = "withdrawn"
    employee = db.get(Employee, separation.employee_id)
    if employee.status == "on_notice":
        employee.status = "active"
    for item in _items(db, separation):
        if item.status == "pending":
            item.status = "waived"
            item.notes = f"withdrawn by {actor}"
    db.commit()
    db.refresh(separation)
    return separation


# ---- LWD approval ----


def approve_lwd(db: Session, tenant: TenantContext, separation: Separation, *, lwd: date, actor: str, waived_days: int = 0, buyout_days: int = 0) -> Separation:
    if separation.status not in ("submitted", "approved"):
        raise SeparationError(f"cannot approve the LWD of a {separation.status} separation")
    if lwd < separation.submitted_on:
        raise SeparationError("last working day cannot be before the submission date")
    if waived_days < 0 or buyout_days < 0:
        raise SeparationError("waiver/buyout days cannot be negative")
    shortfall = max(0, (standard_lwd(separation) - lwd).days)
    if shortfall and _setting(db, tenant, "separation.require_shortfall_cover") and waived_days + buyout_days < shortfall:
        raise SeparationError(f"LWD is {shortfall} days short of notice; waive or buy out at least that many days")
    separation.approved_lwd = lwd
    separation.notice_waived_days = waived_days
    separation.notice_buyout_days = buyout_days
    separation.status = "approved"
    db.commit()
    generate_clearance(db, tenant, separation)
    db.refresh(separation)
    return separation


# ---- clearance ----


def _items(db: Session, separation: Separation) -> list[ClearanceItem]:
    return db.query(ClearanceItem).filter(ClearanceItem.tenant_id == separation.tenant_id, ClearanceItem.separation_id == separation.id).all()


def _asset_clearance_department(db: Session, tenant: TenantContext, asset: Asset) -> str:
    category = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "asset_category", MasterValue.code == asset.category_code).first()
    department = ((category.attributes_json or {}).get("clearance_department") if category else None) or "admin"
    return department if department in CLEARANCE_DEPARTMENTS else "admin"


def generate_clearance(db: Session, tenant: TenantContext, separation: Separation) -> list[ClearanceItem]:
    """Idempotent: checklist items from `separation.clearance_checklist` + one asset-recovery
    item per unreturned allocation. Re-running only adds what's missing."""
    existing = _items(db, separation)
    existing_titles = {(i.department, i.title) for i in existing}
    existing_allocations = {i.asset_allocation_id for i in existing if i.asset_allocation_id}
    for entry in _setting(db, tenant, "separation.clearance_checklist") or []:
        department, title = entry.get("department"), entry.get("title")
        kind = entry.get("kind", "clearance")
        if department not in CLEARANCE_DEPARTMENTS or kind not in CLEARANCE_KINDS or not title:
            continue
        if (department, title) not in existing_titles:
            db.add(ClearanceItem(tenant_id=tenant.tenant_id, separation_id=separation.id, department=department, kind=kind, title=title,
                                 blocks_relieving=bool(entry.get("blocks_relieving", True))))
    allocations = db.query(AssetAllocation).filter(AssetAllocation.tenant_id == tenant.tenant_id, AssetAllocation.employee_id == separation.employee_id, AssetAllocation.returned_at.is_(None)).all()
    for allocation in allocations:
        if allocation.id in existing_allocations:
            continue
        asset = db.get(Asset, allocation.asset_id)
        db.add(ClearanceItem(tenant_id=tenant.tenant_id, separation_id=separation.id, department=_asset_clearance_department(db, tenant, asset), kind="asset_recovery",
                             title=f"Recover {asset.name} ({asset.asset_tag})", asset_allocation_id=allocation.id, blocks_relieving=True))
    if separation.status == "approved":
        separation.status = "clearance"
    db.commit()
    return _items(db, separation)


def add_kt_task(db: Session, tenant: TenantContext, separation: Separation, *, title: str, owner_user_id: Optional[UUID] = None, blocks_relieving: bool = False) -> ClearanceItem:
    item = ClearanceItem(tenant_id=tenant.tenant_id, separation_id=separation.id, department="manager", kind="knowledge_transfer", title=title,
                         owner_user_id=owner_user_id, blocks_relieving=blocks_relieving)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def clear_item(db: Session, item: ClearanceItem, *, actor: str, waive: bool = False, notes: Optional[str] = None, amount_due=None) -> ClearanceItem:
    if item.status != "pending":
        return item
    if item.kind == "asset_recovery" and not waive:
        allocation = db.get(AssetAllocation, item.asset_allocation_id) if item.asset_allocation_id else None
        if allocation is not None and allocation.returned_at is None:
            raise SeparationError("record the asset return first (or waive the item with a reason)")
    if waive and not notes:
        raise SeparationError("waiving a clearance item needs a reason")
    item.status = "waived" if waive else "cleared"
    item.cleared_by = actor
    item.cleared_at = _now()
    item.notes = notes
    if amount_due is not None:
        item.amount_due = amount_due
    db.commit()
    db.refresh(item)
    return item


def on_asset_returned(db: Session, tenant: TenantContext, allocation: AssetAllocation, *, actor: str) -> None:
    for item in db.query(ClearanceItem).filter(ClearanceItem.tenant_id == tenant.tenant_id, ClearanceItem.asset_allocation_id == allocation.id, ClearanceItem.status == "pending").all():
        item.status = "cleared"
        item.cleared_by = actor
        item.cleared_at = _now()
        item.notes = f"returned ({allocation.return_condition})"
    db.commit()


def relieving_blockers(db: Session, separation: Separation) -> list[str]:
    blockers = [f"{i.department}: {i.title}" for i in _items(db, separation) if i.blocks_relieving and i.status == "pending"]
    if separation.approved_lwd is None:
        blockers.insert(0, "last working day not approved")
    return blockers


# ---- exit interview ----


def submit_exit_interview(db: Session, separation: Separation, *, answers: dict) -> Separation:
    separation.exit_interview_json = {"answers": answers, "submitted_at": _now().isoformat()}
    db.commit()
    db.refresh(separation)
    return separation


def summarize_exit_interview(db: Session, tenant: TenantContext, separation: Separation) -> Separation:
    """Advisory themes for HR (`llm.judgment`), stored separately from the answers."""
    from app.platform.ai import gateway

    if not separation.exit_interview_json:
        raise SeparationError("no exit interview recorded")
    answers = separation.exit_interview_json.get("answers", {})
    system = "Summarise this exit interview for HR in at most 5 neutral bullet points: main reasons for leaving, what could have retained the person, suggestions. Do not speculate beyond the answers."
    try:
        summary = gateway.complete_text(db, tenant, purpose="llm.judgment", system=system,
                                        messages=[{"role": "user", "content": "\n".join(f"{k}: {v}" for k, v in answers.items())}])
        separation.exit_interview_ai_summary_json = {"summary": summary, "source": "ai", "reviewed": False}
    except Exception as exc:
        separation.exit_interview_ai_summary_json = {"error": type(exc).__name__}
    db.commit()
    db.refresh(separation)
    return separation


# ---- absconding ----


def issue_absconding_notice(db: Session, tenant: TenantContext, separation: Separation, *, template_key: str, actor: str, context: Optional[dict] = None) -> dict:
    if separation.separation_type != "absconding":
        raise SeparationError("absconding notices apply only to absconding cases")
    from app.core_hr import letters

    letter = letters.generate_letter(db, tenant, employee_id=separation.employee_id, template_key=template_key,
                                     context={"notice_number": len(separation.absconding_notices_json or []) + 1, **(context or {})}, generated_by=actor)
    notice = {"letter_id": str(letter.id), "template_key": template_key, "issued_at": _now().isoformat(), "issued_by": actor}
    separation.absconding_notices_json = [*(separation.absconding_notices_json or []), notice]
    db.commit()
    return notice


# ---- letters + completion ----


def issue_relieving_letter(db: Session, tenant: TenantContext, separation: Separation, *, actor: str, template_key: Optional[str] = None,
                           experience_template_key: Optional[str] = None) -> dict:
    blockers = relieving_blockers(db, separation)
    if blockers:
        raise ClearanceBlockedError("relieving letter blocked: " + "; ".join(blockers))
    from app.core_hr import letters

    key = template_key or _setting(db, tenant, "separation.relieving_letter_template")
    if not key:
        raise SeparationError("no relieving letter template configured (separation.relieving_letter_template)")
    context = {"last_working_day": separation.approved_lwd.isoformat(), "separation_type": separation.separation_type}
    if separation.relieving_letter_id is None:
        separation.relieving_letter_id = letters.generate_letter(db, tenant, employee_id=separation.employee_id, template_key=key, context=context, generated_by=actor).id
    experience_key = experience_template_key or _setting(db, tenant, "separation.experience_letter_template")
    if experience_key and separation.experience_letter_id is None:
        separation.experience_letter_id = letters.generate_letter(db, tenant, employee_id=separation.employee_id, template_key=experience_key, context=context, generated_by=actor).id
    db.commit()
    return {"relieving_letter_id": str(separation.relieving_letter_id), "experience_letter_id": str(separation.experience_letter_id) if separation.experience_letter_id else None}


def complete(db: Session, tenant: TenantContext, separation: Separation, *, actor: str, rehire_eligible: bool, alumni_opt_in: bool = False,
             regretted: Optional[bool] = None, as_of: Optional[date] = None) -> Separation:
    if separation.status == "completed":
        return separation
    if separation.status != "clearance":
        raise SeparationError("complete clearance before closing the separation")
    blockers = relieving_blockers(db, separation)
    if blockers:
        raise ClearanceBlockedError("cannot complete: " + "; ".join(blockers))
    today = as_of or _now().date()
    if separation.approved_lwd > today:
        raise SeparationError(f"last working day {separation.approved_lwd.isoformat()} has not passed")
    employee = db.get(Employee, separation.employee_id)
    employee.status = "rehire_eligible" if rehire_eligible else "inactive"
    current = lifecycle.get_current_employment(db, tenant, employee.id, as_of=separation.approved_lwd)
    if current is not None and (current.effective_to is None or current.effective_to > separation.approved_lwd):
        current.effective_to = separation.approved_lwd
    separation.rehire_eligible = rehire_eligible
    separation.alumni_opt_in = alumni_opt_in
    separation.regretted = regretted
    separation.status = "completed"
    separation.completed_at = _now()
    db.commit()
    db.refresh(separation)
    from app.platform.comms.service import dispatch_event

    dispatch_event(db, tenant, "separation.completed", {"separation_id": str(separation.id), "employee_id": str(employee.id),
                                                        "last_working_day": separation.approved_lwd.isoformat()})
    return separation


# ---- exit summary ----


def exit_summary(db: Session, separation: Separation) -> dict:
    items = _items(db, separation)
    served = (separation.approved_lwd - separation.submitted_on).days if separation.approved_lwd else None
    return {
        "separation_id": str(separation.id), "employee_id": str(separation.employee_id), "type": separation.separation_type,
        "status": separation.status, "submitted_on": separation.submitted_on.isoformat(),
        "last_working_day": separation.approved_lwd.isoformat() if separation.approved_lwd else None,
        "notice_period_days": separation.notice_period_days, "notice_served_days": served,
        "notice_short_days": max(0, separation.notice_period_days - served) if served is not None else None,
        "notice_waived_days": separation.notice_waived_days, "notice_buyout_days": separation.notice_buyout_days,
        "assets_pending": sum(1 for i in items if i.kind == "asset_recovery" and i.status == "pending"),
        "clearance_pending": sum(1 for i in items if i.status == "pending"),
        "amount_due": float(sum((i.amount_due or 0) for i in items)),
        "rehire_eligible": separation.rehire_eligible, "reason_code": separation.reason_code,
    }


def export_csv(db: Session, separations: list[Separation]) -> str:
    """For the client's finance/payroll team -- payroll itself is out of scope."""
    rows = [exit_summary(db, s) for s in separations]
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return out.getvalue()


def item_to_dict(i: ClearanceItem) -> dict:
    return {"id": str(i.id), "department": i.department, "kind": i.kind, "title": i.title, "status": i.status, "blocks_relieving": i.blocks_relieving,
            "asset_allocation_id": str(i.asset_allocation_id) if i.asset_allocation_id else None, "cleared_by": i.cleared_by, "notes": i.notes,
            "amount_due": float(i.amount_due) if i.amount_due is not None else None}
