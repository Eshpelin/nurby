"""Persist package delivery lifecycle candidates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "fb2c4d6e8a0"
down_revision = "fa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "package_lifecycle_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_key", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_present_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("absent_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_kind", sa.String(length=32), nullable=True),
        sa.Column("remover_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence", postgresql.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "tracking_key", name="uq_package_lifecycle_camera_key"),
    )
    op.create_index("ix_package_lifecycle_records_camera_id", "package_lifecycle_records", ["camera_id"])
    op.create_index("ix_package_lifecycle_records_camera_state", "package_lifecycle_records", ["camera_id", "state"])
    op.create_index("ix_package_lifecycle_records_remover_person_id", "package_lifecycle_records", ["remover_person_id"])
    op.create_index("ix_package_lifecycle_records_last_observation_id", "package_lifecycle_records", ["last_observation_id"])


def downgrade() -> None:
    op.drop_index("ix_package_lifecycle_records_last_observation_id", table_name="package_lifecycle_records")
    op.drop_index("ix_package_lifecycle_records_remover_person_id", table_name="package_lifecycle_records")
    op.drop_index("ix_package_lifecycle_records_camera_state", table_name="package_lifecycle_records")
    op.drop_index("ix_package_lifecycle_records_camera_id", table_name="package_lifecycle_records")
    op.drop_table("package_lifecycle_records")

