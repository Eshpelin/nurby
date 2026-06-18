"""add FK constraint on events.recording_id with ondelete SET NULL

Revision ID: e3f5a7c9b1d4
Revises: b1d3f5a7c9e2
Create Date: 2026-06-18 00:00:00.000000

events.recording_id was added as a bare UUID column with no FK (migration
d5b8c2f1a3e6). When RetentionManager deletes a Recording the column is
left dangling, causing "jump to clip" links to 404. Frigate saw the same
pattern in PRs #6319 / #8192.

Fix: backfill any already-dangling ids to NULL first, then add the FK
with ondelete="SET NULL" so future retention deletes are handled
automatically. Matches the nullable=True intent of the original column.

Closes #102.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f5a7c9b1d4"
down_revision: Union[str, Sequence[str], None] = "b1d3f5a7c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: null out already-dangling recording_id values so the FK
    # constraint can be created without violating referential integrity.
    op.execute(
        sa.text(
            "UPDATE events SET recording_id = NULL"
            " WHERE recording_id IS NOT NULL"
            " AND recording_id NOT IN (SELECT id FROM recordings)"
        )
    )

    # Step 2: add the FK constraint with ondelete SET NULL so future
    # Recording deletes degrade gracefully ("no clip" vs broken link).
    op.create_foreign_key(
        "fk_events_recording_id",
        "events",
        "recordings",
        ["recording_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_events_recording_id", "events", type_="foreignkey")
