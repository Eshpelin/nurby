"""Keep notification idempotency keys out of visible alert text."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4a8c0b2d6e1"
down_revision: Union[str, None] = "f3f4a8c0b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.create_index("ix_notifications_dedupe_key", "notifications", ["dedupe_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_dedupe_key", table_name="notifications")
    op.drop_column("notifications", "dedupe_key")
