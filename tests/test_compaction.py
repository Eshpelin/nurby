"""Conversation compaction (issue #135).

The driver appended to `messages` for up to twelve turns and never
compacted, re-sending the whole history each turn. Cost grew
quadratically and a small context window overflowed rather than
degrading. This is the cheap half: old tool results become the one-line
summary the driver already computes, with no LLM call.

Two properties are load-bearing and easy to lose: the citable ids have to
survive, and the model has to be told it is looking at a summary.
"""

import json

from services.agent.compaction import (
    CONDENSED_PREFIX,
    DEFAULT_KEEP_RECENT_TURNS,
    MAX_IDS_KEPT,
    approximate_size,
    compact_messages,
    condense_block,
    is_tool_result_message,
)
from services.agent.driver import _result_summary

OBS_ID = "11111111-1111-1111-1111-111111111111"
OBS_ID2 = "22222222-2222-2222-2222-222222222222"


def _result_block(tool="query_observations", payload=None, call_id="c1"):
    payload = payload if payload is not None else {
        "count": 2,
        "observations": [{"observation_id": OBS_ID}, {"observation_id": OBS_ID2}],
    }
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "tool_name": tool,
        "content": json.dumps(payload),
    }


def _history(turns):
    """A realistic assistant/tool_result alternation."""
    messages = [{"role": "user", "content": "where is the cat?"}]
    for i in range(turns):
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"c{i}", "name": "query_observations",
             "input": {}},
        ]})
        messages.append({"role": "user", "content": [
            _result_block(call_id=f"c{i}"),
        ]})
    return messages


# ---- what gets condensed -------------------------------------------------


def test_recent_results_are_left_verbatim():
    """The model is still working with the rows it just asked for."""
    messages = _history(2)
    out, condensed = compact_messages(messages, _result_summary)

    assert condensed == 0
    assert out == messages


def test_older_results_are_condensed():
    messages = _history(5)
    out, condensed = compact_messages(messages, _result_summary)

    assert condensed == 5 - DEFAULT_KEEP_RECENT_TURNS
    condensed_blocks = [
        b for m in out if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and str(b.get("content", "")).startswith(CONDENSED_PREFIX)
    ]
    assert len(condensed_blocks) == 3


def test_the_most_recent_results_survive_intact():
    messages = _history(5)
    out, _ = compact_messages(messages, _result_summary)

    tail = [m for m in out if is_tool_result_message(m)][-DEFAULT_KEEP_RECENT_TURNS:]
    for message in tail:
        for block in message["content"]:
            json.loads(block["content"])  # still the full payload


def test_compaction_shrinks_the_history():
    messages = _history(6)
    before = approximate_size(messages)
    out, _ = compact_messages(messages, _result_summary)

    assert approximate_size(out) < before


def test_the_input_is_not_mutated():
    """The driver reassigns from the return value; a mutation would make
    the two diverge in confusing ways."""
    messages = _history(5)
    snapshot = json.dumps(messages)
    compact_messages(messages, _result_summary)
    assert json.dumps(messages) == snapshot


# ---- the two things that must survive ------------------------------------


def test_citable_ids_survive_compaction():
    """The driver strips citations pointing at ids no tool returned. If
    condensing dropped the ids, an answer citing evidence from five turns
    ago would lose its support and be left a bare claim."""
    block = condense_block(_result_block(), _result_summary)

    assert OBS_ID in block["content"]
    assert OBS_ID2 in block["content"]


def test_only_a_handful_of_ids_are_kept():
    payload = {"observations": [
        {"observation_id": f"1111111{i}-1111-1111-1111-111111111111"}
        for i in range(20)
    ]}
    block = condense_block(_result_block(payload=payload), _result_summary)

    kept = block["content"].split("ids: ")[1].split(", ")
    assert len(kept) == MAX_IDS_KEPT


def test_the_model_is_told_it_is_a_summary():
    block = condense_block(_result_block(), _result_summary)
    assert block["content"].startswith(CONDENSED_PREFIX)


def test_the_summary_says_what_the_call_returned():
    block = condense_block(_result_block(), _result_summary)
    assert "2 observations" in block["content"]


def test_the_tool_use_id_is_preserved():
    """Anthropic rejects a tool_result whose id does not match its
    tool_use, so losing this breaks the whole turn."""
    block = condense_block(_result_block(call_id="abc"), _result_summary)
    assert block["tool_use_id"] == "abc"


# ---- robustness ----------------------------------------------------------


def test_condensing_is_idempotent():
    once = condense_block(_result_block(), _result_summary)
    twice = condense_block(once, _result_summary)
    assert once == twice


def test_unparseable_content_still_condenses():
    """Should not happen now that results are shaped structurally (#134),
    but a crash here would take down the run."""
    block = {"type": "tool_result", "tool_use_id": "c1",
             "tool_name": "query_observations", "content": "not json{"}
    out = condense_block(block, _result_summary)
    assert out["content"].startswith(CONDENSED_PREFIX)


def test_a_failing_summarizer_does_not_break_the_run():
    def _boom(name, result):
        raise ValueError("nope")

    out = condense_block(_result_block(), _boom)
    assert out["content"].startswith(CONDENSED_PREFIX)


def test_error_results_condense_to_their_error():
    payload = {"error": "tool_loop_detected", "message": "pick another approach"}
    block = condense_block(_result_block(payload=payload), _result_summary)
    assert "tool_loop_detected" in block["content"]


def test_non_tool_messages_are_untouched():
    messages = [
        {"role": "user", "content": "where is the cat?"},
        {"role": "assistant", "content": "Looking."},
    ]
    out, condensed = compact_messages(messages, _result_summary)
    assert out == messages
    assert condensed == 0


def test_is_tool_result_message_detects_shapes():
    assert is_tool_result_message({"content": [_result_block()]}) is True
    assert is_tool_result_message({"content": "plain text"}) is False
    assert is_tool_result_message({"content": [{"type": "text"}]}) is False
    assert is_tool_result_message({}) is False


def test_keep_recent_zero_condenses_everything():
    messages = _history(3)
    _, condensed = compact_messages(messages, _result_summary, keep_recent_turns=0)
    assert condensed == 3
