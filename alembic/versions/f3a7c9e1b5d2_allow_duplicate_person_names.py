"""allow distinct people to share a display name

Revision ID: f3a7c9e1b5d2
Revises: f312a4b6c8d0
Create Date: 2026-09-26 00:00:00.000000

Names are labels, not stable identity keys.  A household can contain two
people with the same name, and an unknown face cluster must be allowed to be
kept separate when the user is not certain that it belongs to an existing
person.  Identity references use Person.id instead.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f3a7c9e1b5d2"
down_revision: Union[str, None] = "f312a4b6c8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_persons_display_name_lower")


def downgrade() -> None:
    # Re-creating this index can fail if a user has intentionally created
    # same-name people after upgrading.  Keep downgrade explicit and safe:
    # operators must resolve those duplicate labels before restoring the old
    # identity policy.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM persons p1
                JOIN persons p2 ON p1.id <> p2.id
                    AND lower(p1.display_name) = lower(p2.display_name)
            ) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS ux_persons_display_name_lower
                    ON persons (LOWER(display_name));
            ELSE
                RAISE EXCEPTION
                    'Cannot restore unique person names while duplicate labels exist';
            END IF;
        END $$;
        """
    )
