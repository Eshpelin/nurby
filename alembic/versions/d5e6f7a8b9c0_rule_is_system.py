"""is_system on rules (#317).

Marks the product-default rules (camera content health) so the UI can
group and badge them instead of presenting them as if the household wrote
them. Backfills the two known system rules by name; the ensure paths in
services/api/routes/rules.py and services/events/engine.py set the flag
for fresh installs.
"""

from alembic import op
import sqlalchemy as sa

from shared.default_rules import CAMERA_HEALTH_RULE_NAME, CAMERA_RECOVERY_RULE_NAME

revision = "d5e6f7a8b9c0"
down_revision = "f299a7b4c6d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    rules = sa.table("rules", sa.column("name", sa.String), sa.column("is_system", sa.Boolean))
    op.execute(
        rules.update()
        .where(rules.c.name.in_([CAMERA_HEALTH_RULE_NAME, CAMERA_RECOVERY_RULE_NAME]))
        .values(is_system=True)
    )


def downgrade() -> None:
    op.drop_column("rules", "is_system")
