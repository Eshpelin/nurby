"""seal camera credentials at rest

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-11 00:00:00.000000

Camera passwords and auth tokens were stored plaintext; a database backup
leaked every camera credential. They are now Fernet-sealed with the same
cipher Telegram bot tokens use (shared/camera_secrets, keyed off
jwt_secret). Columns widen to hold the token overhead, then existing
plaintext rows are encrypted in place. Reads tolerate plaintext (unseal
passes unknown formats through), so a partial upgrade keeps connecting.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "cameras", "password",
        existing_type=sa.String(255), type_=sa.String(2048),
        existing_nullable=True,
    )
    op.alter_column(
        "cameras", "auth_token",
        existing_type=sa.String(512), type_=sa.String(2048),
        existing_nullable=True,
    )

    from shared.camera_secrets import seal

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, password, auth_token FROM cameras "
            "WHERE password IS NOT NULL OR auth_token IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        updates = {}
        # seal() is a no-op on empty values; Fernet tokens start with
        # gAAAA, so re-running never double-encrypts.
        if row.password and not row.password.startswith("gAAAA"):
            updates["password"] = seal(row.password)
        if row.auth_token and not row.auth_token.startswith("gAAAA"):
            updates["auth_token"] = seal(row.auth_token)
        if updates:
            sets = ", ".join(f"{k} = :{k}" for k in updates)
            conn.execute(
                sa.text(f"UPDATE cameras SET {sets} WHERE id = :id"),
                {**updates, "id": row.id},
            )


def downgrade() -> None:
    # Decrypt back to plaintext, then narrow the columns.
    from shared.camera_secrets import unseal

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, password, auth_token FROM cameras "
            "WHERE password IS NOT NULL OR auth_token IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE cameras SET password = :p, auth_token = :t WHERE id = :id"
            ),
            {"p": unseal(row.password), "t": unseal(row.auth_token), "id": row.id},
        )
    op.alter_column(
        "cameras", "auth_token",
        existing_type=sa.String(2048), type_=sa.String(512),
        existing_nullable=True,
    )
    op.alter_column(
        "cameras", "password",
        existing_type=sa.String(2048), type_=sa.String(255),
        existing_nullable=True,
    )
