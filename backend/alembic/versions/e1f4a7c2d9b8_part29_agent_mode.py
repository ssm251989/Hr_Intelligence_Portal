"""part 29: agents run hiring to exit -- the Scheduling agent joins agent_activity

Revision ID: e1f4a7c2d9b8
Revises: c6a8e2f4b1d3
Create Date: 2026-11-10 12:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e1f4a7c2d9b8'
down_revision: Union[str, Sequence[str], None] = 'c6a8e2f4b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "('watchdog','screening','sourcing','salary','documents','bgv','offer','onboarding','exit','briefing')"
NEW = "('watchdog','screening','sourcing','scheduling','salary','documents','bgv','offer','onboarding','exit','briefing')"


def upgrade() -> None:
    op.drop_constraint('agent_activity_agent_check', 'agent_activity', type_='check')
    op.create_check_constraint('agent_activity_agent_check', 'agent_activity', f"agent IN {NEW}")


def downgrade() -> None:
    op.execute("DELETE FROM agent_activity WHERE agent = 'scheduling'")
    op.drop_constraint('agent_activity_agent_check', 'agent_activity', type_='check')
    op.create_check_constraint('agent_activity_agent_check', 'agent_activity', f"agent IN {OLD}")
