"""Hiring team per job (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 2) -- CRUD over
`JobHiringTeamMember`. See app/models/hiring_team.py's own docstring for why a member can
be either a real User or an external contact."""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.hiring_team import JobHiringTeamMember
from app.platform.tenancy.context import TenantContext


def add_member(
    db: Session, tenant: TenantContext, *, job_role_id: UUID, role_in_hiring: str,
    user_id: Optional[UUID] = None, external_name: Optional[str] = None, external_email: Optional[str] = None,
) -> JobHiringTeamMember:
    if user_id is None and not external_name:
        raise ValueError("A hiring team member needs either user_id or external_name")
    member = JobHiringTeamMember(
        tenant_id=tenant.tenant_id, job_role_id=job_role_id, role_in_hiring=role_in_hiring,
        user_id=user_id, external_name=external_name, external_email=external_email,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def list_members(db: Session, tenant: TenantContext, job_role_id: UUID) -> list[JobHiringTeamMember]:
    return (
        db.query(JobHiringTeamMember)
        .filter(JobHiringTeamMember.tenant_id == tenant.tenant_id, JobHiringTeamMember.job_role_id == job_role_id)
        .all()
    )


def remove_member(db: Session, tenant: TenantContext, member_id: UUID) -> None:
    member = db.get(JobHiringTeamMember, member_id)
    if member is not None and member.tenant_id == tenant.tenant_id:
        db.delete(member)
        db.commit()
