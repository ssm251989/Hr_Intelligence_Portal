"""Part 15.6 agency portal (docs/HRMS_COMPLETE_SPEC.txt: "recruitment agencies (agency portal:
agency users submit candidates to assigned jobs only)"). An agency has its own users (flat
role "agency"), sees only the jobs HR assigns to it, and every candidate it sends is
recorded in `agency_submissions` so ownership is clear. TenantOwned + RLS."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    # Part 21.5: Recruitment / BGV / Both
    agency_type = Column(String(20), nullable=False, server_default=text("'recruitment'"))
    contact_person = Column(Text)
    phone = Column(String(50))
    address = Column(Text)
    gst_pan = Column(String(50))
    contract_start = Column(Date)
    contract_end = Column(Date)
    fee_type = Column(String(20))  # recruitment: percent | fixed
    fee_value = Column(Numeric)
    payment_terms = Column(Text)
    bgv_checks_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # BGV: [{"check": "education", "price": 800}]
    turnaround_days = Column(Integer)  # BGV SLA
    report_format = Column(Text)


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


BGV_ASSIGNMENT_STATUSES = ("assigned", "in_progress", "report_received", "decided", "cancelled")


class BgvAssignment(Base, TenantOwned):
    """Part 21.4: one candidate's background check sent to a BGV vendor (an agency of type BGV / Both), with a secure
    expiring link that shows ONLY this candidate's documents and takes the vendor's report."""

    __tablename__ = "bgv_assignments"
    __table_args__ = (CheckConstraint("status IN ('assigned','in_progress','report_received','decided','cancelled')", name="bgv_assignments_status_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    agency_id = Column(UUID(as_uuid=True), ForeignKey("recruitment_agencies.id"), nullable=False)
    checks_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    due_date = Column(Date)
    status = Column(String(20), nullable=False, server_default=text("'assigned'"))
    token = Column(Text, nullable=False, unique=True)
    link_expires_at = Column(DateTime(timezone=True), nullable=False)
    opened_at = Column(DateTime(timezone=True))
    report_path = Column(Text)
    report_name = Column(Text)
    report_note = Column(Text)
    report_uploaded_at = Column(DateTime(timezone=True))
    decision = Column(String(20))
    decided_at = Column(DateTime(timezone=True))
    cost = Column(Numeric)
    reminders_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    cancelled_at = Column(DateTime(timezone=True))
    cancel_reason = Column(Text)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
