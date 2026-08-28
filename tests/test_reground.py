"""Re-grounding stripped citations (issue #142).

The driver strips citations pointing at ids no tool returned. That is
honest but incomplete: the claim stays in the answer with nothing behind
it, and the user reads a confident sentence whose support was silently
deleted. This spends one bounded turn asking the model to cite something
real or retract.
"""

import uuid

from services.agent.driver import (
    reground_prompt,
    sentences_losing_support,
)

GOOD = "11111111-1111-1111-1111-111111111111"
FAKE = "99999999-9999-9999-9999-999999999999"


# ---- finding the claims that lost support --------------------------------


def test_it_finds_the_sentence_whose_citation_was_stripped():
    text = (
        f"The cat was at the back door [obs:{GOOD}]. "
        f"She then went to the kitchen [obs:{FAKE}]."
    )
    losing = sentences_losing_support(text, [f"obs:{FAKE}"])

    assert len(losing) == 1
    assert "kitchen" in losing[0]


def test_a_well_supported_sentence_is_left_alone():
    text = f"The cat was at the back door [obs:{GOOD}]."
    assert sentences_losing_support(text, [f"obs:{FAKE}"]) == []


def test_nothing_removed_means_nothing_to_reground():
    assert sentences_losing_support("Anything.", []) == []
    assert sentences_losing_support("", [f"obs:{FAKE}"]) == []


def test_several_bad_claims_are_all_collected():
    other_fake = "88888888-8888-8888-8888-888888888888"
    text = (
        f"First claim [obs:{FAKE}]. "
        f"Second claim [journey:{other_fake}]. "
        "Third claim with no citation at all."
    )
    losing = sentences_losing_support(
        text, [f"obs:{FAKE}", f"journey:{other_fake}"]
    )
    assert len(losing) == 2


def test_the_kind_prefix_does_not_have_to_match():
    """The stripped record says journey:<id> while the text said obs:<id>
    only in pathological cases, but matching on the id alone is the safer
    read."""
    text = f"A claim [journey:{FAKE}]."
    assert sentences_losing_support(text, [f"obs:{FAKE}"]) != []


def test_duplicate_sentences_are_listed_once():
    text = f"Same claim [obs:{FAKE}]. Same claim [obs:{FAKE}]."
    assert len(sentences_losing_support(text, [f"obs:{FAKE}"])) == 1


# ---- the follow-up -------------------------------------------------------


def test_the_prompt_offers_retraction_as_well_as_citation():
    """Asking only for a citation invites the model to invent a better
    looking one."""
    prompt = reground_prompt(["The cat went to the kitchen."])

    assert "cite an id a tool actually returned" in prompt
    assert "drop the claim" in prompt
    assert "Do not invent ids" in prompt
    assert "Do not call any tools" in prompt


def test_the_prompt_names_the_specific_claims():
    prompt = reground_prompt(["The cat went to the kitchen."])
    assert "The cat went to the kitchen." in prompt


def test_the_prompt_is_capped():
    prompt = reground_prompt([f"Claim {i}." for i in range(20)])
    assert prompt.count("- Claim") == 5


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


def _drive(monkeypatch, answer, reground_answer=None):
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 20)
    _patch_get_setting(monkeypatch)

    scripted = [
        LLMResponse(stop_reason="tool_use", text="",
                    tool_uses=[LLMToolUse(id="t1", name="query_observations",
                                          arguments={"query": "cat"})]),
        LLMResponse(stop_reason="end_turn", text=answer, tool_uses=[]),
    ]
    if reground_answer is not None:
        scripted.append(
            LLMResponse(stop_reason="end_turn", text=reground_answer, tool_uses=[])
        )
    it = iter(scripted)

    async def _llm_call(**kwargs):
        try:
            return next(it)
        except StopIteration:
            return LLMResponse(stop_reason="end_turn", text="", tool_uses=[])

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    async def _tool(ctx, **kw):
        return {"count": 1, "observations": [{"observation_id": GOOD}]}

    original = tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"]
    tools_mod._REGISTRY_BY_NAME["query_observations"]["fn"] = _tool
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


def test_a_fabricated_citation_triggers_one_reground(monkeypatch):
    events, run_row = _drive(
        monkeypatch,
        answer=f"Cat at the door [obs:{GOOD}]. Then the kitchen [obs:{FAKE}].",
        reground_answer=f"Cat at the door [obs:{GOOD}]. I could not confirm the kitchen.",
    )

    kinds = [e["type"] for e in events]
    assert "citations_stripped" in kinds
    assert "reground_started" in kinds
    assert kinds.count("reground_started") == 1  # bounded

    finished = [e for e in events if e["type"] == "reground_finished"]
    assert finished and finished[0]["accepted"] is True
    assert "could not confirm" in run_row.final_answer
    assert GOOD in run_row.final_answer


def test_a_clean_answer_never_regrounds(monkeypatch):
    events, run_row = _drive(monkeypatch, answer=f"Cat at the door [obs:{GOOD}].")

    assert "reground_started" not in [e["type"] for e in events]
    assert f"[obs:{GOOD}]" in run_row.final_answer


def test_a_worse_rewrite_is_rejected(monkeypatch):
    """A reply that drops every citation "fixes" the problem by deleting
    the answer's support, which is the failure this exists to prevent."""
    events, run_row = _drive(
        monkeypatch,
        answer=f"Cat at the door [obs:{GOOD}]. Then the kitchen [obs:{FAKE}].",
        reground_answer="I am not sure about any of it.",
    )

    finished = [e for e in events if e["type"] == "reground_finished"]
    assert finished and finished[0]["accepted"] is False
    # The original, minus the fabricated citation, survives.
    assert GOOD in run_row.final_answer
    assert FAKE not in run_row.final_answer


def test_an_empty_rewrite_leaves_the_stripped_answer(monkeypatch):
    events, run_row = _drive(
        monkeypatch,
        answer=f"Cat at the door [obs:{GOOD}]. Then the kitchen [obs:{FAKE}].",
        reground_answer="",
    )
    assert GOOD in run_row.final_answer
    assert FAKE not in run_row.final_answer


def test_a_run_with_no_evidence_is_skipped(monkeypatch):
    """A question that is legitimately uncitable, such as how many
    cameras there are, produces no evidence ids. Skipped by that
    condition rather than by a list of special cases."""
    run_row = _FakeRunRow()
    factory, db = _fake_db_session(run_row)
    _patch_runs(monkeypatch, run_row)
    _patch_budget(monkeypatch, [_BudgetOk()] * 10)
    _patch_get_setting(monkeypatch)

    async def _llm_call(**kwargs):
        return LLMResponse(stop_reason="end_turn",
                           text=f"You have four cameras [obs:{FAKE}].",
                           tool_uses=[])

    monkeypatch.setattr(driver_mod, "llm_call", _llm_call)

    events: list[dict] = []

    async def _broadcast(rid, ev):
        events.append(ev)

    drv = driver_mod.AgentDriver(db_factory=factory, broadcast=_broadcast)
    _run(drv.run(run_id=uuid.uuid4(), user=_FakeUser(), question="how many cameras?",
                 provider=_FakeProvider(), model="m", parent_run_id=None))

    assert "reground_started" not in [e["type"] for e in events]
    assert FAKE not in run_row.final_answer
