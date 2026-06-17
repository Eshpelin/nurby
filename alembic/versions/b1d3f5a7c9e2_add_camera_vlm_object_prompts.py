"""add cameras.vlm_object_prompts (per-object-class prompt guidance)

Revision ID: b1d3f5a7c9e2
Revises: a4e6c8f0b2d5
Create Date: 2026-06-17 00:00:00.000000

Per-camera, per-object-class VLM prompt guidance. A nullable JSON
{label: guidance} map. Nurby's VLM is scene-level (one call per keyframe
over all detections), so at prompt-build time the snippets for whichever
labels are present in the frame are unioned into the prompt. Mirrors
Frigate's per-camera genai object_prompts (PR #13767), adapted from
Frigate's per-tracked-object model to Nurby's scene-level model.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1d3f5a7c9e2"
down_revision: Union[str, Sequence[str], None] = "a4e6c8f0b2d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("vlm_object_prompts", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "vlm_object_prompts")
