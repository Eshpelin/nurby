"""resize face embeddings to 512 for insightface

Revision ID: d6e7f8a9b0c1
Revises: 4b1118a5954c
Create Date: 2026-04-22 23:40:00.000000

Drop-in swap of the face recognition backend from face_recognition (dlib,
128-dim) to InsightFace (ArcFace, 512-dim). No manual install step, pure
pip + ONNX runtime. The face_embeddings table was empty at migration time,
so we drop and recreate the column rather than attempt to reshape existing
vectors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "4b1118a5954c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clear the table first. Any rows are legacy 128-dim and cannot be
    # mixed with 512-dim InsightFace vectors. Empty in every current env.
    op.execute("DELETE FROM face_embeddings")
    op.drop_column("face_embeddings", "embedding")
    op.add_column(
        "face_embeddings",
        sa.Column("embedding", Vector(512), nullable=False),
    )


def downgrade() -> None:
    op.execute("DELETE FROM face_embeddings")
    op.drop_column("face_embeddings", "embedding")
    op.add_column(
        "face_embeddings",
        sa.Column("embedding", Vector(128), nullable=False),
    )
