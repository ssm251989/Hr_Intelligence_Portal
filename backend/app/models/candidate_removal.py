"""Part 17.15: a bulk "Remove" / "Delete permanently" run (up to 500 candidates), done in the
background so the page can show progress. Holds ids and counts only -- no names or emails."""

import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class CandidateRemovalRun(Base, TenantOwned):
    __tablename__ = "candidate_removal_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode = Column(String(20), nullable=False)  # remove | delete
    reason = Column(String(30), nullable=False)
    note = Column(Text)
    candidate_ids = Column(JSONB, nullable=False)
    total = Column(Integer, nullable=False)
    done = Column(Integer, nullable=False, server_default=text("0"))
    skipped = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # [{"candidate_id", "why"}]
    status = Column(String(20), nullable=False, server_default=text("'running'"))  # running | finished | failed
    started_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True))
