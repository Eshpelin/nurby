"""Tests for services.agent.driver.

The driver is exercised via a fully stubbed LLM (monkeypatched
``llm_call`` from services.agent.driver) and stubbed db/run/budget
helpers. The goal is to assert the loop control flow, the WS event
sequence, the tool-loop dedupe, the budget-mid-loop abort path, and the
max-turns forced-synthesis path.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent import driver as driver_mod
from services.agent.llm import LLMResponse, LLMToolUse


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_db_lookups(monkeypatch):
    """The orientation block and the escalation lookup both run real queries
    against the stub db. Tests that care about either patch it themselves
    (see the injection and escalation tests)."""
    async def _no_context(self, user, db):
        return None

    async def _no_escalation(self, db, current):
        return None

    monkeypatch.setattr(driver_mod.AgentDriver, "_household_context", _no_context)
    monkeypatch.setattr(driver_mod.AgentDriver, "_stronger_provider", _no_escalation)


# ── Fakes ──────────────────────────────────────────────────────────


@dataclass
class _FakeProvider:
    kind: str = "anthropic"
    api_key: str | None = "k"
    base_url: str | None = "https://example"
    default_model: str | None = "claude-sonnet-4"
    id: Any = None

    def __post_init__(self):
        if self.id is None:
            self.id = uuid.uuid4()


@dataclass
class _FakeUser:
    id: Any = None
    role: str = "viewer"
    is_active: bool = True

    def __post_init__(self):
        if self.id is None:
            self.id = uuid.uuid4()


class _FakeRunRow:
    def __init__(self):
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_cents = 0
        self.turns_used = 0
        self.status = "running"
        self.final_answer = None
        self.error_message = None
        self.ended_at = None
        self.latency_ms = None
        self.plan = None


def _fake_db_session(run_row: _FakeRunRow):
    """An async-context-manager that yields a stub db with .get(AgentRun)
    returning the same run_row each time. ``add``/``commit``/``refresh``
    are no-ops."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=run_row)
    db.execute = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield db

    return factory, db


def _patch_runs(monkeypatch, run_row):
    """Wire services.agent.runs functions used by the driver to act on
    the in-memory ``run_row`` so we don't need a real DB."""

    async def _update_run(run_id, db, **patch):
        for k, v in patch.items():
            setattr(run_row, k, v)
        return run_row

    async def _append_tool_call(run_id, turn_index, tool_name, arguments, db):
        row = MagicMock()
        row.id = uuid.uuid4()
        row.turn_index = turn_index
        row.tool_name = tool_name
        return row

    async def _complete_tool_call(call_id, db, **kw):
        return None

    async def _cancel_run(run_id, reason, db):
        run_row.status = "cancelled"
        run_row.error_message = reason
        return run_row

    monkeypatch.setattr(driver_mod.runs_mod, "update_run", _update_run)
    monkeypatch.setattr(driver_mod.runs_mod, "append_tool_call", _append_tool_call)
    monkeypatch.setattr(driver_mod.runs_mod, "complete_tool_call", _complete_tool_call)
    monkeypatch.setattr(driver_mod.runs_mod, "cancel_run", _cancel_run)


class _BudgetOk:
    ok = True
    warn = False
    reason = ""
    remaining_tokens = 999_999
    remaining_cost_cents = 999_999
    used_tokens = 0
    used_cost_cents = 0
    token_budget = 1_000_000
    cost_budget_cents = 1_000_000


class _BudgetExhausted:
    ok = False
    warn = True
    reason = "out of cents"
    remaining_tokens = 0
    remaining_cost_cents = 0
    used_tokens = 1_000_000
    used_cost_cents = 1_000_000
    token_budget = 1_000_000
    cost_budget_cents = 1_000_000


def _patch_budget(monkeypatch, statuses):
    """Each call to check_budget returns the next status in the list."""
    it = iter(statuses)
    fallback = statuses[-1]

    async def _check(user_id, db):
        try:
            return next(it)
        except StopIteration:
            return fallback

    async def _record(*a, **kw):
        return None

    monkeypatch.setattr(driver_mod, "check_budget", _check)
    monkeypatch.setattr(driver_mod, "record_usage", _record)
    monkeypatch.setattr(driver_mod, "estimate_cost", lambda *a, **kw: 1)


def _patch_get_setting(monkeypatch, **vals):
    base = {
        "agent_max_turns_per_run": 12,
        "agent_max_vlm_calls_per_run": 8,
        "system_timezone": "UTC",
    }
    base.update(vals)

    async def _get_setting(key, default=None):
        return base.get(key, default)

    monkeypatch.setattr(driver_mod, "get_setting", _get_setting)


def _scripted_llm(monkeypatch, scripted: list[LLMResponse]):
    """Return successive LLMResponse objects on each llm_call invocation."""
    it = iter(scripted)

    async def _llm_call(**kwargs):
        try:
            resp = next(it)
        except StopIteration:
            resp = LLMResponse(stop_reason="end_turn", text="ran out of script", tool_uses=[])
        cb = kwargs.get("stream_callback")
        if cb and resp.text:
            await cb(resp.text)
        return resp

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)


# ── Tests ──────────────────────────────────────────────────────────


def test_driver_runs_one_tool_then_finishes(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk(), _BudgetOk(), _BudgetOk()])
    _patch_get_setting(monkeypatch)

    # First call: emit one tool_use; second call: end_turn with final text.
    tool_use = LLMToolUse(id="t1", name="query_observations",
                          arguments={"query": "cat", "hours": 24})
    _scripted_llm(monkeypatch, [
        LLMResponse(stop_reason="tool_use", text="<plan>look for cat</plan>",
                    tool_uses=[tool_use], tokens_in=100, tokens_out=20),
        LLMResponse(stop_reason="end_turn", text="No cat sightings.",
                    tool_uses=[], tokens_in=50, tokens_out=10),
    ])

    # Tool function shim that does not touch the DB.
    async def _fake_query_observations(ctx, **kw):
        return {"count": 0, "observations": []}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake_query_observations
    try:
        events: list[dict] = []

        async def _broadcast(rid, ev):
            events.append(ev)

        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id,
            user=_FakeUser(),
            question="did the cat go out?",
            provider=_FakeProvider(kind="anthropic"),
            model="claude-sonnet-4",
            parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original

    types = [e["type"] for e in events]
    assert types[0] == "started"
    assert "tool_start" in types
    assert "tool_result" in types
    assert types[-1] == "done"
    done = events[-1]
    assert done["final_answer"] == "No cat sightings."
    assert done["partial"] is False
    assert run_row.status == "completed"
    assert run_row.final_answer == "No cat sightings."


def test_driver_dedupes_repeated_tool_calls(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 10)
    _patch_get_setting(monkeypatch)

    same = LLMToolUse(id="t1", name="query_observations",
                      arguments={"query": "cat", "hours": 24})
    same2 = LLMToolUse(id="t2", name="query_observations",
                       arguments={"query": "cat", "hours": 24})
    _scripted_llm(monkeypatch, [
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[same]),
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[same2]),
        LLMResponse(stop_reason="end_turn", text="done", tool_uses=[]),
    ])

    async def _fake(ctx, **kw):
        return {"count": 0, "observations": []}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    try:
        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id, user=_FakeUser(),
            question="q", provider=_FakeProvider(), model="claude-sonnet-4",
            parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original

    # find the second tool_result. it should be the dedupe sentinel.
    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) >= 2
    assert "tool_loop_detected" in tool_results[1].get("result_summary", "")


def test_driver_budget_exhausted_mid_loop_triggers_forced_synthesis(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    # first check_budget ok (pre-flight), second still ok (after first call check)
    # third returns exhausted to trigger forced synthesis.
    _patch_budget(monkeypatch, [_BudgetOk(), _BudgetExhausted()])
    _patch_get_setting(monkeypatch)

    tu = LLMToolUse(id="t1", name="query_observations",
                    arguments={"query": "x", "hours": 1})
    _scripted_llm(monkeypatch, [
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[tu],
                    tokens_in=10, tokens_out=5),
        # forced synthesis call:
        LLMResponse(stop_reason="end_turn", text="partial answer", tool_uses=[]),
    ])

    async def _fake(ctx, **kw):
        return {"count": 0, "observations": []}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    try:
        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id, user=_FakeUser(),
            question="q", provider=_FakeProvider(), model="claude-sonnet-4",
            parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original

    types = [e["type"] for e in events]
    assert "budget_warn" in types
    assert types[-1] == "done"
    assert events[-1]["partial"] is True
    assert run_row.status == "budget_exhausted"


def test_driver_respects_max_turns_cap(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 50)
    _patch_get_setting(monkeypatch, agent_max_turns_per_run=2)

    # Always return a new tool_use so the loop never naturally ends.
    def _make_tu(i):
        return LLMToolUse(id=f"t{i}", name="query_observations",
                          arguments={"query": f"x{i}", "hours": 1})

    scripted = [
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[_make_tu(0)]),
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[_make_tu(1)]),
        # forced synthesis
        LLMResponse(stop_reason="end_turn", text="partial summary", tool_uses=[]),
    ]
    _scripted_llm(monkeypatch, scripted)

    async def _fake(ctx, **kw):
        return {"count": 0, "observations": []}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    try:
        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id, user=_FakeUser(),
            question="q", provider=_FakeProvider(), model="claude-sonnet-4",
            parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original

    types = [e["type"] for e in events]
    # max_turns surfaces as an error then done w/ partial=True.
    assert any(e.get("message") == "max_turns_reached" for e in events if e["type"] == "error")
    assert types[-1] == "done"
    assert events[-1]["partial"] is True


def test_ws_replay_returns_buffered_events_after_seq(monkeypatch):
    from services.agent import ws as ws_mod

    ws_mod._reset_for_tests()
    rid = "abc"

    async def go():
        await ws_mod.publish_event(rid, {"type": "started", "seq": 1})
        await ws_mod.publish_event(rid, {"type": "tool_start", "seq": 2})
        await ws_mod.publish_event(rid, {"type": "tool_result", "seq": 3})
        backlog = await ws_mod.replay_after(rid, after_seq=1)
        return backlog

    backlog = _run(go())
    assert [e["seq"] for e in backlog] == [2, 3]


def test_summarize_prior_evidence_returns_lines(monkeypatch):
    """Parent-context evidence preamble surfaces the prior run's tool calls."""

def test_format_evidence_preamble_renders_tool_calls():
    """Parent-context evidence preamble surfaces the prior run's tool calls."""
    from types import SimpleNamespace

    from services.agent.driver import _format_evidence_preamble

    rows_newest_first = [
        SimpleNamespace(
            tool_name="query_observations",
            arguments={"query": "cat", "hours": 24},
            result={"count": 0, "observations": []},
        ),
        SimpleNamespace(
            tool_name="get_household_snapshot",
            arguments={},
            result={"cameras": [1, 2, 3, 4]},
        ),
    ]
    out = _format_evidence_preamble(rows_newest_first)
    assert "Prior evidence I gathered:" in out
    assert "get_household_snapshot" in out
    assert "query_observations" in out
    # Output is oldest-first (input is newest-first; the formatter reverses).
    assert out.index("get_household_snapshot") < out.index("query_observations")


def test_format_evidence_preamble_empty_when_no_rows():
    from services.agent.driver import _format_evidence_preamble
    assert _format_evidence_preamble([]) == ""


# ── Citation verification (G4, issue #128) ─────────────────────────


OBS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OBS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_collect_ids_finds_uuids_at_any_depth():
    payload = {"observations": [{"id": OBS_A, "nested": {"journey_id": OBS_B}}]}
    assert driver_mod.collect_ids(payload) == {OBS_A, OBS_B}


def test_collect_ids_is_case_insensitive():
    assert driver_mod.collect_ids({"id": OBS_A.upper()}) == {OBS_A}


def test_collect_ids_survives_unserializable_payloads():
    assert driver_mod.collect_ids({"obj": object(), "id": OBS_A}) == {OBS_A}


def test_verify_citations_keeps_ids_a_tool_returned():
    text = f"The van arrived [obs:{OBS_A}]."
    cleaned, removed = driver_mod.verify_citations(text, {OBS_A})
    assert cleaned == text
    assert removed == []


def test_verify_citations_strips_invented_ids():
    text = f"The van arrived [obs:{OBS_A}] and left again [obs:{OBS_B}]."
    cleaned, removed = driver_mod.verify_citations(text, {OBS_A})
    assert f"[obs:{OBS_A}]" in cleaned
    assert OBS_B not in cleaned
    # The claim survives; only the fake evidence marker goes.
    assert "left again" in cleaned
    assert removed == [f"obs:{OBS_B}"]


def test_verify_citations_covers_every_citation_kind():
    text = (
        f"a [journey:{OBS_B}] b [vlm:{OBS_B}] c [recording:{OBS_B}] d [obs:{OBS_B}]"
    )
    cleaned, removed = driver_mod.verify_citations(text, set())
    assert OBS_B not in cleaned
    assert [r.split(":")[0] for r in removed] == ["journey", "vlm", "recording", "obs"]


def test_verify_citations_tidies_the_space_it_leaves():
    text = f"The van arrived [obs:{OBS_B}] , then left ."
    cleaned, _ = driver_mod.verify_citations(text, set())
    assert cleaned == "The van arrived, then left."


def test_verify_citations_on_empty_text_is_a_noop():
    assert driver_mod.verify_citations("", {OBS_A}) == ("", [])


def test_driver_strips_citations_the_tools_never_returned(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk(), _BudgetOk(), _BudgetOk()])
    _patch_get_setting(monkeypatch)

    tool_use = LLMToolUse(id="t1", name="query_observations",
                          arguments={"query": "van", "hours": 24})
    _scripted_llm(monkeypatch, [
        LLMResponse(stop_reason="tool_use", text="", tool_uses=[tool_use],
                    tokens_in=100, tokens_out=20),
        LLMResponse(
            stop_reason="end_turn",
            # One real citation, one the model made up.
            text=f"A van arrived [obs:{OBS_A}] and a second one followed [obs:{OBS_B}].",
            tool_uses=[], tokens_in=50, tokens_out=10,
        ),
    ])

    async def _fake_query_observations(ctx, **kw):
        return {"count": 1, "observations": [{"id": OBS_A, "description": "a van"}]}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake_query_observations
    try:
        events: list[dict] = []

        async def _broadcast(rid, ev):
            events.append(ev)

        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id,
            user=_FakeUser(),
            question="how many vans?",
            provider=_FakeProvider(kind="anthropic"),
            model="claude-sonnet-4",
            parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original

    done = events[-1]
    assert done["type"] == "done"
    assert OBS_A in done["final_answer"]
    assert OBS_B not in done["final_answer"]
    # Stored answer matches what the user is shown.
    assert run_row.final_answer == done["final_answer"]
    # The strip is auditable, not silent.
    stripped = [e for e in events if e["type"] == "citations_stripped"]
    assert stripped and stripped[0]["count"] == 1
    assert stripped[0]["citations"] == [f"obs:{OBS_B}"]
    # And the surviving citation is still reported on the done event.
    assert done["citations"] == [{"kind": "obs", "id": OBS_A}]


# ── household orientation block (G5, issue #131) ───────────────────


def test_driver_injects_the_household_block_into_the_system_prompt(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk(), _BudgetOk()])
    _patch_get_setting(monkeypatch)

    async def _block(self, user, db):
        return "ABOUT THIS HOUSEHOLD: two cameras, one cat."

    monkeypatch.setattr(driver_mod.AgentDriver, "_household_context", _block)

    seen = {}

    async def _llm_call(**kwargs):
        seen["system_prompt"] = kwargs.get("system_prompt")
        return LLMResponse(stop_reason="end_turn", text="Nothing to report.",
                           tool_uses=[], tokens_in=10, tokens_out=5)

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    driver = driver_mod.AgentDriver(db_factory=factory, broadcast=None)
    _run(driver.run(
        run_id=run_id,
        user=_FakeUser(),
        question="anything happening?",
        provider=_FakeProvider(kind="anthropic"),
        model="claude-sonnet-4",
        parent_run_id=None,
    ))

    assert "ABOUT THIS HOUSEHOLD: two cameras, one cat." in seen["system_prompt"]
    # The block is appended after .format(), so braces in entity names cannot
    # break the template.
    assert "You are Nurby Agent" in seen["system_prompt"]


def test_driver_runs_fine_without_a_household_block(monkeypatch):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk(), _BudgetOk()])
    _patch_get_setting(monkeypatch)
    _scripted_llm(monkeypatch, [
        LLMResponse(stop_reason="end_turn", text="All quiet.", tool_uses=[]),
    ])

    driver = driver_mod.AgentDriver(db_factory=factory, broadcast=None)
    _run(driver.run(
        run_id=run_id,
        user=_FakeUser(),
        question="anything happening?",
        provider=_FakeProvider(kind="anthropic"),
        model="claude-sonnet-4",
        parent_run_id=None,
    ))
    assert run_row.final_answer == "All quiet."


# ── mid-run model escalation (G6, issue #132) ──────────────────────


def _escalation_run(monkeypatch, *, exhaust_budget: bool, stronger):
    """Drive the loop to a forced synthesis and report what it called with."""
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    if exhaust_budget:
        _patch_budget(monkeypatch, [_BudgetOk(), _BudgetExhausted()])
    else:
        _patch_budget(monkeypatch, [_BudgetOk()] * 50)
    _patch_get_setting(monkeypatch, agent_max_turns_per_run=1)

    async def _stronger(self, db_, current):
        return stronger

    monkeypatch.setattr(driver_mod.AgentDriver, "_stronger_provider", _stronger)

    used: list[tuple] = []

    async def _llm_call(**kwargs):
        used.append((kwargs.get("provider"), kwargs.get("model")))
        if len(used) == 1:
            return LLMResponse(
                stop_reason="tool_use", text="",
                tool_uses=[LLMToolUse(id="t0", name="query_observations",
                                      arguments={"query": "x", "hours": 1})],
            )
        return LLMResponse(stop_reason="end_turn", text="partial summary", tool_uses=[])

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    async def _fake(ctx, **kw):
        return {"count": 0, "observations": []}

    import services.agent.tools as tools_mod
    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _fake

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    try:
        driver = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(driver.run(
            run_id=run_id, user=_FakeUser(), question="q",
            provider=_FakeProvider(kind="ollama", default_model="gemma3:4b"),
            model="gemma3:4b", parent_run_id=None,
        ))
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original
    return used, events


def test_max_turns_synthesis_escalates_to_a_stronger_model(monkeypatch):
    strong = _FakeProvider(kind="anthropic", default_model="claude-sonnet-4")
    used, events = _escalation_run(monkeypatch, exhaust_budget=False, stronger=strong)

    # Loop ran on the weak model; the final synthesis ran on the strong one.
    assert used[0][1] == "gemma3:4b"
    assert used[-1] == (strong, "claude-sonnet-4")
    escalated = [e for e in events if e["type"] == "model_escalated"]
    assert escalated and escalated[0]["reason"] == "max_turns_reached"
    assert escalated[0]["from"] == "ollama/gemma3:4b"
    assert escalated[0]["to"] == "anthropic/claude-sonnet-4"


def test_max_turns_synthesis_stays_put_when_nothing_is_stronger(monkeypatch):
    used, events = _escalation_run(monkeypatch, exhaust_budget=False, stronger=None)
    assert used[-1][1] == "gemma3:4b"
    assert not [e for e in events if e["type"] == "model_escalated"]


def test_budget_exhaustion_never_escalates(monkeypatch):
    """Out of money is not a quality signal, and a pricier model is the last
    thing that situation needs."""
    strong = _FakeProvider(kind="anthropic", default_model="claude-sonnet-4")
    used, events = _escalation_run(monkeypatch, exhaust_budget=True, stronger=strong)
    assert all(model == "gemma3:4b" for _, model in used)
    assert not [e for e in events if e["type"] == "model_escalated"]
