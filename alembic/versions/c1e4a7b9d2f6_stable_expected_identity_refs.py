"""Add stable person references to expected activity (#285)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "c1e4a7b9d2f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "expected_activities",
        sa.Column("subject_person_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_expected_activities_subject_person_id",
        "expected_activities",
        ["subject_person_id"],
    )
    op.create_foreign_key(
        "fk_expected_activities_subject_person_id_persons",
        "expected_activities",
        "persons",
        ["subject_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Only backfill unambiguous names. Duplicate display names remain legacy
    # and are intentionally surfaced for manual selection rather than guessed.
    op.execute(
        """
        UPDATE expected_activities e
        SET subject_person_id = p.id
        FROM persons p
        WHERE e.subject_kind = 'person'
          AND e.subject_person_id IS NULL
          AND e.subject_key IS NOT NULL
          AND lower(p.display_name) = lower(e.subject_key)
          AND 1 = (
            SELECT count(*) FROM persons p2
            WHERE lower(p2.display_name) = lower(e.subject_key)
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_expected_activities_subject_person_id_persons",
        "expected_activities",
        type_="foreignkey",
    )
    op.drop_index("ix_expected_activities_subject_person_id", table_name="expected_activities")
    op.drop_column("expected_activities", "subject_person_id")
