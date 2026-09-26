"""Part 15.6 agency portal (docs/HRMS_COMPLETE_SPEC.txt: "recruitment agencies (agency portal:
agency users submit candidates to assigned jobs only)"). An agency has its own users (flat
role "agency"), sees only the jobs HR assigns to it, and every candidate it sends is
recorded in `agency_submissions` so ownership is clear. TenantOwned + RLS."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class RecruitmentAgency(Base, TenantOwned):
    __tablename__ = "recruitment_agencies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="recruitment_agencies_name_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255))
    notes = Column(Text)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AgencyMember(Base, TenantOwned):
    """One login -> one agency."""

    __tablename__ = "agency_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="agency_members_user_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id = Column(UUID(as_uuid=True), ForeignKey("recruitment_agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AgencyJobAssignment(Base, TenantOwned):
    __tablename__ = "agency_job_assignments"
    __table_args__ = (UniqueConstraint("tenant_id", "agency_id", "job_role_id", name="agency_job_assignments_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id = Column(UUID(as_uuid=True), ForeignKey("recruitment_agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class AgencySubmission(Base, TenantOwned):
    """Which agency (and which of its users) sent an application."""

    __tablename__ = "agency_submissions"
    __table_args__ = (UniqueConstraint("tenant_id", "application_id", name="agency_submissions_application_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id = Column(UUID(as_uuid=True), ForeignKey("recruitment_agencies.id"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
