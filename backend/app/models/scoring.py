"""Part 17.5: scoring rule versions and recalculation runs. TenantOwned + RLS.

A company default has job_role_id NULL; a job override has its job_role_id. Every save
adds a NEW version row (history + revert = save an old version again); the highest version
per scope is the one in use."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class ScoringRuleSet(Base, TenantOwned):
    __tablename__ = "scoring_rule_sets"
    __table_args__ = (UniqueConstraint("tenant_id", "job_role_id", "version", name="scoring_rule_sets_version_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id", ondelete="CASCADE"), index=True)
    version = Column(Integer, nullable=False)
    rules_json = Column(JSONB, nullable=False)
    note = Column(Text)  # e.g. "From preset: Balanced", "Reverted to version 3"
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ScoreRecalcRun(Base, TenantOwned):
    """One background recalculation after a rules save (progress shown on screen)."""

    __tablename__ = "score_recalc_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_role_id = Column(UUID(as_uuid=True), ForeignKey("job_roles.id", ondelete="CASCADE"))
    rule_set_id = Column(UUID(as_uuid=True), ForeignKey("scoring_rule_sets.id", ondelete="SET NULL"))
    status = Column(String(20), nullable=False, server_default=text("'queued'"))  # queued | running | done | failed
    total = Column(Integer, nullable=False, server_default=text("0"))
    done = Column(Integer, nullable=False, server_default=text("0"))
    changed = Column(Integer, nullable=False, server_default=text("0"))
    error = Column(Text)
    started_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True))
