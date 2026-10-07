"""Part 22.4: Employees > Assign roles (app/employees/role_admin.py).

- GET  /api/v1/ui/employee-roles/catalog                 the roles HR can give (+ the company's custom roles)
- GET  /api/v1/ui/employee-roles?ids=<id>,<id>          each employee's current roles (and whether they have an app account)
- POST /api/v1/ui/employee-roles                         {employee_ids, set_role_ids | add_role_ids/remove_role_ids,
                                                          create_accounts, interviewer: {skills, pool_ids, max_per_day}}
Permission iam.role_assignments.configure (HR Admin / Super Admin by default).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.employees import role_admin
from app.models.core_hr import Employee
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/employee-roles", tags=["ui-employee-roles"])
PERM = "iam.role_assignments.configure"


def _employees(db: Session, ids: list[UUID]) -> list[Employee]:
    tenant = require_current_tenant()
    rows = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.id.in_(ids)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Employee not found")
    return rows


@router.get("/catalog")
def get_catalog(db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    return {"roles": role_admin.catalog(db, require_current_tenant())}


@router.get("")
def get_state(ids: str, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    wanted = [UUID(x) for x in ids.split(",") if x.strip()][:200]
    return {"items": role_admin.state(db, require_current_tenant(), _employees(db, wanted))}


class InterviewerIn(BaseModel):
    skills: list[str] = Field(default_factory=list)
    pool_ids: list[UUID] = Field(default_factory=list)
    max_per_day: Optional[int] = None


class ApplyIn(BaseModel):
    employee_ids: list[UUID]
    set_role_ids: Optional[list[str]] = None
    add_role_ids: list[str] = Field(default_factory=list)
    remove_role_ids: list[str] = Field(default_factory=list)
    create_accounts: bool = False
    interviewer: Optional[InterviewerIn] = None


@router.post("")
def apply_roles(body: ApplyIn, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    try:
        iv = body.interviewer.model_dump() if body.interviewer else None
        if iv:
            iv["skills"] = [s.strip()[:60] for s in iv["skills"] if s.strip()][:20]
        results = role_admin.apply(db, require_current_tenant(), _employees(db, body.employee_ids[:200]), actor=current_user,
                                   set_role_ids=body.set_role_ids if len(body.employee_ids) == 1 else None,
                                   add_role_ids=body.add_role_ids, remove_role_ids=body.remove_role_ids,
                                   create_accounts=body.create_accounts, interviewer=iv)
    except role_admin.RoleAdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"results": results}
