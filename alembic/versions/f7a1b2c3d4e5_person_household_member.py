"""Mark persons as household members for presence-based mode (#184).

Home/Away mode can flip automatically from the identity graph ("everyone
known has left" -> away, "someone arrived" -> home), but only if we know
which named people count as the household. A relationship string is too
fuzzy, so this adds an explicit, user-controllable flag.
"""

import sqlalchemy as sa

from alembic import op

revision = "f7a1b2c3d4e5"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persons",
        sa.Column("is_household_member", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("persons", "is_household_member")
