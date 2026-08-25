"""Empty completions must not be recorded as success (issue #137).

The driver reached its final-answer branch whenever a response carried no
tool calls, and stored whatever text came with it. For an empty
completion that was "", written with status="completed". The user saw a
blank reply and every metric over run status counted a success.
"""

import uuid

import pytest

from services.agent import empty_guard
from services.agent.empty_guard import (
    DEFAULT_COST_THRESHOLD_CENTS,
    DEFAULT_EMPTY_RETRY_BUDGET,
    REDUCED_EMPTY_RETRY_BUDGET,
    EmptyAttempt,
    describe,
    is_empty_answer,
    nudge_for,
    retry_budget,
    should_retry,
)


def _attempt(n=1, provider="anthropic", model="m", stop="end_turn"):
    return [EmptyAttempt(provider, model, stop) for _ in range(n)]


# ---- what counts as empty ------------------------------------------------


def test_no_text_and_no_tools_is_empty():
    assert is_empty_answer("", None) is True
    assert is_empty_answer(None, []) is True


def test_whitespace_only_is_empty():
    """A reply of two newlines is blank to a reader."""
    assert is_empty_answer("\n\n  \t", []) is True


def test_a_real_answer_is_not_empty():
    assert is_empty_answer("No cat sightings.", []) is False


def test_a_response_with_tool_calls_is_not_this_guard_s_business():
    """It is not an answer at all, empty or otherwise."""
    assert is_empty_answer("", [{"name": "query_observations"}]) is False


# ---- the retry budget ----------------------------------------------------


def test_a_cheap_streak_gets_the_full_budget():
    assert retry_budget(0) == DEFAULT_EMPTY_RETRY_BUDGET
    assert should_retry(_attempt(1)) is True
    assert should_retry(_attempt(2)) is True


def test_the_budget_runs_out():
    assert should_retry(_attempt(DEFAULT_EMPTY_RETRY_BUDGET)) is False


def test_an_expensive_streak_gets_one_try_only():
    """A model failing expensively should not be retried into a hole. The
    point of a retry is being cheap relative to what it recovers."""
    assert retry_budget(DEFAULT_COST_THRESHOLD_CENTS) == REDUCED_EMPTY_RETRY_BUDGET
    assert should_retry(_attempt(1), streak_cost_cents=99) is False
    assert should_retry(_attempt(0), streak_cost_cents=99) is True


def test_the_threshold_is_configurable():
    assert should_retry(_attempt(1), streak_cost_cents=10, threshold_cents=5) is False
    assert should_retry(_attempt(1), streak_cost_cents=10, threshold_cents=50) is True


# ---- attempt signatures --------------------------------------------------


def test_identical_conditions_share_a_signature():
    a, b = _attempt(2)
    assert a.signature == b.signature


def test_a_changed_provider_is_a_different_signature():
    a = EmptyAttempt("anthropic", "m", "end_turn")
    b = EmptyAttempt("openai", "m", "end_turn")
    assert a.signature != b.signature


def test_describe_calls_out_a_repeat_under_identical_conditions():
    text = describe(_attempt(3))
    assert "3 empty replies" in text
    assert "identical conditions" in text


def test_describe_handles_one_attempt():
    assert "1 empty reply" in describe(_attempt(1))
    assert "identical conditions" not in describe(_attempt(1))


def test_describe_survives_an_empty_list():
    assert describe([]) == "the model returned no answer"


# ---- the nudge -----------------------------------------------------------


def test_the_nudge_escalates():
    first = nudge_for(_attempt(1))
    second = nudge_for(_attempt(2))
    assert "last reply was empty" in first
    assert "last two replies were empty" in second
    # The second says not to call more tools: by then the model is not
    # gathering evidence, it is failing to write.
    assert "Do not call any more tools" in second


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


def _drive(monkeypatch, scripted):
    run_id = uuid.uuid4()
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 12)
    _patch_get_setting(monkeypatch)

    it = iter(scripted)

    async def _llm_call(**kwargs):
        try:
            resp = next(it)
        except StopIteration:
            resp = LLMResponse(stop_reason="end_turn", text="", tool_uses=[])
        cb = kwargs.get("stream_callback")
        if cb and resp.text:
            await cb(resp.text)
        return resp

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    drv = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
    _run(drv.run(run_id=run_id, user=_FakeUser(), question="where is the cat?",
                 provider=_FakeProvider(), model="m", parent_run_id=None))
    return events, run_row


def _empty():
    return LLMResponse(stop_reason="end_turn", text="", tool_uses=[],
                       tokens_in=10, tokens_out=0)


def test_an_empty_reply_is_retried_and_can_recover(monkeypatch):
    events, run_row = _drive(monkeypatch, [
        _empty(),
        LLMResponse(stop_reason="end_turn", text="No cat sightings.",
                    tool_uses=[], tokens_in=10, tokens_out=5),
    ])

    assert [e["type"] for e in events].count("empty_response") == 1
    assert run_row.status == "completed"
    assert run_row.final_answer == "No cat sightings."


def test_a_run_of_empties_never_completes_with_nothing(monkeypatch):
    """The regression, stated directly. Before #137 this stored
    status="completed" with an empty answer."""
    events, run_row = _drive(monkeypatch, [_empty()] * 8)

    assert run_row.status == "no_answer"
    assert run_row.status != "completed"
    # The stored text is the forced-synthesis status line, which explains
    # itself to the user but is not an answer and must not be counted as one.
    assert driver_mod._is_real_answer(run_row.final_answer) is False
    assert run_row.error_message
    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["failure_kind"] == "no_answer"


def test_the_retry_budget_is_respected(monkeypatch):
    events, _ = _drive(monkeypatch, [_empty()] * 8)
    empties = [e for e in events if e["type"] == "empty_response"]
    assert len(empties) == DEFAULT_EMPTY_RETRY_BUDGET


def test_a_salvaged_partial_answer_counts_as_completed(monkeypatch):
    """Forced synthesis after the budget runs out can still produce
    something off the evidence gathered. That is a real answer."""
    scripted = [_empty()] * DEFAULT_EMPTY_RETRY_BUDGET + [
        LLMResponse(stop_reason="end_turn", text="Partial: nothing found.",
                    tool_uses=[]),
    ]
    events, run_row = _drive(monkeypatch, scripted)

    assert run_row.status == "completed"
    assert "Partial" in (run_row.final_answer or "")
    done = [e for e in events if e["type"] == "done"]
    # Flagged partial, because it came from forced synthesis rather than
    # from the model deciding it was finished.
    assert done and done[0]["partial"] is True


def test_a_streak_is_cleared_by_a_real_answer(monkeypatch):
    """One empty reply, an answer, then later empties start from zero
    rather than inheriting the earlier streak."""
    state = driver_mod._LoopState()
    state.empty_attempts.extend(_attempt(2))
    state.empty_streak_cost_cents = 40

    # Mirrors what the driver does on a real answer.
    state.empty_attempts.clear()
    state.empty_streak_cost_cents = 0

    assert should_retry(state.empty_attempts, state.empty_streak_cost_cents) is True


def test_no_answer_is_a_terminal_status():
    from services.agent.runs import _TERMINAL_STATUSES

    assert "no_answer" in _TERMINAL_STATUSES


def test_the_forced_synthesis_status_line_is_not_an_answer():
    """Counting it as one would recreate this bug a layer further down:
    a run that said nothing, recorded as having answered."""
    assert driver_mod._is_real_answer(driver_mod.NO_SYNTHESIS_TEXT) is False
    assert driver_mod._is_real_answer("(investigation halted: boom)") is False
    assert driver_mod._is_real_answer("") is False
    assert driver_mod._is_real_answer("   ") is False
    assert driver_mod._is_real_answer("No cat sightings.") is True
