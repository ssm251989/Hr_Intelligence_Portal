"""Part 17.12: interviewer pools kept in the app (replacing the Excel tracker's
"Interviewer Pool" + "Mails" sheets). A pool is for one job (job_role_id) or for any job
whose title / skills match its skills (skills_json); members are interviewer emails, whose
names, working hours, blocked dates and daily limits live in interviewer_availability.
TenantOwned + RLS."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class InterviewerPool(Base, TenantOwned):
    __tablename__ = "interviewer_pools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id", ondelete="CASCADE"), index=True)
    skills_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    member_emails_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # in the order they are tried
    active = Column(Boolean, nullable=False, server_default=text("true"))
    source = Column(Text, nullable=False, server_default=text("'manual'"))  # manual | excel_import
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
