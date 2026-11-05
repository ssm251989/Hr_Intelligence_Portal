"""Replace job_roles.skills (single flat list) with 4 categorized skill lists:
technical_skills_must_have, technical_skills_good_to_have, soft_skills_must_have,
soft_skills_good_to_have.

Every existing skill in the old flat `skills` column is moved into
technical_skills_must_have -- a one-time best-effort DEFAULT, not a real categorization:
this migration has no way to know which of a job's existing skills were actually
soft-skills or merely nice-to-have, so it puts all of them in the single category that
preserves their original behavior most closely (skills_score/suitability previously
treated every one of them as equally required). Every job with any pre-existing skills
gets one INFO log line naming it, specifically so this default is visible and reviewable
rather than a silent reinterpretation of that job's requirements.

Dropped `skills` outright rather than keeping it alongside the new columns: this dev DB's
job_roles table is empty at the time of writing (a prior full data reset), so there is no
real data at risk, and there is no reader left in the codebase for the old column once
this migration's callers are updated -- keeping it would just be schema debt with no path
to ever using it again. A deployment with real job_roles data should review the logged
per-job defaults *before* running this migration, and re-categorize afterward -- it's a
starting point, not a final answer.

Revision ID: c4d9e2a7f5b1
Revises: b8f3c1e7a4d2
Create Date: 2026-08-21 12:00:00.000000

"""
import json
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'c4d9e2a7f5b1'
down_revision: Union[str, Sequence[str], None] = 'b8f3c1e7a4d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _log_default_categorization(rows: list[tuple]) -> None:
    """Split out from upgrade() so a test can call it directly with a fabricated row list
    and assert on the log record, without needing a live alembic migration context."""
    if not rows:
        return
    logger.info(
        "skills migration: %d job_roles row(s) had existing skills moved into "
        "technical_skills_must_have as a one-time best-effort default (not a real "
        "categorization -- review and re-split into technical/soft, must-have/good-to-have "
        "as appropriate): %s",
        len(rows),
        [(str(job_id), skills) for job_id, skills in rows],
    )


def upgrade() -> None:
    op.add_column('job_roles', sa.Column('technical_skills_must_have', JSONB(), nullable=True))
    op.add_column('job_roles', sa.Column('technical_skills_good_to_have', JSONB(), nullable=True))
    op.add_column('job_roles', sa.Column('soft_skills_must_have', JSONB(), nullable=True))
    op.add_column('job_roles', sa.Column('soft_skills_good_to_have', JSONB(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, skills FROM job_roles WHERE skills IS NOT NULL")
    ).fetchall()

    non_empty = [(job_id, skills) for job_id, skills in rows if skills]
    for job_id, skills in non_empty:
        bind.execute(
            sa.text("UPDATE job_roles SET technical_skills_must_have = :skills::jsonb WHERE id = :id"),
            {"skills": json.dumps(skills), "id": job_id},
        )
    _log_default_categorization(non_empty)

    op.drop_column('job_roles', 'skills')


def downgrade() -> None:
    op.add_column('job_roles', sa.Column('skills', JSONB(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, technical_skills_must_have, technical_skills_good_to_have, "
            "soft_skills_must_have, soft_skills_good_to_have FROM job_roles"
        )
    ).fetchall()
    for job_id, tech_must, tech_good, soft_must, soft_good in rows:
        combined = [*(tech_must or []), *(tech_good or []), *(soft_must or []), *(soft_good or [])]
        if not combined:
            continue
        bind.execute(
            sa.text("UPDATE job_roles SET skills = :skills::jsonb WHERE id = :id"),
            {"skills": json.dumps(combined), "id": job_id},
        )

    op.drop_column('job_roles', 'technical_skills_must_have')
    op.drop_column('job_roles', 'technical_skills_good_to_have')
    op.drop_column('job_roles', 'soft_skills_must_have')
    op.drop_column('job_roles', 'soft_skills_good_to_have')
