"""add webhook subscriptions

Standing outbound webhooks fanned out per fired event.

Revision ID: f2a4c6e8b1d3
Revises: d5b8c2f1a3e6
Create Date: 2026-05-30 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f2a4c6e8b1d3"
down_revision = "d5b8c2f1a3e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rule_ids", sa.JSON(), nullable=True),
        sa.Column("camera_ids", sa.JSON(), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("webhook_subscriptions")
