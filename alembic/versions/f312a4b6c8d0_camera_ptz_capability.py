"""Persist detected PTZ capability and ONVIF port."""

from alembic import op
import sqlalchemy as sa

revision = "f312a4b6c8d0"
down_revision = "f299a7b4c6d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("ptz_supported", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("onvif_port", sa.Integer(), nullable=True))
    op.alter_column("cameras", "ptz_supported", server_default=None)


def downgrade() -> None:
    op.drop_column("cameras", "onvif_port")
    op.drop_column("cameras", "ptz_supported")
