"""trace an utterance back to the agent run that chose it

Revision ID: d3b9c1e5f7a2
Revises: c7f2a8b4d1e6
Create Date: 2026-09-08 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd3b9c1e5f7a2'
down_revision: Union[str, None] = 'c7f2a8b4d1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "speech_events",
        sa.Column("agent_run_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_speech_events_agent_run_id", "speech_events", "agent_runs",
        ["agent_run_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_speech_events_agent_run_id", "speech_events", ["agent_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_speech_events_agent_run_id", table_name="speech_events")
    op.drop_constraint(
        "fk_speech_events_agent_run_id", "speech_events", type_="foreignkey"
    )
    op.drop_column("speech_events", "agent_run_id")
