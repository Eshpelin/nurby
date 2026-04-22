"""resize face cluster embeddings to 512 for insightface

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-04-22 23:48:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Wipe 128-dim dlib cluster rows. Samples cascade on cluster delete.
    # Recreate the embedding columns at 512-dim for InsightFace ArcFace.
    op.execute("DELETE FROM face_clusters")
    op.drop_column("face_cluster_samples", "embedding")
    op.add_column(
        "face_cluster_samples",
        sa.Column("embedding", Vector(512), nullable=False),
    )
    op.drop_column("face_clusters", "representative_embedding")
    op.add_column(
        "face_clusters",
        sa.Column("representative_embedding", Vector(512), nullable=False),
    )


def downgrade() -> None:
    op.execute("DELETE FROM face_clusters")
    op.drop_column("face_cluster_samples", "embedding")
    op.add_column(
        "face_cluster_samples",
        sa.Column("embedding", Vector(128), nullable=False),
    )
    op.drop_column("face_clusters", "representative_embedding")
    op.add_column(
        "face_clusters",
        sa.Column("representative_embedding", Vector(128), nullable=False),
    )
