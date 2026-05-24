"""agent v1 schema. runs, tool calls, vlm calls, frame cache, daily usage

Revision ID. c8d9e0f1a2b3
Revises. b1c2d3e4f5a8

Wave 1A of the agentic Q&A layer (see docs/agent-design.md).

Adds.
* ``agent_runs`` lifecycle row with status + cost rollups
* ``agent_tool_calls`` per-turn audit
* ``agent_vlm_calls`` per analyzer invocation audit + redaction trail
* ``vlm_frame_analysis`` eternal per-frame Q&A cache (section 5.4).
  Partial unique indexes on (observation_id, ...) and (recording_id, ...)
  enforce the "one cache row per frame per question per model" rule
  while still allowing the other id column to be null.
* ``agent_daily_usage`` rollup for per-user budget enforcement.
  UNIQUE (user_id, usage_date) for cheap UPSERT.
* ``persons.audio_redact`` boolean column (resolution 5 in design
  doc section 17). Lands now so v2 can flip it without another
  migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b1c2d3e4f5a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── persons.audio_redact ───────────────────────────────────────
    op.add_column(
        "persons",
        sa.Column(
            "audio_redact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # ── agent_runs ─────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="running",
        ),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("turns_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Audit page lists runs by user, newest first. Composite index
    # avoids a sort on the hot path.
    op.create_index(
        "ix_agent_runs_user_started",
        "agent_runs",
        ["user_id", sa.text("started_at DESC")],
    )

    # ── agent_tool_calls ───────────────────────────────────────────
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Replay of a run reads tool calls ordered by turn_index.
    op.create_index(
        "ix_agent_tool_calls_run_turn",
        "agent_tool_calls",
        ["run_id", "turn_index"],
    )

    # ── agent_vlm_calls ────────────────────────────────────────────
    op.create_table(
        "agent_vlm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_tool_calls.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recording_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("time_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("thumbnails_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── vlm_frame_analysis (eternal cache, section 5.4) ────────────
    op.create_table(
        "vlm_frame_analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "recording_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "response_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("cost_tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thumbnail_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(observation_id IS NOT NULL) OR (recording_id IS NOT NULL)",
            name="ck_vlm_frame_analysis_target_present",
        ),
    )
    # Partial unique indexes. one row per (target, question, provider, model).
    op.create_index(
        "uq_vlm_frame_analysis_observation",
        "vlm_frame_analysis",
        ["observation_id", "question_hash", "provider_id", "model"],
        unique=True,
        postgresql_where=sa.text("observation_id IS NOT NULL"),
    )
    op.create_index(
        "uq_vlm_frame_analysis_recording",
        "vlm_frame_analysis",
        ["recording_id", "question_hash", "provider_id", "model"],
        unique=True,
        postgresql_where=sa.text("recording_id IS NOT NULL"),
    )
    # Plain lookup indexes (one per target column).
    op.create_index(
        "ix_vlm_frame_analysis_observation_id",
        "vlm_frame_analysis",
        ["observation_id"],
    )
    op.create_index(
        "ix_vlm_frame_analysis_recording_id",
        "vlm_frame_analysis",
        ["recording_id"],
    )

    # ── agent_daily_usage ──────────────────────────────────────────
    op.create_table(
        "agent_daily_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_agent_daily_usage_user_day"),
    )


def downgrade() -> None:
    op.drop_table("agent_daily_usage")
    op.drop_index("ix_vlm_frame_analysis_recording_id", table_name="vlm_frame_analysis")
    op.drop_index("ix_vlm_frame_analysis_observation_id", table_name="vlm_frame_analysis")
    op.drop_index("uq_vlm_frame_analysis_recording", table_name="vlm_frame_analysis")
    op.drop_index("uq_vlm_frame_analysis_observation", table_name="vlm_frame_analysis")
    op.drop_table("vlm_frame_analysis")
    op.drop_table("agent_vlm_calls")
    op.drop_index("ix_agent_tool_calls_run_turn", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_runs_user_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_column("persons", "audio_redact")
