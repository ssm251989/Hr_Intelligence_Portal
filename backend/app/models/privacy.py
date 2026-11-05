"""Privacy (docs/HRMS_COMPLETE_SPEC.txt Part 13 section E -- India DPDP Act 2023 + DPDP
Rules 2025, GDPR-ready). All `TenantOwned` + RLS.

- `privacy_notices`: versioned notice per purpose (candidates at apply, employees per purpose).
- `consent_records`: the consent ledger -- append-only; a withdrawal is a new row, never an
  update of the grant (so the history of what someone agreed to, when, stays provable).
- `data_principal_requests`: access / correction / erasure / grievance with an SLA.
- `retention_runs`: every purge is a dry-run report first, approved by a human, then executed.
- `breach_incidents`: the breach register + notification tracking.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

SUBJECT_TYPES = ("candidate", "employee", "user", "other")
CONSENT_ACTIONS = ("granted", "withdrawn")
DPR_TYPES = ("access", "correction", "erasure", "grievance", "nomination")
DPR_STATUSES = ("received", "verifying", "in_progress", "completed", "rejected")
RETENTION_RUN_STATUSES = ("dry_run", "approved", "executed", "rejected")
BREACH_SEVERITIES = ("low", "medium", "high", "critical")
BREACH_STATUSES = ("open", "contained", "notified", "closed")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


class PrivacyNotice(Base, TenantOwned):
    __tablename__ = "privacy_notices"
    __table_args__ = (UniqueConstraint("tenant_id", "purpose", "version", "language", name="privacy_notices_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purpose = Column(String(100), nullable=False)  # e.g. "recruitment.application", "employment.payroll_export"
    version = Column(Integer, nullable=False)
    language = Column(String(10), nullable=False, server_default=text("'en'"))
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'draft'"))  # draft | published | retired
    published_at = Column(DateTime(timezone=True))
    created_by = Column(Text)


class ConsentRecord(Base, TenantOwned):
    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(_in("subject_type", SUBJECT_TYPES), name="consent_records_subject_type_check"),
        CheckConstraint(_in("action", CONSENT_ACTIONS), name="consent_records_action_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_type = Column(String(20), nullable=False)
    subject_id = Column(UUID(as_uuid=True))
    subject_email = Column(Text)
    purpose = Column(String(100), nullable=False)
    notice_id = Column(UUID(as_uuid=True))
    notice_version = Column(Integer)
    action = Column(String(20), nullable=False)
    channel = Column(String(30), nullable=False, server_default=text("'web'"))  # web | career_site | portal | email | paper
    evidence_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # ip/user agent/checkbox text
    recorded_at = Column(DateTime(timezone=True), server_default=text("now()"))


class DataPrincipalRequest(Base, TenantOwned):
    __tablename__ = "data_principal_requests"
    __table_args__ = (
        CheckConstraint(_in("request_type", DPR_TYPES), name="dpr_type_check"),
        CheckConstraint(_in("status", DPR_STATUSES), name="dpr_status_check"),
        CheckConstraint(_in("subject_type", SUBJECT_TYPES), name="dpr_subject_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(String(20), nullable=False)
    subject_type = Column(String(20), nullable=False)
    subject_id = Column(UUID(as_uuid=True))
    subject_email = Column(Text, nullable=False)
    details = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'received'"))
    due_at = Column(DateTime(timezone=True), nullable=False)
    identity_verified_at = Column(DateTime(timezone=True))
    assigned_to = Column(Text)
    resolution = Column(Text)
    outcome_json = Column(JSONB)  # what was exported / corrected / anonymised / retained and why
    legal_hold = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    closed_at = Column(DateTime(timezone=True))


class RetentionRun(Base, TenantOwned):
    __tablename__ = "retention_runs"
    __table_args__ = (CheckConstraint(_in("status", RETENTION_RUN_STATUSES), name="retention_runs_status_check"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(50), nullable=False)
    cutoff = Column(Date, nullable=False)
    report_json = Column(JSONB, nullable=False)  # {"candidate_ids": [...], "count": n, "excluded": {...}}
    status = Column(String(20), nullable=False, server_default=text("'dry_run'"))
    requested_by = Column(Text, nullable=False)
    approved_by = Column(Text)
    executed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class BreachIncident(Base, TenantOwned):
    __tablename__ = "breach_incidents"
    __table_args__ = (
        CheckConstraint(_in("severity", BREACH_SEVERITIES), name="breach_incidents_severity_check"),
        CheckConstraint(_in("status", BREACH_STATUSES), name="breach_incidents_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    severity = Column(String(10), nullable=False)
    data_categories_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    affected_count = Column(Integer)
    status = Column(String(20), nullable=False, server_default=text("'open'"))
    board_notified_at = Column(DateTime(timezone=True))  # Data Protection Board
    principals_notified_at = Column(DateTime(timezone=True))
    actions_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # timeline
    reported_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
