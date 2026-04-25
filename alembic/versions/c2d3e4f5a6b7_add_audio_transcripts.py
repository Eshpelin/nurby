"""add audio captures, transcripts, audit log + camera audio config

Revision ID: c2d3e4f5a6b7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-23 12:00:00.000000

Phase 1 of audio transcription plan. Schema for STT pipeline.

- ``audio_captures``. Optional raw audio storage when the user opts in.
- ``transcripts``. Speech segments with timing, text, embedding, and
  hallucination filter metadata. The per-camera time-range GiST index
  mirrors the one we added on ``observations`` so range-overlap joins
  remain index-driven.
- ``audio_audit_log``. Records every flip of an audio privacy toggle so
  there is a tamper-evident trail when a household member challenges a
  setting change.
- ``cameras``. Nine new columns gating capture, transcription, raw
  audio retention, transcript retention, default language, STT
  provider, and per-camera STT budget.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- cameras new columns ------------------------------------------
    op.add_column("cameras", sa.Column("audio_capture_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("audio_transcribe_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("audio_store_raw", sa.Boolean(), nullable=False, server_default=sa.false()))
    # transcript_store: 'full' | 'redacted' | 'summary_only'
    op.add_column("cameras", sa.Column("transcript_store", sa.String(16), nullable=False, server_default="full"))
    op.add_column("cameras", sa.Column("audio_language", sa.String(8), nullable=False, server_default="en"))
    op.add_column("cameras", sa.Column("audio_retention_days", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("cameras", sa.Column("transcript_retention_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column(
        "cameras",
        sa.Column(
            "stt_provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("cameras", sa.Column("stt_budget_minutes_per_hour", sa.Integer(), nullable=False, server_default="30"))

    # ---- audio_captures -----------------------------------------------
    op.create_table(
        "audio_captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("codec", sa.String(16), nullable=False, server_default="opus"),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default="16000"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audio_captures_camera_time", "audio_captures", ["camera_id", "started_at"])

    # ---- transcripts --------------------------------------------------
    op.create_table(
        "transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "audio_capture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audio_captures.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("text_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("no_speech_prob", sa.Float(), nullable=True),
        sa.Column("words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("filtered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transcripts_camera_time", "transcripts", ["camera_id", "started_at"])
    # Range-overlap index. mirrors observations_time_range_idx.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS transcripts_time_range_idx
        ON transcripts
        USING gist (camera_id, tstzrange(started_at, ended_at))
        """
    )
    # ivfflat index for semantic search. lists=100 is fine until ~1M rows.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS transcripts_embedding_idx
        ON transcripts
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    # ---- audio_audit_log ----------------------------------------------
    op.create_table(
        "audio_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("old_value", sa.String(255), nullable=True),
        sa.Column("new_value", sa.String(255), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audio_audit_log")
    op.execute("DROP INDEX IF EXISTS transcripts_embedding_idx")
    op.execute("DROP INDEX IF EXISTS transcripts_time_range_idx")
    op.drop_index("ix_transcripts_camera_time", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_audio_captures_camera_time", table_name="audio_captures")
    op.drop_table("audio_captures")
    for col in (
        "stt_budget_minutes_per_hour",
        "stt_provider_id",
        "transcript_retention_days",
        "audio_retention_days",
        "audio_language",
        "transcript_store",
        "audio_store_raw",
        "audio_transcribe_enabled",
        "audio_capture_enabled",
    ):
        op.drop_column("cameras", col)
