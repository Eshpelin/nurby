"""add recordings.clean_frame_path (model/migration drift fix)

The ``Recording`` model has declared ``clean_frame_path`` for a while, but no
migration ever created the column. Deployments that grew their schema
incrementally happened to have it (an older ad-hoc add), but a clean
migrate-from-scratch is missing it, so recording writes and retention queries
fail with ``UndefinedColumnError: column recordings.clean_frame_path does not
exist``. This adds the column to match the model.

Revision ID: f2c1a4b6d8e0
Revises: e0fad573effe
Create Date: 2026-07-19 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2c1a4b6d8e0"
down_revision: Union[str, None] = "e0fad573effe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: some existing databases already have this column from an
    # ad-hoc add before this migration existed, so only create it if missing.
    op.execute(
        "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS clean_frame_path "
        "VARCHAR(1024)"
    )


def downgrade() -> None:
    op.drop_column("recordings", "clean_frame_path")
