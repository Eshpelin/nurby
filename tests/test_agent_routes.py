"""Unit tests for services.api.routes.agent.

The route handlers are invoked directly with stubbed dependencies. We do
NOT spin up the full FastAPI app since the rest of the test suite is
unit-style. Background driver-task launches are patched away so each
test asserts the route-level behavior in isolation.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.api.routes import agent as agent_routes
from shared.schemas import AgentAskRequest


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _User:
    id: Any = None
    role: str = "viewer"
    is_active: bool = True

    def __post_init__(self):
        if self.id is None:
            self.id = uuid.uuid4()


@dataclass
class _Provider:
    id: Any = None
    name: str = "anthropic"
    kind: str = "anthropic"
    active: bool = True
    default_model: str = "claude-sonnet-4"
    api_key: str | None = "k"
    base_url: str | None = "https://example"

    def __post_init__(self):
        if self.id is None:
            self.id = uuid.uuid4()


def _db_with(get_map: dict | None = None, execute_rows: list | None = None):
    """AsyncSession stub. ``get_map`` maps row id -> row for ``db.get``.
    ``execute_rows`` feeds the .scalars().all() output of one execute()
    call. Multiple execute() calls return empty unless set explicitly
    via a list-of-lists."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def _get(model, key):
        if isinstance(get_map, dict):
            return get_map.get(key)
        return None

    db.get.side_effect = _get

    # Build a sequence of execute outputs.
    if execute_rows is None:
        outputs = [[]]
    elif execute_rows and isinstance(execute_rows[0], list):
        outputs = execute_rows
    else:
        outputs = [execute_rows]

    call_idx = {"i": 0}

    async def _execute(stmt):
        i = call_idx["i"]
        call_idx["i"] += 1
        rows = outputs[i] if i < len(outputs) else []
        scalar_result = MagicMock()
        scalar_result.all.return_value = rows
        scalar_result.first.return_value = rows[0] if rows else None
        result = MagicMock()
        result.scalars.return_value = scalar_result
        result.scalar_one_or_none.return_value = rows[0] if rows else None
        return result

    db.execute = _execute
    return db


def _patch_create_task(monkeypatch):
    """Swallow asyncio.create_task so the background driver does not
    actually launch during tests."""
    created: list[Any] = []

    def _fake(coro, *a, **kw):
        # close the coroutine so it doesn't warn about un-awaited
        try:
            coro.close()
        except Exception:
            pass
        m = MagicMock()
        created.append(m)
        return m

    monkeypatch.setattr(agent_routes.asyncio, "create_task", _fake)
    return created


def _patch_create_run(monkeypatch):
    """Stub runs_mod.create_run so we don't hit a real DB session."""
    async def _create(**kwargs):
        row = MagicMock()
        row.id = uuid.uuid4()
        row.question = kwargs["question"]
        row.status = "running"
        row.user_id = kwargs["user_id"]
        return row

    monkeypatch.setattr(agent_routes.runs_mod, "create_run", _create)


class _BudgetOk:
    ok = True
    warn = False
    reason = ""
    token_budget = 100
    cost_budget_cents = 100
    used_tokens = 0
    used_cost_cents = 0
    remaining_tokens = 100
    remaining_cost_cents = 100


class _BudgetExhausted(_BudgetOk):
    ok = False
    reason = "out"


def _patch_check_budget(monkeypatch, status_obj):
    async def _check(*a, **kw):
        return status_obj
    monkeypatch.setattr(agent_routes, "check_budget", _check)


def _patch_get_setting(monkeypatch, **vals):
    async def _g(key, default=None):
        return vals.get(key, default)
    monkeypatch.setattr(agent_routes, "get_setting", _g)


# ── ask ─────────────────────────────────────────────────────────────


def test_ask_requires_provider_id(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetOk())
    _patch_get_setting(monkeypatch)
    db = _db_with()
    body = AgentAskRequest(question="q", provider_id=None)
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.ask(body=body, current_user=_User(), db=db))
    assert "provider_id" in str(excinfo.value)


def test_ask_rejects_non_tool_use_provider(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetOk())
    _patch_get_setting(monkeypatch)
    pid = uuid.uuid4()
    bad = _Provider(id=pid, kind="not_a_real_kind")
    db = _db_with(get_map={pid: bad})
    body = AgentAskRequest(question="q", provider_id=pid)
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.ask(body=body, current_user=_User(), db=db))
    assert "tool-use" in str(excinfo.value) or "does not support" in str(excinfo.value)


def test_ask_blocks_when_budget_exhausted(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetExhausted())
    _patch_get_setting(monkeypatch)
    pid = uuid.uuid4()
    p = _Provider(id=pid)
    db = _db_with(get_map={pid: p})
    body = AgentAskRequest(question="q", provider_id=pid)
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.ask(body=body, current_user=_User(), db=db))
    assert "budget" in str(excinfo.value).lower()


def test_ask_dry_run_returns_synthetic_run_id_without_starting_driver(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetOk())
    _patch_get_setting(monkeypatch)
    created = _patch_create_task(monkeypatch)
    pid = uuid.uuid4()
    p = _Provider(id=pid)
    db = _db_with(get_map={pid: p}, execute_rows=[[]])
    body = AgentAskRequest(question="q", provider_id=pid, dry_run=True)
    resp = _run(agent_routes.ask(body=body, current_user=_User(), db=db))
    assert resp.run_id is not None
    assert resp.ws_url.startswith("/ws/agent/")
    assert created == []  # no background task spawned


def test_ask_starts_driver_and_returns_run(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetOk())
    _patch_get_setting(monkeypatch)
    _patch_create_run(monkeypatch)
    created = _patch_create_task(monkeypatch)
    pid = uuid.uuid4()
    p = _Provider(id=pid)
    db = _db_with(get_map={pid: p}, execute_rows=[[]])  # no in-flight dupes
    body = AgentAskRequest(question="hello", provider_id=pid)
    resp = _run(agent_routes.ask(body=body, current_user=_User(), db=db))
    assert resp.run_id is not None
    assert resp.ws_url == f"/ws/agent/{resp.run_id}"
    assert len(created) == 1


# ── get run detail ──────────────────────────────────────────────────


def test_get_run_detail_forbids_non_owner_non_admin(monkeypatch):
    owner = _User()
    other = _User(role="viewer")
    run = MagicMock()
    run.id = uuid.uuid4()
    run.user_id = owner.id
    run.status = "completed"
    run.plan = None
    db = _db_with(get_map={run.id: run})
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.get_run_detail(run_id=run.id, current_user=other, db=db))
    assert "403" in str(excinfo.value) or "not your run" in str(excinfo.value)


def test_get_run_detail_404_when_missing(monkeypatch):
    user = _User()
    db = _db_with(get_map={})
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.get_run_detail(run_id=uuid.uuid4(), current_user=user, db=db))
    assert "404" in str(excinfo.value) or "not found" in str(excinfo.value)


# ── list_runs ───────────────────────────────────────────────────────


def test_list_runs_user_id_query_only_for_admins(monkeypatch):
    viewer = _User(role="viewer")
    db = _db_with(execute_rows=[[]])
    other = uuid.uuid4()
    with pytest.raises(Exception) as excinfo:
        _run(agent_routes.list_runs(limit=10, before=None, user_id=other,
                                     current_user=viewer, db=db))
    assert "admin" in str(excinfo.value).lower() or "403" in str(excinfo.value)


# ── usage/today ─────────────────────────────────────────────────────


def test_usage_today_shape(monkeypatch):
    _patch_check_budget(monkeypatch, _BudgetOk())
    user = _User()
    db = _db_with(execute_rows=[[]])
    out = _run(agent_routes.usage_today(current_user=user, db=db))
    assert "token_budget" in out
    assert "remaining_cost_cents" in out
    assert "percent_used" in out


# ── providers list ──────────────────────────────────────────────────


def test_list_agent_providers_filters_to_tool_use_kinds(monkeypatch):
    p_anthropic = _Provider(kind="anthropic", default_model="claude-sonnet-4")
    p_weird = _Provider(kind="some-non-llm")
    db = _db_with(execute_rows=[[p_anthropic, p_weird]])
    out = _run(agent_routes.list_agent_providers(_current_user=_User(), db=db))
    assert len(out) == 1
    assert out[0]["kind"] == "anthropic"
    assert out[0]["models"][0]["recommended"] is True


# ── ws replay test (sanity) ─────────────────────────────────────────


def test_publish_and_replay_roundtrip(monkeypatch):
    from services.agent import ws as ws_mod
    ws_mod._reset_for_tests()
    rid = str(uuid.uuid4())

    async def go():
        await ws_mod.publish_event(rid, {"type": "started", "seq": 1, "run_id": rid})
        await ws_mod.publish_event(rid, {"type": "tool_start", "seq": 2})
        backlog = await ws_mod.replay_after(rid, after_seq=1)
        return backlog

    backlog = _run(go())
    assert len(backlog) == 1
    assert backlog[0]["seq"] == 2
