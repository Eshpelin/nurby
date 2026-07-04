"""AgentRun lifecycle helpers.

The driver in (future) ``services/agent/driver.py`` owns the run loop;
this module owns the CRUD on the three audit tables. Each helper is a
thin, focused function so the driver stays declarative and the audit
trail is uniform across waves.

Wave 1B's tool registry calls ``append_tool_call`` + ``complete_tool_call``.
Wave 1C's analyzer calls ``record_vlm_call``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import AgentRun, AgentToolCall, AgentVlmCall

_logger = logging.getLogger("nurby.agent.runs")


_ALLOWED_RUN_PATCH = {
    "plan",
    "status",
    "final_answer",
    "provider_id",
    "model",
    "turns_used",
    "tokens_in",
    "tokens_out",
    "cost_cents",
    "latency_ms",
    "error_message",
    "ended_at",
}


_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "budget_exhausted"}


async def create_run(
    user_id: uuid.UUID,
    question: str,
    provider_id: uuid.UUID | None,
    model: str | None,
    parent_run_id: uuid.UUID | None,
    db: AsyncSession,
    mentions: list[dict] | None = None,
) -> AgentRun:
    """Create a new ``running`` AgentRun row and return it."""

    run = AgentRun(
        id=uuid.uuid4(),
        user_id=user_id,
        parent_run_id=parent_run_id,
        question=question,
        status="running",
        provider_id=provider_id,
        model=model,
        turns_used=0,
        tokens_in=0,
        tokens_out=0,
        cost_cents=0,
        mentions=mentions or None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def update_run(run_id: uuid.UUID, db: AsyncSession, **patch: Any) -> AgentRun:
    """Apply a partial update to an AgentRun.

    Only fields in ``_ALLOWED_RUN_PATCH`` are honored; unknown keys
    raise ``ValueError`` to fail loud rather than silently drop a
    counter update. The row is refreshed and returned.
    """

    bad = set(patch.keys()) - _ALLOWED_RUN_PATCH
    if bad:
        raise ValueError(f"update_run rejected unknown fields: {sorted(bad)}")
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise LookupError(f"AgentRun {run_id} not found")
    for key, value in patch.items():
        setattr(run, key, value)
    await db.commit()
    await db.refresh(run)
    return run


async def append_tool_call(
    run_id: uuid.UUID,
    turn_index: int,
    tool_name: str,
    arguments: dict,
    db: AsyncSession,
) -> AgentToolCall:
    """Persist a tool-call invocation. Returns the row so the caller
    can hand its id to ``complete_tool_call`` once the tool returns.

    ``turn_index`` is supplied by the driver (which owns the loop
    counter); we do not auto-increment here because a single turn can
    fan out into multiple tool calls.
    """

    call = AgentToolCall(
        id=uuid.uuid4(),
        run_id=run_id,
        turn_index=turn_index,
        tool_name=tool_name,
        arguments=arguments,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def complete_tool_call(
    call_id: uuid.UUID,
    db: AsyncSession,
    *,
    result: dict | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> AgentToolCall:
    """Stamp result/error + cost telemetry onto an existing tool call."""

    call = await db.get(AgentToolCall, call_id)
    if call is None:
        raise LookupError(f"AgentToolCall {call_id} not found")
    if result is not None:
        call.result = result
    if error is not None:
        call.error_message = error
    if latency_ms is not None:
        call.latency_ms = latency_ms
    if tokens_in:
        call.tokens_in = (call.tokens_in or 0) + int(tokens_in)
    if tokens_out:
        call.tokens_out = (call.tokens_out or 0) + int(tokens_out)
    await db.commit()
    await db.refresh(call)
    return call


async def record_vlm_call(
    run_id: uuid.UUID,
    db: AsyncSession,
    *,
    tool_call_id: uuid.UUID | None = None,
    provider_id: uuid.UUID | None = None,
    model: str | None = None,
    target_kind: str,
    observation_id: uuid.UUID | None = None,
    recording_id: uuid.UUID | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    frame_count: int = 0,
    question: str,
    response: dict | None = None,
    confidence: float | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_cents: int = 0,
    cached: bool = False,
    thumbnails_path: str | None = None,
) -> AgentVlmCall:
    """Persist a VLM analyzer invocation (real or cache-hit).

    Cache hits should still be recorded with ``cached=True`` and
    zeroed cost so the audit trail shows what the agent looked at
    even on the cheap path. ``target_kind`` must be one of
    ``frame``, ``clip``.
    """

    if target_kind not in {"frame", "clip"}:
        raise ValueError(f"target_kind must be 'frame' or 'clip', got {target_kind!r}")
    call = AgentVlmCall(
        id=uuid.uuid4(),
        run_id=run_id,
        tool_call_id=tool_call_id,
        provider_id=provider_id,
        model=model,
        target_kind=target_kind,
        observation_id=observation_id,
        recording_id=recording_id,
        time_from=time_from,
        time_to=time_to,
        frame_count=int(frame_count),
        question=question,
        response=response,
        confidence=confidence,
        tokens_in=int(tokens_in),
        tokens_out=int(tokens_out),
        cost_cents=int(cost_cents),
        cached=bool(cached),
        thumbnails_path=thumbnails_path,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def cancel_run(run_id: uuid.UUID, reason: str, db: AsyncSession) -> AgentRun:
    """Set ``status='cancelled'`` + ``ended_at`` + ``error_message``.

    Safe to call on an already-terminal run; it becomes a no-op and
    returns the row unchanged.
    """

    run = await db.get(AgentRun, run_id)
    if run is None:
        raise LookupError(f"AgentRun {run_id} not found")
    if run.status in _TERMINAL_STATUSES:
        return run
    run.status = "cancelled"
    run.ended_at = datetime.now(timezone.utc)
    run.error_message = reason
    await db.commit()
    await db.refresh(run)
    return run


async def next_turn_index(run_id: uuid.UUID, db: AsyncSession) -> int:
    """Compute the next ``turn_index`` for a run. Helper for the
    driver when it does not already track the counter in-process.
    Returns 0 for a fresh run.
    """

    stmt = select(func.coalesce(func.max(AgentToolCall.turn_index), -1)).where(
        AgentToolCall.run_id == run_id
    )
    current = (await db.execute(stmt)).scalar_one()
    return int(current) + 1


__all__ = [
    "append_tool_call",
    "cancel_run",
    "complete_tool_call",
    "create_run",
    "next_turn_index",
    "record_vlm_call",
    "update_run",
]
