"""Add key_responsibilities, education_degree_level, education_field, and
preferred_certifications to job_roles.

Purely additive -- all 4 columns are nullable, and job_roles is empty at the time of
writing (a prior full data reset), so there's no backfill/parsing concern like the
experience_level and skills migrations before this one.

Revision ID: d1e6a3c9f8b4
Revises: c4d9e2a7f5b1
Create Date: 2026-08-22 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'd1e6a3c9f8b4'
down_revision: Union[str, Sequence[str], None] = 'c4d9e2a7f5b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept in sync with app.models.job_role.EDUCATION_DEGREE_LEVELS.
EDUCATION_DEGREE_LEVELS = ("Any", "Bachelor's", "Master's", "PhD", "Diploma")


def upgrade() -> None:
    op.add_column('job_roles', sa.Column('key_responsibilities', sa.Text(), nullable=True))
    op.add_column('job_roles', sa.Column('education_degree_level', sa.String(length=50), nullable=True))
    op.add_column('job_roles', sa.Column('education_field', sa.String(length=255), nullable=True))
    op.add_column('job_roles', sa.Column('preferred_certifications', JSONB(), nullable=True))
    op.create_check_constraint(
        'job_roles_education_degree_level_check',
        'job_roles',
        "education_degree_level IN ("
        + ",".join(f"'{level.replace(chr(39), chr(39) * 2)}'" for level in EDUCATION_DEGREE_LEVELS)
        + ") OR education_degree_level IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint('job_roles_education_degree_level_check', 'job_roles', type_='check')
    op.drop_column('job_roles', 'preferred_certifications')
    op.drop_column('job_roles', 'education_field')
    op.drop_column('job_roles', 'education_degree_level')
    op.drop_column('job_roles', 'key_responsibilities')
