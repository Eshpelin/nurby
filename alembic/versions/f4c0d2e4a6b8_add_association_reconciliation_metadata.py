"""Persist structured identity reconciliation details in review history (#258)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f4c0d2e4a6b8"
down_revision: Union[str, None] = "f4b9c1d3e5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "association_review_events",
        sa.Column("decision_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("association_review_events", "decision_metadata")
