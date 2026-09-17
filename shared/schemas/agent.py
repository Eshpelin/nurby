"""Ask and agent-run payloads: requests, responses, tool and
VLM call records, daily usage.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ── Agent v1 (Wave 1A) ──────────────────────────────────────────────
#
# Response models for the agentic Q&A surface. The driver returns
# AgentRunResponse for list endpoints (cheap) and AgentRunDetailResponse
# for the audit page (nested tool calls + vlm calls). AgentAskRequest
# is the user-facing entry point; AgentAskResponse hands back a run_id
# and websocket URL the frontend subscribes to for streaming tokens.


class MentionRef(BaseModel):
    """One @-mention attached to a natural-language input: the composer
    resolved a name to an entity id so the backend never guesses."""

    kind: Literal["person", "camera", "telegram_channel", "device"]
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)


class AgentAskRequest(BaseModel):
    """POST /api/agent/ask body. ``parent_run_id`` carries multi-turn
    follow-ups so the audit page can group them. ``dry_run`` short-
    circuits before any tool execution and returns the planned tool
    sequence only (used by tests + the future budget preview UI)."""

    question: str = Field(min_length=1, max_length=4000)
    provider_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=128)
    parent_run_id: uuid.UUID | None = None
    dry_run: bool = False
    mentions: list[MentionRef] = Field(default_factory=list, max_length=20)


class AgentAskResponse(BaseModel):
    """Immediate response from POST /api/agent/ask. The frontend
    subscribes to ``ws_url`` for streamed tokens + tool events."""

    run_id: uuid.UUID
    ws_url: str


class AgentRunResponse(BaseModel):
    """Cheap list-friendly run summary (no nested children)."""

    id: uuid.UUID
    user_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    question: str
    status: str
    final_answer: str | None
    provider_id: uuid.UUID | None
    model: str | None
    turns_used: int
    tokens_in: int
    tokens_out: int
    cost_cents: int
    latency_ms: int | None
    error_message: str | None
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class AgentToolCallResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    turn_index: int
    tool_name: str
    arguments: dict
    result: dict | None
    error_message: str | None
    latency_ms: int | None
    tokens_in: int
    tokens_out: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentVlmCallResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    tool_call_id: uuid.UUID | None
    provider_id: uuid.UUID | None
    model: str | None
    target_kind: str
    observation_id: uuid.UUID | None
    recording_id: uuid.UUID | None
    time_from: datetime | None
    time_to: datetime | None
    frame_count: int
    question: str
    response: dict | None
    confidence: float | None
    tokens_in: int
    tokens_out: int
    cost_cents: int
    cached: bool
    thumbnails_path: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunDetailResponse(AgentRunResponse):
    """Full audit-page payload. Nested tool calls + vlm calls."""

    plan: str | None = None
    tool_calls: list[AgentToolCallResponse] = Field(default_factory=list)
    vlm_calls: list[AgentVlmCallResponse] = Field(default_factory=list)


class AgentDailyUsageResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    usage_date: datetime
    tokens_in: int
    tokens_out: int
    cost_cents: int
    run_count: int
    updated_at: datetime

    model_config = {"from_attributes": True}
