"""Bind provisional bootstrap re-adoption to the installing browser (#299)."""

import sqlalchemy as sa
from alembic import op

revision = "f299a7b4c6d8"
down_revision = "e219a7b4c6d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bootstrap_secret_hash", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "bootstrap_secret_hash")
