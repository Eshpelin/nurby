"""Exporting a real run as an eval fixture (issue #140).

Fixtures were hand-written while every real run already persisted richer
data than they contain. This closes that loop, so a production failure
becomes a regression case in one command instead of being reconstructed
from memory.
"""

import uuid
from types import SimpleNamespace

import yaml

from services.agent.eval.export import (
    REVIEW_MARKER,
    _seed_from_calls,
    _slug,
    _turns_from_calls,
    build_fixture,
)


def _call(turn, name, args=None, result=None, created="2026-08-24T00:00:00"):
    return SimpleNamespace(
        turn_index=turn,
        tool_name=name,
        arguments=args or {},
        result=result if result is not None else {"count": 0, "observations": []},
        created_at=created,
        error_message=None,
    )


def _run(**kw):
    base = dict(
        id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        question="Where is the cat?",
        status="completed",
        final_answer="Last seen at the back door [obs:11111111-1111-1111-1111-111111111111].",
        error_message=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---- shape ---------------------------------------------------------------


def test_the_fixture_matches_the_runner_s_blocks():
    fixture = build_fixture(_run(), [_call(0, "query_observations")])
    assert set(fixture) >= {"id", "question", "tags", "seed", "mocked_llm", "expected"}


def test_it_serializes_to_yaml():
    """It has to survive the round trip to be usable at all."""
    fixture = build_fixture(_run(), [_call(0, "query_observations")])
    reloaded = yaml.safe_load(yaml.safe_dump(fixture, sort_keys=False))
    assert reloaded["question"] == "Where is the cat?"


def test_the_id_is_readable_and_unique_per_run():
    fixture = build_fixture(_run(), [])
    assert fixture["id"].startswith("where_is_the_cat")
    assert fixture["id"].endswith("aaaaaaaa")


def test_slugs_are_filename_safe():
    assert _slug("Did a package arrive?! At 3pm") == "did_a_package_arrive_at_3pm"
    assert _slug("") == "run"
    assert "/" not in _slug("a/b")


# ---- the seed ------------------------------------------------------------


def test_results_become_canned_tool_responses():
    """The runner's seed already accepts tool_results keyed by name, so a
    run's recorded results drop straight in."""
    calls = [_call(0, "query_observations", result={"count": 2})]
    seed = _seed_from_calls(calls)
    assert seed == {"tool_results": {"query_observations": {"count": 2}}}


def test_repeated_calls_with_different_results_become_a_sequence():
    """The mock registry replays a list in order, which is how the run
    actually saw them."""
    calls = [
        _call(0, "query_observations", result={"count": 0}),
        _call(1, "query_observations", result={"count": 5}),
    ]
    seed = _seed_from_calls(calls)["tool_results"]["query_observations"]
    assert seed == [{"count": 0}, {"count": 5}]


def test_identical_repeats_collapse():
    calls = [_call(i, "get_camera_layout", result={"cameras": []}) for i in range(3)]
    seed = _seed_from_calls(calls)["tool_results"]["get_camera_layout"]
    assert seed == {"cameras": []}


def test_a_non_dict_result_is_wrapped():
    calls = [_call(0, "t", result="oops")]
    assert _seed_from_calls(calls)["tool_results"]["t"] == {"value": "oops"}


# ---- the transcript ------------------------------------------------------


def test_calls_group_into_turns():
    """Several tool calls in one turn belong to one assistant message."""
    calls = [
        _call(0, "get_household_snapshot"),
        _call(1, "query_observations"),
        _call(1, "get_journeys"),
    ]
    turns = _turns_from_calls(calls, "done")

    assert len(turns) == 3  # two tool turns plus the final answer
    assert len(turns[1]["tool_uses"]) == 2
    assert turns[-1] == {"text": "done", "stop_reason": "end_turn"}


def test_arguments_are_carried_verbatim():
    calls = [_call(0, "query_observations", args={"query": "cat", "hours": 24})]
    turns = _turns_from_calls(calls, "x")
    assert turns[0]["tool_uses"][0]["arguments"] == {"query": "cat", "hours": 24}


def test_a_run_with_no_tool_calls_still_produces_a_transcript():
    turns = _turns_from_calls([], "just an answer")
    assert turns == [{"text": "just an answer", "stop_reason": "end_turn"}]


# ---- the expectations, and why they are not assertions yet ---------------


def test_expected_is_marked_for_review():
    """Filling final_answer_contains from the observed answer would mint a
    test that passes by construction and proves nothing."""
    fixture = build_fixture(_run(), [_call(0, "query_observations")])

    assert REVIEW_MARKER in fixture["_review"]
    assert fixture["expected"]["final_answer_contains"] == []


def test_observed_behaviour_is_recorded_as_a_starting_point():
    calls = [_call(0, "query_observations"), _call(1, "analyze_clip")]
    fixture = build_fixture(_run(), calls)

    assert fixture["expected"]["tools_called"] == ["query_observations", "analyze_clip"]
    assert fixture["expected"]["vlm_calls_max"] == 1
    assert fixture["expected"]["status"] == "completed"


def test_citations_are_counted_from_the_answer():
    fixture = build_fixture(_run(), [])
    assert fixture["expected"]["citations_min"] == 1


def test_a_failed_run_carries_its_error_and_status():
    run = _run(status="no_answer", final_answer="", error_message="3 empty replies")
    fixture = build_fixture(run, [])

    assert fixture["expected"]["status"] == "no_answer"
    assert fixture["_observed_error"] == "3 empty replies"
    assert "no_answer" in fixture["tags"]


def test_tools_are_listed_once_in_call_order():
    calls = [
        _call(0, "query_observations"),
        _call(1, "query_observations"),
        _call(2, "get_journeys"),
    ]
    fixture = build_fixture(_run(), calls)
    assert fixture["expected"]["tools_called"] == ["query_observations", "get_journeys"]


def test_calls_are_sorted_by_turn():
    """Rows can come back in any order; the transcript must not."""
    calls = [_call(2, "c"), _call(0, "a"), _call(1, "b")]
    fixture = build_fixture(_run(), calls)
    names = [t["tool_uses"][0]["name"] for t in fixture["mocked_llm"][:-1]]
    assert names == ["a", "b", "c"]
