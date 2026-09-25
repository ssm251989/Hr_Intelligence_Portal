"""Hiring team per job (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 2): "recruiter(s),
hiring manager, interviewer pools (employees or external contacts - no User creation
needed)". `JobRole.hiring_manager_id` already covers the single hiring-manager case (Part
1); this table covers everyone else, and allows more than one recruiter/interviewer pool
member -- a row can name either a real `User` or an external contact (name/email only)."""

import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

HIRING_TEAM_ROLES = ("recruiter", "hiring_manager", "interviewer_pool")


class JobHiringTeamMember(Base, TenantOwned):
    __tablename__ = "job_hiring_team_members"
    __table_args__ = (
        CheckConstraint("role_in_hiring IN (" + ",".join(f"'{r}'" for r in HIRING_TEAM_ROLES) + ")", name="job_hiring_team_members_role_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"), nullable=False)
    role_in_hiring = Column(Text, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    external_name = Column(Text)
    external_email = Column(Text)
