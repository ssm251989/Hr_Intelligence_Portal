"""actionable exit checklist: item statuses to do / requested / waiting for confirmation / done / not applicable /
blocked, owners, due dates, details + history; asset / ID card / finance / handover / exit-docs item kinds;
separations: completion note + letters emailed

Revision ID: e27a9b0c1d2f
Revises: d26f8a9b0c1e
Create Date: 2026-10-06 17:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e27a9b0c1d2f'
down_revision: Union[str, Sequence[str], None] = 'd26f8a9b0c1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUS = ("pending", "cleared", "waived")
NEW_STATUS = ("todo", "requested", "waiting_confirmation", "done", "not_applicable", "blocked")
OLD_KINDS = ("clearance", "asset_recovery", "access_revocation", "knowledge_transfer")
NEW_KINDS = OLD_KINDS + ("id_card", "finance_settlement", "handover_signoff", "exit_docs", "no_assets")
COLUMNS = (("item_key", sa.String(40)), ("owner_role", sa.String(20)), ("due_date", sa.Date()), ("reason", sa.Text()),
           ("auto_rule", sa.String(30)), ("requested_at", sa.DateTime(timezone=True)), ("last_reminder_at", sa.DateTime(timezone=True)))


def _in(col, values) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column('clearance_items', sa.Column(name, type_, nullable=True))
    op.add_column('clearance_items', sa.Column('details_json', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column('clearance_items', sa.Column('history_json', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.drop_constraint('clearance_items_status_check', 'clearance_items', type_='check')
    op.execute("UPDATE clearance_items SET status = CASE status WHEN 'pending' THEN 'todo' WHEN 'cleared' THEN 'done' WHEN 'waived' THEN 'not_applicable' ELSE status END")
    op.execute("UPDATE clearance_items SET reason = notes WHERE status = 'not_applicable' AND reason IS NULL")
    op.create_check_constraint('clearance_items_status_check', 'clearance_items', _in('status', NEW_STATUS))
    op.alter_column('clearance_items', 'status', server_default=sa.text("'todo'"))
    op.drop_constraint('clearance_items_kind_check', 'clearance_items', type_='check')
    op.create_check_constraint('clearance_items_kind_check', 'clearance_items', _in('kind', NEW_KINDS))
    op.add_column('separations', sa.Column('completion_note', sa.Text(), nullable=True))
    op.add_column('separations', sa.Column('letters_emailed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('separations', 'letters_emailed_at')
    op.drop_column('separations', 'completion_note')
    op.drop_constraint('clearance_items_kind_check', 'clearance_items', type_='check')
    op.execute("DELETE FROM clearance_items WHERE kind NOT IN (" + ",".join(f"'{k}'" for k in OLD_KINDS) + ")")
    op.create_check_constraint('clearance_items_kind_check', 'clearance_items', _in('kind', OLD_KINDS))
    op.drop_constraint('clearance_items_status_check', 'clearance_items', type_='check')
    op.execute("UPDATE clearance_items SET status = CASE WHEN status = 'done' THEN 'cleared' WHEN status = 'not_applicable' THEN 'waived' ELSE 'pending' END")
    op.create_check_constraint('clearance_items_status_check', 'clearance_items', _in('status', OLD_STATUS))
    op.alter_column('clearance_items', 'status', server_default=sa.text("'pending'"))
    for name in ('history_json', 'details_json', *[c for c, _ in reversed(COLUMNS)]):
        op.drop_column('clearance_items', name)
