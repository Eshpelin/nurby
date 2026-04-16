"""merge notification and motion zone branches

Revision ID: 5f395ac9f751
Revises: a3b4c5d6e7f8, c4d5e6f7a8b9
Create Date: 2026-04-16 18:14:34.261805
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '5f395ac9f751'
down_revision: Union[str, None] = ('a3b4c5d6e7f8', 'c4d5e6f7a8b9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
