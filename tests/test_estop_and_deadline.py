"""Wall-clock deadline and the household pause (issue #139).

Budgets covered turns, tokens, cost and VLM calls, but not time: twelve
turns against a wedged provider at a 120s HTTP timeout could hold a live
WS channel for roughly twenty-four minutes. And there was a per-run stop
with nothing above it, so a runaway could only be stopped by restarting
the API, which drops every unrelated in-flight request too.
"""

import json
import os
import uuid

import pytest

from shared import estop


@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    path = tmp_path / "ESTOP"
    monkeypatch.setenv(estop.ESTOP_PATH_ENV, str(path))
    return path


# ---- the pause -----------------------------------------------------------


def test_engage_and_disengage_round_trip(sentinel):
    assert estop.is_engaged() is False

    estop.engage("runaway rule")
    assert estop.is_engaged() is True
    assert estop.reason() == "runaway rule"

    estop.disengage()
    assert estop.is_engaged() is False
    assert estop.reason() is None


def test_a_bare_touch_still_counts_as_engaged(sentinel):
    """Someone typing touch on the path wanted things stopped. Failing
    open because there was no JSON would be the worst possible reading."""
    sentinel.write_text("")

    assert estop.is_engaged() is True
    assert estop.reason() is None


def test_a_corrupt_sentinel_still_counts_as_engaged(sentinel):
    sentinel.write_text("{not json at all")
    assert estop.is_engaged() is True


def test_a_sentinel_without_a_reason_is_fine(sentinel):
    sentinel.write_text(json.dumps({"engaged_at": "2026-08-24T00:00:00Z"}))
    assert estop.is_engaged() is True
    assert estop.reason() is None


def test_engage_is_idempotent(sentinel):
    estop.engage("one")
    estop.engage("two")
    assert estop.reason() == "two"


def test_disengage_on_an_absent_sentinel_is_not_an_error(sentinel):
    estop.disengage()
    estop.disengage()
    assert estop.is_engaged() is False


def test_the_body_records_when_it_was_engaged(sentinel):
    estop.engage("why")
    body = json.loads(sentinel.read_text())
    assert body["reason"] == "why"
    assert body["engaged_at"]


def test_the_path_is_overridable(sentinel, tmp_path, monkeypatch):
    other = tmp_path / "elsewhere" / "ESTOP"
    monkeypatch.setenv(estop.ESTOP_PATH_ENV, str(other))
    estop.engage("here")
    assert other.exists()
    assert not sentinel.exists()


# ---- driver behaviour ----------------------------------------------------


from tests.test_agent_driver import (  # noqa: E402
    _BudgetOk,
    _FakeProvider,
    _FakeRunRow,
    _FakeUser,
    _fake_db_session,
    _patch_budget,
    _patch_get_setting,
    _patch_runs,
    _run,
)
from services.agent import driver as driver_mod  # noqa: E402
from services.agent.llm import LLMResponse  # noqa: E402


def _drive(monkeypatch, llm=None, settings=None):
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 20)
    _patch_get_setting(monkeypatch, **(settings or {}))

    async def _default(**kwargs):
        return LLMResponse(stop_reason="end_turn", text="Answered.", tool_uses=[])

    monkeypatch.setattr(driver_mod, "llm_call", llm or _default)

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    drv = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
    _run(drv.run(run_id=uuid.uuid4(), user=_FakeUser(), question="q",
                 provider=_FakeProvider(), model="m", parent_run_id=None))
    return events, run_row


def test_a_paused_household_refuses_to_start_a_run(monkeypatch, sentinel):
    estop.engage("maintenance")
    events, run_row = _drive(monkeypatch)

    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["failure_kind"] == "paused"
    assert "maintenance" in errors[0]["message"]
    assert run_row.status == "cancelled"


def test_an_unpaused_household_runs_normally(monkeypatch, sentinel):
    events, run_row = _drive(monkeypatch)
    assert run_row.status == "completed"
    assert not [e for e in events if e.get("failure_kind") == "paused"]


def test_a_run_past_its_deadline_answers_with_what_it_has(monkeypatch, sentinel):
    """Rather than holding the channel open for another eleven turns."""
    calls = {"n": 0}

    async def _slow(**kwargs):
        calls["n"] += 1
        return LLMResponse(stop_reason="end_turn", text="Answered.", tool_uses=[])

    events, run_row = _drive(
        monkeypatch, llm=_slow, settings={"agent_max_run_seconds": 0},
    )

    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["failure_kind"] == "deadline"
    # The provider was never asked for a turn; the deadline fired first.
    assert calls["n"] == 1  # only the forced synthesis
    assert run_row.status == "completed"

    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["partial"] is True


def test_the_deadline_default_is_sane():
    """Long enough for a real investigation, short enough that a wedged
    provider cannot hold a live channel for twenty minutes."""
    assert 60 <= driver_mod.DEFAULT_MAX_RUN_SECONDS <= 900


def test_the_pause_is_checked_before_any_budget_work(monkeypatch, sentinel):
    """A paused household should not even be billed for a budget lookup
    round-trip, and more importantly should not start."""
    estop.engage("stop")

    called = {"budget": 0}

    async def _check(user_id, db):
        called["budget"] += 1
        return _BudgetOk()

    monkeypatch.setattr(driver_mod, "check_budget", _check)
    _drive(monkeypatch)

    assert called["budget"] == 0
