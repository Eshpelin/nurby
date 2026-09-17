"""Regression tests for issue #222: a failed event insert must never produce
a fabricated event id or a downstream action chain referencing one.

``store_event`` returns None on a DB failure, and ``fire_actions`` skips the
action chain and subscription fan-out, broadcasting ``event_store_failed``
so an operator can see that a firing was dropped.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from services.events import actions as actions_mod
from services.events import firing as firing_mod
from tests._engine_helpers import FakeRule


class _FailingSession:
    """Async session stand-in whose commit always fails (simulated DB outage)."""

    def __init__(self, *args, **kwargs):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        raise RuntimeError("simulated db outage")

    async def refresh(self, obj):
        pass


@pytest.fixture
def rule():
    return FakeRule(name="Door person", trigger_pattern={"type": "object_detected"})


@pytest.mark.asyncio
async def test_store_event_returns_none_on_db_failure(monkeypatch, rule):
    monkeypatch.setattr(firing_mod, "async_session", _FailingSession)

    result = await firing_mod.store_event(rule.id, None, {"camera_id": None})

    assert result is None


@pytest.mark.asyncio
async def test_store_event_logs_payload_on_failure(monkeypatch, rule, caplog):
    monkeypatch.setattr(firing_mod, "async_session", _FailingSession)
    payload = {"camera_id": None, "message": "person at door"}

    with caplog.at_level("ERROR", logger="nurby.events.firing"):
        await firing_mod.store_event(rule.id, None, payload)

    # The firing must not vanish silently: the payload survives in the log
    # so it can be reconstructed manually after a DB outage window.
    assert any("person at door" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_fire_actions_skips_chain_and_fans_out_when_store_fails(monkeypatch, rule):
    monkeypatch.setattr(firing_mod, "store_event", AsyncMock(return_value=None))
    execute = AsyncMock()
    monkeypatch.setattr(actions_mod, "execute_action", execute)
    dispatch = AsyncMock()
    monkeypatch.setattr(actions_mod, "dispatch_subscriptions", dispatch)
    broadcasts: list[dict] = []

    async def _capture_broadcast(event):
        broadcasts.append(event)

    monkeypatch.setattr("services.api.ws.broadcast", _capture_broadcast)

    result = await firing_mod.fire_actions(rule, {}, [{"type": "notify"}])

    assert result is None
    execute.assert_not_awaited()
    dispatch.assert_not_awaited()
    assert any(b.get("type") == "event_store_failed" for b in broadcasts)


@pytest.mark.asyncio
async def test_fire_actions_still_runs_with_supplied_event_id(monkeypatch, rule):
    # The sequence path supplies its own event id; a healthy supplied id must
    # still run the full chain even though store_event is never called.
    store = AsyncMock()
    monkeypatch.setattr(firing_mod, "store_event", store)
    execute = AsyncMock()
    monkeypatch.setattr(actions_mod, "execute_action", execute)

    supplied = uuid.uuid4()
    result = await firing_mod.fire_actions(rule, {}, [{"type": "notify"}], event_id=supplied)

    assert result == supplied
    store.assert_not_awaited()
    execute.assert_awaited_once()
