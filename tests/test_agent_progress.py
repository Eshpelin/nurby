"""Loop guard and progress metric (issue #138).

The old guard hashed exact arguments over a two-turn window, so it caught
literal repetition and nothing else. And nothing measured whether a run
was actually learning anything: twelve turns of distinct, valid,
uninformative calls looked exactly like twelve turns of good work until
the turn cap fired.
"""

import uuid

from services.agent.progress import (
    HALT_AFTER_TURNS,
    NUDGE_AFTER_TURNS,
    WINDOW_RUNGS,
    call_signature,
    made_progress,
    normalize_args,
    nudge_text,
    verdict,
)


# ---- normalized signatures -----------------------------------------------


def test_numeric_noise_collides():
    """The gap the old exact hash left open."""
    assert call_signature("q", {"hours": 24}) == call_signature("q", {"hours": 25})


def test_the_widen_ladder_stays_distinct():
    """The system prompt tells the model to escalate 24 -> 168 -> 720 when
    a query comes back empty. Collapsing those would block the strategy
    the prompt depends on, which is worse than the bug being fixed."""
    a = call_signature("q", {"hours": 24})
    b = call_signature("q", {"hours": 168})
    c = call_signature("q", {"hours": 720})
    assert len({a, b, c}) == 3


def test_every_ladder_rung_maps_to_itself():
    for rung in WINDOW_RUNGS:
        assert normalize_args({"hours": rung})["hours"] == rung


def test_limits_collide_at_noise_but_not_at_scale():
    assert call_signature("q", {"limit": 20}) == call_signature("q", {"limit": 21})
    assert call_signature("q", {"limit": 20}) != call_signature("q", {"limit": 100})


def test_different_tools_never_collide():
    assert call_signature("a", {"hours": 24}) != call_signature("b", {"hours": 24})


def test_strings_are_case_and_space_insensitive():
    assert call_signature("q", {"query": " Cat "}) == call_signature("q", {"query": "cat"})


def test_meaningfully_different_strings_do_not_collide():
    assert call_signature("q", {"query": "cat"}) != call_signature("q", {"query": "dog"})


def test_argument_order_does_not_matter():
    assert call_signature("q", {"a": 1, "b": 2}) == call_signature("q", {"b": 2, "a": 1})


def test_booleans_and_none_survive_intact():
    out = normalize_args({"flag": True, "other": None})
    assert out == {"flag": True, "other": None}


def test_nested_structures_are_normalized():
    a = normalize_args({"filter": {"hours": 24}, "ids": ["A", "B"]})
    b = normalize_args({"filter": {"hours": 25}, "ids": ["a", "b"]})
    assert a == b


def test_empty_args_are_stable():
    assert call_signature("q", None) == call_signature("q", {})


# ---- the progress metric -------------------------------------------------


def test_new_evidence_is_progress():
    assert made_progress(3, 7, {"query_observations"}, {"query_observations"}) is True


def test_no_new_evidence_is_not_progress():
    assert made_progress(7, 7, {"query_observations"}, {"query_observations"}) is False


def test_a_first_call_to_a_tool_counts_even_with_no_ids():
    """Several useful tools return no ids at all: the camera layout, the
    rule list, the doctor. Judging those as spinning would nag a run that
    is doing the right thing."""
    assert made_progress(5, 5, {"get_camera_layout"}, {"query_observations"}) is True


def test_repeating_a_known_tool_with_nothing_new_is_not_progress():
    assert made_progress(5, 5, {"get_camera_layout"},
                         {"get_camera_layout", "query_observations"}) is False


# ---- escalation ----------------------------------------------------------


def test_one_quiet_turn_is_tolerated():
    """A turn can legitimately confirm an absence."""
    assert verdict(1) == "ok"


def test_two_quiet_turns_earn_a_nudge():
    assert verdict(NUDGE_AFTER_TURNS) == "nudge"


def test_three_quiet_turns_halt_the_run():
    assert verdict(HALT_AFTER_TURNS) == "halt"
    assert verdict(HALT_AFTER_TURNS + 5) == "halt"


def test_the_nudge_offers_both_ways_out():
    """Change approach or answer with what you have. Telling a model only
    to try harder is how a run burns its remaining turns."""
    text = nudge_text(2)
    assert "widen the time window" in text
    assert "answer now" in text


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
from services.agent.llm import LLMResponse, LLMToolUse  # noqa: E402
import services.agent.tools as tools_mod  # noqa: E402


def _tool_turn(i):
    return LLMResponse(
        stop_reason="tool_use",
        text="",
        tool_uses=[LLMToolUse(id=f"t{i}", name="query_observations",
                              arguments={"query": f"cat{i}", "hours": 24})],
        tokens_in=10, tokens_out=5,
    )


def _drive_with_empty_results(monkeypatch, turns=6):
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 20)
    _patch_get_setting(monkeypatch)

    scripted = [_tool_turn(i) for i in range(turns)]
    it = iter(scripted)

    async def _llm_call(**kwargs):
        try:
            return next(it)
        except StopIteration:
            return LLMResponse(stop_reason="end_turn", text="Nothing found.",
                               tool_uses=[])

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    # Every call returns rows with no ids: valid, distinct, uninformative.
    async def _empty(ctx, **kw):
        return {"count": 0, "observations": []}

    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _empty
    try:
        events: list[dict] = []

        async def _broadcast(rid, ev):
            events.append(ev)

        drv = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
        _run(drv.run(run_id=uuid.uuid4(), user=_FakeUser(), question="where is the cat?",
                     provider=_FakeProvider(), model="m", parent_run_id=None))
        return events, run_row
    finally:
        tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = original


def test_a_spinning_run_is_nudged_then_halted(monkeypatch):
    """The regression: distinct, valid, uninformative calls used to run
    all the way to the turn cap."""
    events, run_row = _drive_with_empty_results(monkeypatch, turns=6)

    signals = [e for e in events if e["type"] == "no_progress"]
    assert [s["action"] for s in signals] == ["nudge", "halt"]
    assert run_row.status == "completed"

    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["partial"] is True


def test_it_halts_well_before_the_turn_cap(monkeypatch):
    events, _ = _drive_with_empty_results(monkeypatch, turns=12)
    tool_starts = [e for e in events if e["type"] == "tool_start"]
    assert len(tool_starts) <= HALT_AFTER_TURNS + 1
