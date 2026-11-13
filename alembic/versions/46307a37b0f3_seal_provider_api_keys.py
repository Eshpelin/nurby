"""seal provider api keys at rest

Revision ID: 46307a37b0f3
Revises: f5a7c9e1d3b5
Create Date: 2026-11-13 20:30:00.000000

Cloud LLM provider API keys were stored plaintext in providers.api_key,
while camera credentials and Telegram bot tokens were already Fernet-
sealed. The column widens to hold the token overhead, renames to
api_key_enc, and existing rows are sealed in place. Reads tolerate
plaintext (shared/camera_secrets.unseal passes unknown formats through),
so a partial upgrade keeps working.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "46307a37b0f3"
down_revision: Union[str, None] = "f5a7c9e1d3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "providers", "api_key",
        existing_type=sa.String(512), type_=sa.String(2048),
        existing_nullable=True,
    )
    op.alter_column(
        "providers", "api_key",
        new_column_name="api_key_enc", existing_type=sa.String(2048),
        existing_nullable=True,
    )

    from shared.camera_secrets import seal

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, api_key_enc FROM providers WHERE api_key_enc IS NOT NULL")
    ).fetchall()
    for row in rows:
        # seal() is a no-op on empty values; tokens start with gAAAA, so
        # re-running never double-encrypts.
        if not row.api_key_enc.startswith("gAAAA"):
            conn.execute(
                sa.text("UPDATE providers SET api_key_enc = :k WHERE id = :id"),
                {"k": seal(row.api_key_enc), "id": row.id},
            )


def downgrade() -> None:
    # Decrypt back to plaintext, then rename and narrow the column.
    from shared.camera_secrets import unseal

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, api_key_enc FROM providers WHERE api_key_enc IS NOT NULL")
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text("UPDATE providers SET api_key_enc = :k WHERE id = :id"),
            {"k": unseal(row.api_key_enc), "id": row.id},
        )
    op.alter_column(
        "providers", "api_key_enc",
        new_column_name="api_key", existing_type=sa.String(2048),
        existing_nullable=True,
    )
    op.alter_column(
        "providers", "api_key",
        existing_type=sa.String(2048), type_=sa.String(512),
        existing_nullable=True,
    )
