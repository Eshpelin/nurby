"""dashboard widgets (custom data tiles)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-16 00:00:00.000000

User-defined dashboard tiles that pull data from an external HTTP API and
render it via a built-in template or sandboxed custom HTML/JS. The auth
secret is sealed at rest; the backend proxies the fetch.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("render_kind", sa.String(16), nullable=False, server_default="template"),
        sa.Column("source", JSON, nullable=True),
        sa.Column("auth_secret", sa.String(2048), nullable=True),
        sa.Column("template", JSON, nullable=True),
        sa.Column("custom_html", sa.Text, nullable=True),
        sa.Column("layout", JSON, nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_dashboard_widgets_created_by_user_id",
        "dashboard_widgets",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_widgets_created_by_user_id", table_name="dashboard_widgets")
    op.drop_table("dashboard_widgets")
