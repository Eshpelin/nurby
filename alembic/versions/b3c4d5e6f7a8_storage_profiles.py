"""Storage profiles: per-camera recording locations (issue #251).

Adds the ``storage_profiles`` table — a named media-storage location
(kind + absolute root) — and a nullable ``cameras.storage_profile_id``.
Null keeps today's behaviour (the global recordings root); set, the
camera's segments land under the profile's root, resolved by
``shared/storage_paths.recordings_root_for``. Only ``kind="local"`` is
implemented in v1; the column is textual so remote backends (FTP / S3 /
WebDAV writers) can arrive without another migration.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="local"),
        sa.Column("root", sa.String(1024), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "cameras",
        sa.Column("storage_profile_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cameras_storage_profile_id",
        "cameras",
        "storage_profiles",
        ["storage_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_cameras_storage_profile_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "storage_profile_id")
    op.drop_table("storage_profiles")
