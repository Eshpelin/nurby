"""provider reasoning / thinking controls (issue #41)

Adds optional, opt-in per-provider reasoning controls:
  * anthropic_thinking                 ("adaptive" | "enabled" | NULL=off)
  * anthropic_thinking_budget_tokens   (fixed budget for older models)
  * openai_reasoning_effort            ("minimal".."high" | NULL=off)

All NULL by default so existing providers behave exactly as before.

This revision also merges the three pre-existing heads
(d4e6f8a0b2c4, f2a4c6e8b1d3, f3a4b5c6d7e8) back into a single lineage.

Revision ID: e7f9a1c3b5d7
Revises: d4e6f8a0b2c4, f2a4c6e8b1d3, f3a4b5c6d7e8
Create Date: 2026-06-17 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e7f9a1c3b5d7'
down_revision: Union[str, Sequence[str], None] = 'e4f6a8c0b2d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('providers', sa.Column('anthropic_thinking', sa.String(length=16), nullable=True))
    op.add_column('providers', sa.Column('anthropic_thinking_budget_tokens', sa.Integer(), nullable=True))
    op.add_column('providers', sa.Column('openai_reasoning_effort', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('providers', 'openai_reasoning_effort')
    op.drop_column('providers', 'anthropic_thinking_budget_tokens')
    op.drop_column('providers', 'anthropic_thinking')
