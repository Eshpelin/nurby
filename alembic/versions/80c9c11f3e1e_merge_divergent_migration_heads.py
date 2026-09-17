"""merge divergent migration heads

Revision ID: 80c9c11f3e1e
Revises: a1c3e5b7d9f2, b7e2c4a6d8f1
Create Date: 2026-09-17 17:10:35.576114
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '80c9c11f3e1e'
down_revision: Union[str, None] = ('a1c3e5b7d9f2', 'b7e2c4a6d8f1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
