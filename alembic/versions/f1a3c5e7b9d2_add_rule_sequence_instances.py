"""add rule_sequence_instances (temporal sequence rules, slice 1)

Revision ID: f1a3c5e7b9d2
Revises: d8b2f4a6c0e3
Create Date: 2026-06-21 00:00:00.000000

In-flight state for temporal sequence rules (docs/sequence-rules-design.md): one
row per active sequence instance (which rule, which correlated subject, the step
we're waiting on, and its deadline). The engine starts/advances rows on each
observation; a sweeper expires overdue ones. The (rule_id, status,
correlation_key) index serves the per-observation lookup; (status, step_deadline)
serves the sweeper scan.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a3c5e7b9d2"
down_revision: Union[str, None] = "d8b2f4a6c0e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_sequence_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("correlation_key", sa.String(length=255), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("step_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vars", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_sequence_instances_rule_id", "rule_sequence_instances", ["rule_id"])
    op.create_index(
        "ix_rule_seq_rule_status_key", "rule_sequence_instances",
        ["rule_id", "status", "correlation_key"],
    )
    op.create_index(
        "ix_rule_seq_status_deadline", "rule_sequence_instances",
        ["status", "step_deadline"],
    )


def downgrade() -> None:
    op.drop_index("ix_rule_seq_status_deadline", table_name="rule_sequence_instances")
    op.drop_index("ix_rule_seq_rule_status_key", table_name="rule_sequence_instances")
    op.drop_index("ix_rule_sequence_instances_rule_id", table_name="rule_sequence_instances")
    op.drop_table("rule_sequence_instances")
