"""interviewer_availability (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 6) -- the real
system-of-record this part introduces to eventually REPLACE the Excel `Interviewer Pool` /
`Interview Log` sheets (`app/interview_scheduling/tracker.py`) for busy-checking, selected
per tenant via the `recruitment.negotiation.busy_source` setting (internal | excel |
calendar). Keyed by `interviewer_email` -- the one identity field already shared by
`NegotiationToken`/`Interview` for a pool interviewer who may not have a `User` account
(see `Interview.interviewer_email`'s own docstring) -- with an optional `employee_id` link
once Part 7 has a real Employee row for them.

`weekly_pattern_json`/`exceptions_json` are stored as opaque JSON (day-of-week / date-keyed
availability) -- see `app/interview_scheduling/availability.py` for exactly which shape the
CURRENT internal busy-check actually reads (a deliberately scoped-down day-level check, not
the full weekly time-range granularity the column name suggests; see that module's own
docstring)."""

import uuid

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class InterviewerAvailability(Base, TenantOwned):
    __tablename__ = "interviewer_availability"
    __table_args__ = (
        UniqueConstraint("tenant_id", "interviewer_email", name="interviewer_availability_tenant_email_uq"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interviewer_email = Column(Text, nullable=False)
    interviewer_name = Column(Text)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    weekly_pattern_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    exceptions_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    max_interviews_per_day = Column(Integer)
    max_interviews_per_week = Column(Integer)
    skills_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 'manual' (admin-entered) | 'excel_import' (hrctl.import_interviewer_availability) --
    # purely informational provenance, nothing reads this to change behavior.
    source = Column(Text, nullable=False, server_default=text("'manual'"))
