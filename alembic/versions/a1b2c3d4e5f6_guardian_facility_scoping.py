"""guardian facility scoping: facility_id on cameras and persons

Revision ID: a1b2c3d4e5f6
Revises: e2a4c6f8b0d3
Create Date: 2026-06-08

Adds a nullable facility_id to cameras and persons so a multi-facility deploy
can scope which cameras expose which people. Null means "unscoped", which keeps
the single-household behaviour (a person is visible on every camera).
"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "e2a4c6f8b0d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("cameras", "persons"):
        op.add_column(
            table,
            sa.Column("facility_id", sa.UUID(as_uuid=True), nullable=True),
        )
        op.create_index(
            f"ix_{table}_facility_id", table, ["facility_id"], unique=False
        )
        op.create_foreign_key(
            f"fk_{table}_facility_id",
            table,
            "facilities",
            ["facility_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("cameras", "persons"):
        op.drop_constraint(f"fk_{table}_facility_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_facility_id", table_name=table)
        op.drop_column(table, "facility_id")
