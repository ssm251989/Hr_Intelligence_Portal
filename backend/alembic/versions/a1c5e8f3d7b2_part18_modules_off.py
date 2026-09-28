"""part18 switch off People, Performance, Helpdesk by default (owner decision 18.5)

Only the list of switched-on modules changes (setting platform.modules.enabled); no records are
touched, and each company can switch them on again in Settings > Advanced > Modules.

Revision ID: a1c5e8f3d7b2
Revises: f2a8d6c3b9e1
Create Date: 2026-09-28 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c5e8f3d7b2'
down_revision: Union[str, Sequence[str], None] = 'f2a8d6c3b9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OFF = ("core_hr", "performance", "helpdesk")


def upgrade() -> None:
    conn = op.get_bind()
    for code in OFF:
        conn.execute(sa.text(
            "update setting_values set value_json = coalesce((select jsonb_agg(v) from jsonb_array_elements(value_json) v where v <> to_jsonb(cast(:c as text))), '[]'::jsonb) "
            "where key = 'platform.modules.enabled' and jsonb_typeof(value_json) = 'array'"), {"c": code})


def downgrade() -> None:
    conn = op.get_bind()
    for code in OFF:
        conn.execute(sa.text(
            "update setting_values set value_json = value_json || to_jsonb(cast(:c as text)) "
            "where key = 'platform.modules.enabled' and jsonb_typeof(value_json) = 'array' and not value_json @> to_jsonb(cast(:c as text))"), {"c": code})
