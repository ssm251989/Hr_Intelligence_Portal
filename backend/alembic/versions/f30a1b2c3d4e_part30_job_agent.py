"""part 30.1: the Job agent joins agent_activity

Revision ID: f30a1b2c3d4e
Revises: b4d7e9a1c3f5
Create Date: 2026-11-20 12:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f30a1b2c3d4e'
down_revision: Union[str, Sequence[str], None] = 'b4d7e9a1c3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "('watchdog','screening','sourcing','scheduling','salary','documents','bgv','offer','onboarding','exit','briefing')"
NEW = "('watchdog','job','screening','sourcing','scheduling','salary','documents','bgv','offer','onboarding','exit','briefing')"


def upgrade() -> None:
    op.drop_constraint('agent_activity_agent_check', 'agent_activity', type_='check')
    op.create_check_constraint('agent_activity_agent_check', 'agent_activity', f"agent IN {NEW}")


def downgrade() -> None:
    op.execute("DELETE FROM agent_activity WHERE agent = 'job'")
    op.drop_constraint('agent_activity_agent_check', 'agent_activity', type_='check')
    op.create_check_constraint('agent_activity_agent_check', 'agent_activity', f"agent IN {OLD}")
