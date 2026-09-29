"""Add separate relationship evidence privacy controls (#256)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f5a7c9e1d3b5"
down_revision: Union[str, None] = "ff9d1e3f5a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in (
        "vehicle_relationship_inference_enabled",
        "cooccurrence_inference_enabled",
        "name_mention_inference_enabled",
    ):
        op.add_column("cameras", sa.Column(name, sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    for name in (
        "name_mention_inference_enabled",
        "cooccurrence_inference_enabled",
        "vehicle_relationship_inference_enabled",
    ):
        op.drop_column("cameras", name)
