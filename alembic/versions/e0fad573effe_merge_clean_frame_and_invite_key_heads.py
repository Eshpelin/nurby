"""merge clean-frame and invite-key heads

Revision ID: e0fad573effe
Revises: a3f5c1e9d7b2, d8f1a2b3c4e5
Create Date: 2026-07-19 13:26:45.190781
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e0fad573effe'
down_revision: Union[str, None] = ('a3f5c1e9d7b2', 'd8f1a2b3c4e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
