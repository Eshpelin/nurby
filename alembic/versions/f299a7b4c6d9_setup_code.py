"""Add one-time cross-device setup-code storage (#299)."""

import sqlalchemy as sa
from alembic import op

revision = "f299a7b4c6d9"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("setup_code_hash", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("setup_code_ciphertext", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "setup_code_ciphertext")
    op.drop_column("users", "setup_code_hash")
