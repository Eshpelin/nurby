"""entity associations between identities

Revision ID: c8e2b5d7f3a1
Revises: b7d3f1a9c2e4
Create Date: 2026-08-24 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8e2b5d7f3a1'
down_revision: Union[str, None] = 'b7d3f1a9c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_associations",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(255), nullable=False),
        sa.Column("object_kind", sa.String(16), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("object_label", sa.String(255), nullable=True),
        sa.Column(
            "relation", sa.String(32), nullable=False, server_default="uses"
        ),
        sa.Column(
            "source", sa.String(16), nullable=False, server_default="learned"
        ),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="candidate"
        ),
        sa.Column(
            "user_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("distinct_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_day", sa.String(10), nullable=True),
        sa.Column("hour_histogram", sa.JSON(), nullable=True),
        sa.Column("dow_histogram", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "subject_kind", "subject_key", "object_kind", "object_key",
            "relation", "source",
            name="uq_entity_association",
        ),
    )
    op.create_index(
        "ix_entity_associations_subject",
        "entity_associations", ["subject_kind", "subject_key"],
    )
    op.create_index(
        "ix_entity_associations_object",
        "entity_associations", ["object_kind", "object_key"],
    )
    # Associator bookkeeping. Null = this journey has not been folded into
    # associations yet. A column rather than a cursor so the pass is
    # idempotent and cannot skip a journey by drifting.
    op.add_column(
        "journeys",
        sa.Column("associations_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_journeys_associations_pending",
        "journeys", ["finalized", "associations_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_journeys_associations_pending", table_name="journeys")
    op.drop_column("journeys", "associations_at")
    op.drop_index("ix_entity_associations_object", table_name="entity_associations")
    op.drop_index("ix_entity_associations_subject", table_name="entity_associations")
    op.drop_table("entity_associations")
