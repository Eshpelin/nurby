"""per-subject incident membership for an observation

Revision ID: b7d3f1a9c2e4
Revises: f2c1a4b6d8e0
Create Date: 2026-08-24 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b7d3f1a9c2e4'
down_revision: Union[str, None] = 'f2c1a4b6d8e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observation_incidents",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "observation_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("observations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "incident_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(255), nullable=False),
        sa.Column("bound_by", sa.String(16), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "observation_id", "incident_id", name="uq_observation_incident"
        ),
    )
    op.create_index(
        "ix_observation_incidents_observation_id",
        "observation_incidents", ["observation_id"],
    )
    op.create_index(
        "ix_observation_incidents_incident_id",
        "observation_incidents", ["incident_id"],
    )
    # Backfill the existing single link so the new table is complete for
    # history, not only for observations written from here on. Existing
    # rows are all single-subject by construction, so they are primary.
    op.execute(
        """
        INSERT INTO observation_incidents (
            id, observation_id, incident_id, subject_kind, subject_key,
            bound_by, is_primary, created_at
        )
        SELECT gen_random_uuid(), o.id, i.id, i.signature_kind,
               i.signature_key, NULL, true, now()
        FROM observations o
        JOIN incidents i ON i.id = o.incident_id
        WHERE o.incident_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_observation_incident DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_observation_incidents_incident_id", table_name="observation_incidents"
    )
    op.drop_index(
        "ix_observation_incidents_observation_id", table_name="observation_incidents"
    )
    op.drop_table("observation_incidents")
