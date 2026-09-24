"""Record the curator decision on identity relationships (#256)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "c1d2e3f4a5b6"
down_revision = "b5d7f9a1c3e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entity_associations", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "entity_associations",
        sa.Column("reviewed_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_entity_associations_reviewed_by_user",
        "entity_associations",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("entity_associations", sa.Column("review_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_associations", "review_note")
    op.drop_constraint("fk_entity_associations_reviewed_by_user", "entity_associations", type_="foreignkey")
    op.drop_column("entity_associations", "reviewed_by_user_id")
    op.drop_column("entity_associations", "reviewed_at")
