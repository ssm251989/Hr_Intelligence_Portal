"""part17 duplicate candidate detection

Revision ID: b8e4c2f6a9d3
Revises: a6d3f8b2c4e1
Create Date: 2026-09-27 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8e4c2f6a9d3'
down_revision: Union[str, Sequence[str], None] = 'a6d3f8b2c4e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('resume_sha256', sa.String(length=64), nullable=True))
    op.add_column('candidates', sa.Column('duplicate_of_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_candidates_resume_sha256'), 'candidates', ['resume_sha256'], unique=False)
    op.create_foreign_key('candidates_duplicate_of_fk', 'candidates', 'candidates', ['duplicate_of_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('candidates_duplicate_of_fk', 'candidates', type_='foreignkey')
    op.drop_index(op.f('ix_candidates_resume_sha256'), table_name='candidates')
    op.drop_column('candidates', 'duplicate_of_id')
    op.drop_column('candidates', 'resume_sha256')
