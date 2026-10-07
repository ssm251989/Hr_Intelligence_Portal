"""Part 18.15: department hiring budgets (Settings > Hiring > Department budgets) and the
Salary > Finance dashboard.

- GET    /api/v1/ui/budgets?fiscal_year=         every department (from jobs + budgets) with its budget and money used
- PUT    /api/v1/ui/budgets                       {department, fiscal_year, allocated, quarters?, alert_pct, on_exceed}
- DELETE /api/v1/ui/budgets/{id}
- GET    /api/v1/ui/budgets/dashboard?fiscal_year=  per department allocated / reserved / committed / remaining,
         month trend, top roles by cost, alerts
- GET    /api/v1/ui/budgets/export?fiscal_year=     the same as an Excel file
"""

import io
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.department_budget import BudgetCommitment, DepartmentBudget
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import budgets

router = APIRouter(prefix="/api/v1/ui/budgets", tags=["ui-budgets"])


def _need(db, user, perm):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, perm):
        raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return tenant


def _summary(db, tenant, fy: str) -> list[dict]:
    rows = {b.department: b for b in db.query(DepartmentBudget).filter(DepartmentBudget.tenant_id == tenant.tenant_id, DepartmentBudget.fiscal_year == fy)}
    depts = {d for (d,) in db.query(JobRole.department).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.department.isnot(None)).distinct() if d}
    used = defaultdict(lambda: {"reserved": 0.0, "committed": 0.0, "hires": 0})
    for dept, state, amount, n in db.query(BudgetCommitment.department, BudgetCommitment.state, func.sum(BudgetCommitment.amount), func.count()).filter(
            BudgetCommitment.tenant_id == tenant.tenant_id, BudgetCommitment.fiscal_year == fy, BudgetCommitment.state.in_(("reserved", "committed"))
    ).group_by(BudgetCommitment.department, BudgetCommitment.state):
        used[dept][state] = float(amount or 0)
        used[dept]["hires"] += n
    out = []
    for d in sorted(depts | set(rows) | set(used)):
        b = rows.get(d)
        u = used[d]
        spent = u["reserved"] + u["committed"]
        alloc = float(b.allocated) if b else None
        pct = round(100 * spent / alloc, 1) if alloc else None
        out.append({"id": str(b.id) if b else None, "department": d, "fiscal_year": fy, "allocated": alloc,
                    "quarters": b.quarters_json if b else None, "alert_pct": b.alert_pct if b else 80, "on_exceed": b.on_exceed if b else "needs_approval",
                    "reserved": u["reserved"], "committed": u["committed"], "hires": u["hires"],
                    "remaining": (alloc - spent) if alloc is not None else None, "used_pct": pct,
                    "alert": bool(b and pct is not None and pct >= b.alert_pct), "exceeded": bool(alloc is not None and spent > alloc)})
    return out


@router.get("")
def list_budgets(fiscal_year: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.salary.view")
    fy = fiscal_year or budgets.fiscal_year(db, tenant)
    years = sorted({y for (y,) in db.query(DepartmentBudget.fiscal_year).filter(DepartmentBudget.tenant_id == tenant.tenant_id).distinct()} | {budgets.fiscal_year(db, tenant)})
    return {"fiscal_year": fy, "fiscal_years": years, "departments": _summary(db, tenant, fy),
            "can_edit": has_permission(db, tenant, current_user, "platform.settings.configure")}


class BudgetIn(BaseModel):
    department: str = Field(min_length=1, max_length=200)
    fiscal_year: str = Field(pattern=r"^\d{4}(-\d{2})?$")
    allocated: float = Field(ge=0, le=1e13)
    quarters: Optional[dict[str, float]] = None
    alert_pct: int = Field(80, ge=1, le=100)
    on_exceed: str = Field("needs_approval", pattern="^(needs_approval|block)$")


@router.put("")
def save_budget(body: BudgetIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "platform.settings.configure")
    if body.quarters:
        bad = set(body.quarters) - {"Q1", "Q2", "Q3", "Q4"}
        if bad:
            raise HTTPException(status_code=400, detail="Quarters must be Q1-Q4.")
        if sum(body.quarters.values()) > body.allocated + 0.5:
            raise HTTPException(status_code=400, detail="The quarters add up to more than the yearly budget.")
    row = db.query(DepartmentBudget).filter(DepartmentBudget.tenant_id == tenant.tenant_id, DepartmentBudget.department == body.department.strip(),
                                            DepartmentBudget.fiscal_year == body.fiscal_year).first()
    before = float(row.allocated) if row else None
    if row is None:
        row = DepartmentBudget(tenant_id=tenant.tenant_id, department=body.department.strip(), fiscal_year=body.fiscal_year, allocated=body.allocated)
        db.add(row)
    row.allocated, row.quarters_json, row.alert_pct, row.on_exceed = body.allocated, body.quarters or None, body.alert_pct, body.on_exceed
    row.updated_by, row.updated_at = current_user.email, datetime.now(timezone.utc)
    db.commit()
    log_action(db, "department_budget", row.id, "department_budget_saved", current_user.email[:50],
               {"department": row.department, "fiscal_year": row.fiscal_year, "allocated_before": before, "allocated": body.allocated, "on_exceed": body.on_exceed})
    return {"id": str(row.id), "saved": True}


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "platform.settings.configure")
    row = db.query(DepartmentBudget).filter(DepartmentBudget.tenant_id == tenant.tenant_id, DepartmentBudget.id == budget_id).first()
    if row is not None:
        log_action(db, "department_budget", row.id, "department_budget_deleted", current_user.email[:50], {"department": row.department, "fiscal_year": row.fiscal_year})
        db.delete(row)
        db.commit()
    return None


@router.get("/dashboard")
def dashboard(fiscal_year: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _need(db, current_user, "recruitment.salary.view")
    fy = fiscal_year or budgets.fiscal_year(db, tenant)
    depts = _summary(db, tenant, fy)
    live = db.query(BudgetCommitment).filter(BudgetCommitment.tenant_id == tenant.tenant_id, BudgetCommitment.fiscal_year == fy,
                                             BudgetCommitment.state.in_(("reserved", "committed"))).all()
    trend: dict = defaultdict(lambda: {"reserved": 0.0, "committed": 0.0})
    roles: dict = defaultdict(lambda: {"amount": 0.0, "hires": 0})
    for c in live:
        month = (c.created_at or datetime.now(timezone.utc)).strftime("%Y-%m")
        trend[month][c.state] += float(c.amount)
        key = (c.job_title or "—", c.department)
        roles[key]["amount"] += float(c.amount)
        roles[key]["hires"] += 1
    alerts = [{"department": d["department"], "kind": "exceeded" if d["exceeded"] else "near", "used_pct": d["used_pct"], "remaining": d["remaining"]}
              for d in depts if d["alert"] or d["exceeded"]]
    total_alloc = sum(d["allocated"] or 0 for d in depts)
    totals = {"allocated": total_alloc, "reserved": sum(d["reserved"] for d in depts), "committed": sum(d["committed"] for d in depts)}
    totals["remaining"] = total_alloc - totals["reserved"] - totals["committed"]
    return {"fiscal_year": fy, "totals": totals, "departments": depts,
            "trend": [{"month": m, **v} for m, v in sorted(trend.items())],
            "top_roles": sorted(({"job_title": k[0], "department": k[1], **v} for k, v in roles.items()), key=lambda r: -r["amount"])[:10],
            "alerts": alerts, "history": budgets.history(db, tenant, fy)}  # Part 21.7


@router.get("/export")
def export(fiscal_year: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from openpyxl import Workbook

    data = dashboard(fiscal_year, db, current_user)
    wb = Workbook()
    ws = wb.active
    ws.title = f"Budgets {data['fiscal_year']}"
    ws.append(["Department", "Allocated", "Reserved", "Committed", "Remaining", "Used %", "Hires", "Alert at %", "When exceeded"])
    for d in data["departments"]:
        ws.append([d["department"], d["allocated"], d["reserved"], d["committed"], d["remaining"], d["used_pct"], d["hires"], d["alert_pct"], d["on_exceed"]])
    t = data["totals"]
    ws.append(["Total", t["allocated"], t["reserved"], t["committed"], t["remaining"]])
    ws2 = wb.create_sheet("Top roles")
    ws2.append(["Role", "Department", "Cost", "Hires"])
    for r in data["top_roles"]:
        ws2.append([r["job_title"], r["department"], r["amount"], r["hires"]])
    ws3 = wb.create_sheet("By month")
    ws3.append(["Month", "Reserved", "Committed"])
    for r in data["trend"]:
        ws3.append([r["month"], r["reserved"], r["committed"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="hiring-budgets-{data["fiscal_year"]}.xlsx"'})
