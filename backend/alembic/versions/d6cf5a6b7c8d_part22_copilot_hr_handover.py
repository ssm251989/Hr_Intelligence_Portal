"""part 22.1: HR assistant drafts can be "hr_handover" (Helpdesk off -> HR to-do + email)

Revision ID: d6cf5a6b7c8d
Revises: c5be4f5a6b7c
Create Date: 2026-10-07 10:30:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd6cf5a6b7c8d'
down_revision: Union[str, Sequence[str], None] = 'c5be4f5a6b7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("copilot_drafts_action_check", "copilot_drafts", type_="check")
    op.create_check_constraint("copilot_drafts_action_check", "copilot_drafts",
                               "action IN ('raise_ticket','request_asset','request_letter','hr_handover')")


def downgrade() -> None:
    op.execute("UPDATE copilot_drafts SET action = 'raise_ticket' WHERE action = 'hr_handover'")
    op.drop_constraint("copilot_drafts_action_check", "copilot_drafts", type_="check")
    op.create_check_constraint("copilot_drafts_action_check", "copilot_drafts",
                               "action IN ('raise_ticket','request_asset','request_letter')")
