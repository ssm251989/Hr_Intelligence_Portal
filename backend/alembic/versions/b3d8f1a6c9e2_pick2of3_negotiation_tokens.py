"""negotiation_tokens: replace the per-link kind/slot_time/marked_available fan-out with a
single selected_slots column (double-blind pick-2-of-3 redesign)

The old mechanic emitted 5 rows per batch (3 'slot' + 'not_available' + 'done'), one per
clickable link, since a click was the only action a recipient could take. The new mechanic
shows all 3 canned times on one page as checkboxes and asks for exactly 2, submitted
together -- one row per recipient is now enough, and kind/slot_time/marked_available have
no meaning under it (the 3 times are always derived from round_day, never stored per-row).

Any still-live (not yet invalidated) row is invalidated here rather than migrated: an
emailed link under the old mechanic points at a page the new GET/POST handlers can no
longer interpret (no kind to dispatch on), so leaving it "live" would just be a dead link
silently blocking that application's idempotency guard. Whoever is waiting on one of those
should be re-negotiated fresh via POST .../retry-negotiation (or the interviewer-batch-
resolved flow) once this migration is live.

Revision ID: b3d8f1a6c9e2
Revises: c3f7a9e2b5d8
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3d8f1a6c9e2'
down_revision: Union[str, Sequence[str], None] = 'c3f7a9e2b5d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE negotiation_tokens SET invalidated_at = now() WHERE invalidated_at IS NULL")

    op.add_column('negotiation_tokens', sa.Column('selected_slots', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_constraint('negotiation_tokens_kind_check', 'negotiation_tokens', type_='check')
    op.drop_column('negotiation_tokens', 'kind')
    op.drop_column('negotiation_tokens', 'slot_time')
    op.drop_column('negotiation_tokens', 'marked_available')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('negotiation_tokens', sa.Column('marked_available', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('negotiation_tokens', sa.Column('slot_time', sa.DateTime(timezone=True), nullable=True))
    op.add_column('negotiation_tokens', sa.Column('kind', sa.Text(), nullable=True))
    op.execute("UPDATE negotiation_tokens SET kind = 'done' WHERE kind IS NULL")
    op.alter_column('negotiation_tokens', 'kind', nullable=False)
    op.create_check_constraint('negotiation_tokens_kind_check', 'negotiation_tokens', "kind IN ('slot','not_available','done')")
    op.drop_column('negotiation_tokens', 'selected_slots')
