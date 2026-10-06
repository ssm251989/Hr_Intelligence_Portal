"""Part 20.3: an employee asks for a change to their own profile; HR approves (then it is applied) or rejects."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

CHANGE_REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")


class EmployeeChangeRequest(Base, TenantOwned):
    __tablename__ = "employee_change_requests"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="employee_change_requests_status_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    requested_by = Column(Text)
    changes_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {field: {"old": .., "new": ..}}
    note = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    reviewed_by = Column(Text)
    reviewed_at = Column(DateTime(timezone=True))
    review_note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
