"""Job requisitions (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 2) -- the headcount-
approval step that precedes a job posting, separate from `JobRole` (which stays the
posting/pipeline record). Approval is gated by Part 5's workflow engine using the exact
same "un-gated if no published workflow_definition for this key" pattern Part 7's
`core_hr.lifecycle.request_event` already established -- see `app/recruitment/
requisitions.py`."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

REQUISITION_REASONS = ("new", "replacement")
REQUISITION_STATUSES = ("draft", "pending_approval", "approved", "rejected", "closed")


class JobRequisition(Base, TenantOwned):
    __tablename__ = "job_requisitions"
    __table_args__ = (
        CheckConstraint("reason IN (" + ",".join(f"'{r}'" for r in REQUISITION_REASONS) + ")", name="job_requisitions_reason_check"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in REQUISITION_STATUSES) + ")", name="job_requisitions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    # Nullable -- a requisition may target an existing Part 7 Position (replacement) or a
    # brand-new headcount not yet backed by one (reason="new").
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"))
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id"))  # set once a JobRole is posted against this requisition
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    reason = Column(Text, nullable=False, server_default=text("'new'"))
    headcount = Column(Integer, nullable=False, server_default=text("1"))
    budget = Column(Numeric)
    justification = Column(Text)
    status = Column(Text, nullable=False, server_default=text("'draft'"))
    workflow_instance_id = Column(UUID(as_uuid=True))
    requested_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
