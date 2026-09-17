"""Per-user onboarding preferences (#204)."""

import sqlalchemy as sa
from alembic import op

revision = "a8d1f3b5c7e9"
down_revision = "f9c2d4e6a8b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_preferences", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "onboarding_preferences")
