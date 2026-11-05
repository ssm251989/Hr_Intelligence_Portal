"""Semantic layer (docs/HRMS_COMPLETE_SPEC.txt Part 12 section A.1): curated datasets per
module, each a set of named fields over one SQL FROM clause, with:
- a permission the caller must hold (`permission`);
- the employee column rows are ABOUT (`employee_column`) -- the caller's data scope from
  `org_scope.employee_ids_in_scope()` is applied to it automatically (a manager with
  `reportees_direct` sees only their reportees' rows);
- a field-security entity (`field_security_entity`) -- hidden/masked fields are refused in
  filters/grouping and masked in row output;
- custom fields (`cf_<key>`) for entities that carry `custom_fields` JSONB;
- as-of-date support where the data is effective-dated (employment records).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.core_hr import Employee, EmploymentRecord
from app.models.job_role import JobRole
from app.models.onboarding import PreboardingCase
from app.models.performance import Goal, Review
from app.models.service_desk import Asset, AssetAllocation, Separation, Ticket
from app.platform.tenancy.context import TenantContext


@dataclass
class FieldDef:
    key: str
    label: str
    type: str  # str | num | date | bool | id
    expr: object  # SQLAlchemy column expression


@dataclass
class BuiltDataset:
    from_clause: object
    fields: dict[str, FieldDef]
    employee_column: Optional[object]
    base_filters: list = field(default_factory=list)


@dataclass
class DatasetDef:
    code: str
    label: str
    module: str
    permission: str
    build: Callable[[Session, TenantContext, date], BuiltDataset]
    field_security_entity: Optional[str] = None
    custom_field_entity: Optional[str] = None
    as_of_supported: bool = False


def _month(col):
    return cast(func.date_trunc("month", col), Date)


def _fields(*defs: FieldDef) -> dict[str, FieldDef]:
    return {d.key: d for d in defs}


def _custom_fields(db: Session, tenant: TenantContext, entity: str, column) -> list[FieldDef]:
    from app.platform.metadata.custom_fields import active_defs

    return [FieldDef(f"cf_{d.code}", (d.label_i18n or {}).get("en", d.code), "str", column[d.code].astext) for d in active_defs(db, tenant, entity)]


# ---- builders ----


def _headcount(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    er = EmploymentRecord
    join = Employee.__table__.outerjoin(
        er.__table__,
        and_(er.employee_id == Employee.id, er.tenant_id == Employee.tenant_id, er.effective_from <= as_of,
             or_(er.effective_to.is_(None), er.effective_to >= as_of)),
    )
    fields = _fields(
        FieldDef("employee_id", "Employee", "id", Employee.id), FieldDef("employee_code", "Employee code", "str", Employee.employee_code),
        FieldDef("first_name", "First name", "str", Employee.first_name), FieldDef("last_name", "Last name", "str", Employee.last_name),
        FieldDef("status", "Status", "str", Employee.status), FieldDef("worker_type", "Worker type", "str", Employee.worker_type),
        FieldDef("gender", "Gender", "str", Employee.gender),
        FieldDef("legal_entity_id", "Legal entity", "id", er.legal_entity_id), FieldDef("business_unit_id", "Business unit", "id", er.business_unit_id),
        FieldDef("department_id", "Department", "id", er.department_id), FieldDef("location_id", "Location", "id", er.location_id),
        FieldDef("grade", "Grade", "str", er.grade), FieldDef("designation", "Designation", "str", er.designation),
        FieldDef("employment_type", "Employment type", "str", er.employment_type), FieldDef("work_mode", "Work mode", "str", er.work_mode),
        FieldDef("manager_employee_id", "Manager", "id", er.manager_employee_id),
        FieldDef("record_since", "In current role since", "date", er.effective_from),
    )
    for f in _custom_fields(db, tenant, "employee", Employee.custom_fields):
        fields[f.key] = f
    return BuiltDataset(join, fields, Employee.id, [Employee.tenant_id == tenant.tenant_id])


def _exits(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    s = Separation
    return BuiltDataset(s.__table__, _fields(
        FieldDef("separation_id", "Separation", "id", s.id), FieldDef("employee_id", "Employee", "id", s.employee_id),
        FieldDef("type", "Type", "str", s.separation_type), FieldDef("status", "Status", "str", s.status),
        FieldDef("voluntary", "Voluntary", "bool", s.voluntary), FieldDef("regretted", "Regretted", "bool", s.regretted),
        FieldDef("reason_code", "Reason", "str", s.reason_code), FieldDef("submitted_on", "Submitted on", "date", s.submitted_on),
        FieldDef("last_working_day", "Last working day", "date", s.approved_lwd), FieldDef("exit_month", "Exit month", "date", _month(s.approved_lwd)),
        FieldDef("notice_period_days", "Notice period (days)", "num", s.notice_period_days),
        FieldDef("rehire_eligible", "Rehire eligible", "bool", s.rehire_eligible),
    ), s.employee_id, [s.tenant_id == tenant.tenant_id])


def _hiring_funnel(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    a, j = Application, JobRole
    join = a.__table__.outerjoin(j.__table__, j.id == a.job_role_id)
    return BuiltDataset(join, _fields(
        FieldDef("application_id", "Application", "id", a.id), FieldDef("status", "Stage", "str", a.status),
        FieldDef("job_title", "Job", "str", j.title), FieldDef("department", "Department", "str", j.department),
        FieldDef("location", "Location", "str", j.location), FieldDef("applied_on", "Applied on", "date", cast(a.created_at, Date)),
        FieldDef("applied_month", "Applied month", "date", _month(a.created_at)),
        FieldDef("match_score", "Match score", "num", a.match_score), FieldDef("composite_score", "Composite score", "num", a.composite_score),
        FieldDef("days_in_pipeline", "Days in pipeline", "num", func.extract("epoch", a.updated_at - a.created_at) / 86400),
    ), None, [a.tenant_id == tenant.tenant_id])


def _onboarding(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    c = PreboardingCase
    return BuiltDataset(c.__table__, _fields(
        FieldDef("case_id", "Case", "id", c.id), FieldDef("employee_id", "Employee", "id", c.employee_id),
        FieldDef("status", "Status", "str", c.status), FieldDef("joining_date", "Joining date", "date", c.joining_date),
        FieldDef("joining_month", "Joining month", "date", _month(c.joining_date)),
    ), c.employee_id, [c.tenant_id == tenant.tenant_id])


def _performance(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    r = Review
    return BuiltDataset(r.__table__, _fields(
        FieldDef("review_id", "Review", "id", r.id), FieldDef("cycle_id", "Cycle", "id", r.cycle_id),
        FieldDef("employee_id", "Employee", "id", r.employee_id), FieldDef("stage", "Stage", "str", r.stage),
        FieldDef("status", "Status", "str", r.status), FieldDef("overall_rating", "Rating", "num", r.overall_rating),
    ), r.employee_id, [r.tenant_id == tenant.tenant_id])


def _goals(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    g = Goal
    return BuiltDataset(g.__table__, _fields(
        FieldDef("goal_id", "Goal", "id", g.id), FieldDef("employee_id", "Owner", "id", g.owner_employee_id),
        FieldDef("level", "Level", "str", g.level), FieldDef("status", "Status", "str", g.status),
        FieldDef("progress_pct", "Progress %", "num", g.progress_pct), FieldDef("department_id", "Department", "id", g.department_id),
        FieldDef("completed", "Completed", "bool", g.status == "completed"),
    ), g.owner_employee_id, [g.tenant_id == tenant.tenant_id, g.status != "cancelled"])


def _helpdesk(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    t = Ticket
    breached = case((and_(t.resolution_due_at.isnot(None), func.coalesce(t.resolved_at, func.now()) > t.resolution_due_at), True), else_=False)
    return BuiltDataset(t.__table__, _fields(
        FieldDef("ticket_id", "Ticket", "id", t.id), FieldDef("employee_id", "Requester", "id", t.requester_employee_id),
        FieldDef("category", "Category", "str", t.category_code), FieldDef("priority", "Priority", "str", t.priority),
        FieldDef("status", "Status", "str", t.status), FieldDef("channel", "Channel", "str", t.channel),
        FieldDef("queue", "Queue", "str", t.queue_code), FieldDef("created_month", "Created month", "date", _month(t.created_at)),
        FieldDef("csat", "CSAT", "num", t.csat_score), FieldDef("sla_breached", "SLA breached", "bool", breached),
        FieldDef("escalation_level", "Escalation level", "num", t.escalation_level),
        FieldDef("resolution_hours", "Resolution (hours)", "num", func.extract("epoch", t.resolved_at - t.created_at) / 3600),
    ), t.requester_employee_id, [t.tenant_id == tenant.tenant_id, t.confidential.is_(False)])


def _assets(db: Session, tenant: TenantContext, as_of: date) -> BuiltDataset:
    a, al = Asset, AssetAllocation
    join = a.__table__.outerjoin(al.__table__, and_(al.asset_id == a.id, al.returned_at.is_(None)))
    return BuiltDataset(join, _fields(
        FieldDef("asset_id", "Asset", "id", a.id), FieldDef("asset_tag", "Tag", "str", a.asset_tag),
        FieldDef("category", "Category", "str", a.category_code), FieldDef("status", "Status", "str", a.status),
        FieldDef("location_id", "Location", "id", a.location_id), FieldDef("employee_id", "Allocated to", "id", al.employee_id),
        FieldDef("purchase_cost", "Purchase cost", "num", a.purchase_cost), FieldDef("warranty_until", "Warranty until", "date", a.warranty_until),
    ), None, [a.tenant_id == tenant.tenant_id])


DATASETS: dict[str, DatasetDef] = {d.code: d for d in (
    DatasetDef("headcount", "Headcount", "core_hr", "core_hr.employee.view", _headcount, field_security_entity="employee", custom_field_entity="employee", as_of_supported=True),
    DatasetDef("exits", "Attrition & exits", "separation", "separation.case.view", _exits),
    DatasetDef("hiring_funnel", "Hiring funnel", "recruitment", "recruitment.application.view", _hiring_funnel),
    DatasetDef("onboarding", "Onboarding", "onboarding", "onboarding.preboarding.view", _onboarding),
    DatasetDef("performance", "Performance reviews", "performance", "performance.review.view", _performance),
    DatasetDef("goals", "Goals", "performance", "performance.goal.view", _goals),
    DatasetDef("helpdesk", "Helpdesk", "helpdesk", "helpdesk.ticket.view", _helpdesk),
    DatasetDef("assets", "Assets", "assets", "assets.asset.view", _assets),
)}


def get_dataset(code: str) -> DatasetDef:
    if code not in DATASETS:
        raise KeyError(code)
    return DATASETS[code]


def describe(db: Session, tenant: TenantContext, code: str) -> dict:
    dataset = get_dataset(code)
    built = dataset.build(db, tenant, date.today())
    return {"code": dataset.code, "label": dataset.label, "module": dataset.module, "as_of_supported": dataset.as_of_supported,
            "fields": [{"key": f.key, "label": f.label, "type": f.type} for f in built.fields.values()]}


def select_from(built: BuiltDataset):
    return select().select_from(built.from_clause)
