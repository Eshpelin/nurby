"""Tests for services.agent.runs.

The lifecycle helpers operate on a real AsyncSession-shaped object.
We stub it with an ``AsyncMock`` that tracks ``db.add``, ``db.commit``,
``db.get``, and ``db.refresh``. Each test asserts on the row mutations
the helper performs, NOT on SQL strings.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent import runs as runs_mod
from shared.models import AgentRun, AgentToolCall, AgentVlmCall


def _run(coro):
    return asyncio.run(coro)


def _db_with_get(*, get_returns=None):
    """AsyncSession stub. ``db.get`` returns whatever ``get_returns``
    is set to (defaults to None). ``add`` records the appended row on
    ``db._added``. ``commit`` + ``refresh`` are no-ops."""

    db = AsyncMock()
    db._added = []

    def _add(row):
        db._added.append(row)

    db.add = MagicMock(side_effect=_add)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=get_returns)
    return db


# ── create_run ──────────────────────────────────────────────────────


def test_create_run_sets_defaults_and_running_status():
    user_id = uuid.uuid4()
    db = _db_with_get()
    run = _run(
        runs_mod.create_run(
            user_id=user_id,
            question="what did dad do today?",
            provider_id=None,
            model="claude-sonnet-4",
            parent_run_id=None,
            db=db,
        )
    )
    assert isinstance(run, AgentRun)
    assert run.user_id == user_id
    assert run.status == "running"
    assert run.turns_used == 0
    assert run.tokens_in == 0
    assert run.tokens_out == 0
    assert run.cost_cents == 0
    assert run.question == "what did dad do today?"
    assert run.model == "claude-sonnet-4"
    assert db.commit.await_count == 1
    assert db._added == [run]


def test_create_run_carries_parent_for_followups():
    parent = uuid.uuid4()
    db = _db_with_get()
    run = _run(
        runs_mod.create_run(
            user_id=uuid.uuid4(),
            question="and yesterday?",
            provider_id=None,
            model=None,
            parent_run_id=parent,
            db=db,
        )
    )
    assert run.parent_run_id == parent


# ── update_run ──────────────────────────────────────────────────────


def test_update_run_applies_allowed_fields():
    existing = AgentRun(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        question="q",
        status="running",
        turns_used=0,
        tokens_in=0,
        tokens_out=0,
        cost_cents=0,
    )
    db = _db_with_get(get_returns=existing)
    updated = _run(
        runs_mod.update_run(
            existing.id,
            db,
            status="completed",
            tokens_in=100,
            tokens_out=200,
            cost_cents=3,
            turns_used=2,
            final_answer="he ate breakfast",
        )
    )
    assert updated.status == "completed"
    assert updated.tokens_in == 100
    assert updated.tokens_out == 200
    assert updated.cost_cents == 3
    assert updated.turns_used == 2
    assert updated.final_answer == "he ate breakfast"


def test_update_run_rejects_unknown_field():
    existing = AgentRun(id=uuid.uuid4(), user_id=uuid.uuid4(), question="q", status="running")
    db = _db_with_get(get_returns=existing)
    with pytest.raises(ValueError):
        _run(runs_mod.update_run(existing.id, db, user_id=uuid.uuid4()))


def test_update_run_missing_raises():
    db = _db_with_get(get_returns=None)
    with pytest.raises(LookupError):
        _run(runs_mod.update_run(uuid.uuid4(), db, status="failed"))


# ── append_tool_call / complete_tool_call ────────────────────────────


def test_append_tool_call_persists_with_turn_index():
    db = _db_with_get()
    call = _run(
        runs_mod.append_tool_call(
            run_id=uuid.uuid4(),
            turn_index=0,
            tool_name="resolve_person",
            arguments={"name": "dad"},
            db=db,
        )
    )
    assert isinstance(call, AgentToolCall)
    assert call.tool_name == "resolve_person"
    assert call.arguments == {"name": "dad"}
    assert call.turn_index == 0
    assert call.result is None
    assert db._added == [call]


def test_append_tool_call_preserves_caller_supplied_turn_index():
    """The driver tracks the turn counter; ``append_tool_call`` does
    not auto-increment because multiple tool calls fan out per turn."""

    db = _db_with_get()
    run_id = uuid.uuid4()
    c0 = _run(
        runs_mod.append_tool_call(run_id, 0, "tool_a", {}, db)
    )
    c1 = _run(
        runs_mod.append_tool_call(run_id, 0, "tool_b", {}, db)  # same turn
    )
    c2 = _run(
        runs_mod.append_tool_call(run_id, 1, "tool_c", {}, db)
    )
    assert [c.turn_index for c in (c0, c1, c2)] == [0, 0, 1]


def test_complete_tool_call_updates_result_and_telemetry():
    existing = AgentToolCall(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        turn_index=0,
        tool_name="resolve_person",
        arguments={"name": "dad"},
        tokens_in=0,
        tokens_out=0,
    )
    db = _db_with_get(get_returns=existing)
    updated = _run(
        runs_mod.complete_tool_call(
            existing.id,
            db,
            result={"matches": [{"id": "p1", "score": 0.95}]},
            latency_ms=42,
            tokens_in=12,
            tokens_out=34,
        )
    )
    assert updated.result == {"matches": [{"id": "p1", "score": 0.95}]}
    assert updated.latency_ms == 42
    assert updated.tokens_in == 12
    assert updated.tokens_out == 34
    assert updated.error_message is None


def test_complete_tool_call_records_error_path():
    existing = AgentToolCall(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        turn_index=0,
        tool_name="analyze_clip",
        arguments={},
        tokens_in=0,
        tokens_out=0,
    )
    db = _db_with_get(get_returns=existing)
    updated = _run(
        runs_mod.complete_tool_call(
            existing.id,
            db,
            error="provider timeout",
            latency_ms=15000,
        )
    )
    assert updated.error_message == "provider timeout"
    assert updated.result is None


# ── record_vlm_call ─────────────────────────────────────────────────


def test_record_vlm_call_persists_with_target_kind():
    db = _db_with_get()
    obs_id = uuid.uuid4()
    call = _run(
        runs_mod.record_vlm_call(
            run_id=uuid.uuid4(),
            db=db,
            target_kind="frame",
            observation_id=obs_id,
            question="is the person eating?",
            response={"answer": "yes"},
            confidence=0.9,
            tokens_in=100,
            tokens_out=20,
            cost_cents=1,
            frame_count=4,
        )
    )
    assert isinstance(call, AgentVlmCall)
    assert call.target_kind == "frame"
    assert call.observation_id == obs_id
    assert call.cached is False
    assert call.cost_cents == 1


def test_record_vlm_call_rejects_bad_target_kind():
    db = _db_with_get()
    with pytest.raises(ValueError):
        _run(
            runs_mod.record_vlm_call(
                run_id=uuid.uuid4(),
                db=db,
                target_kind="image",  # invalid
                question="?",
            )
        )


def test_record_vlm_call_marks_cache_hit_with_zero_cost():
    db = _db_with_get()
    call = _run(
        runs_mod.record_vlm_call(
            run_id=uuid.uuid4(),
            db=db,
            target_kind="frame",
            observation_id=uuid.uuid4(),
            question="?",
            response={"answer": "no"},
            cached=True,
            tokens_in=0,
            tokens_out=0,
            cost_cents=0,
        )
    )
    assert call.cached is True
    assert call.cost_cents == 0


# ── cancel_run ──────────────────────────────────────────────────────


def test_cancel_run_sets_terminal_state():
    existing = AgentRun(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        question="q",
        status="running",
    )
    db = _db_with_get(get_returns=existing)
    updated = _run(runs_mod.cancel_run(existing.id, "user aborted", db))
    assert updated.status == "cancelled"
    assert updated.error_message == "user aborted"
    assert updated.ended_at is not None
    assert updated.ended_at.tzinfo is not None


def test_cancel_run_is_idempotent_on_terminal():
    existing = AgentRun(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        question="q",
        status="completed",
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db = _db_with_get(get_returns=existing)
    updated = _run(runs_mod.cancel_run(existing.id, "late", db))
    assert updated.status == "completed"  # unchanged
    assert db.commit.await_count == 0
