"""add provider input/output token caps

Revision ID: b7c8d9e1f2a3
Revises: a6b7c8d9e1f2
Create Date: 2026-05-07 17:00:00.000000

Both columns nullable. NULL means "no cap, let the provider's model
default decide". The user sets these at provider setup. Per-camera
caps remain as optional overrides that further tighten the limit.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7c8d9e1f2a3"
down_revision: Union[str, None] = "a6b7c8d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "providers",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("providers", "max_output_tokens")
    op.drop_column("providers", "max_input_tokens")
