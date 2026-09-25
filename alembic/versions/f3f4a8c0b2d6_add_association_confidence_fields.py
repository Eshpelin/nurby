"""add explainable support/conflict balance to associations

Revision ID: f3f4a8c0b2d6
Revises: f3e2a6c8b0d4
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3f4a8c0b2d6"
down_revision: Union[str, None] = "f3e2a6c8b0d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_associations", sa.Column("supporting_evidence_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("entity_associations", sa.Column("contradictory_evidence_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("entity_associations", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column("entity_associations", sa.Column("decision_explanation", sa.Text(), nullable=True))
    # Existing counters cannot be reconstructed into individual source
    # episodes. Preserve their value but label the provenance honestly.
    op.execute(
        """
        UPDATE entity_associations
        SET supporting_evidence_count = COALESCE(evidence_count, 0),
            confidence_score = CASE WHEN COALESCE(evidence_count, 0) > 0 THEN 1.0 ELSE NULL END,
            decision_explanation = CASE
                WHEN COALESCE(evidence_count, 0) > 0
                THEN 'Legacy aggregate count; individual support episodes were not retained.'
                ELSE NULL
            END
        """
    )


def downgrade() -> None:
    op.drop_column("entity_associations", "decision_explanation")
    op.drop_column("entity_associations", "confidence_score")
    op.drop_column("entity_associations", "contradictory_evidence_count")
    op.drop_column("entity_associations", "supporting_evidence_count")
