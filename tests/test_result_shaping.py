"""Tool results must not be cut into corrupt JSON (issue #134).

The driver serialized every tool result with ``json.dumps(result)[:8000]``,
which slices mid-token. The model received a malformed tail and, worse,
had no way to tell a truncated result from a short one: it counted the
rows it could see and answered confidently. Silent truncation is exactly
the input that produces a wrong number stated as fact.
"""

import json

from services.agent.result_shaping import (
    DEFAULT_MAX_CHARS,
    ROW_KEYS,
    _row_key,
    _trim_long_strings,
    shape_tool_result,
)


def _observations(n, text="a" * 200):
    return {
        "count": n,
        "observations": [
            {"observation_id": f"obs-{i}", "camera_name": "Back Door",
             "description": text}
            for i in range(n)
        ],
    }


# ---- the property the old slice did not have -----------------------------


def test_output_is_always_valid_json():
    """The whole point. A caller can parse the result, always."""
    for n in (0, 1, 5, 50, 500):
        out = shape_tool_result("query_observations", _observations(n))
        json.loads(out)  # raises if the fix regressed


def test_a_small_result_is_untouched():
    result = {"count": 1, "observations": [{"observation_id": "obs-1"}]}
    assert json.loads(shape_tool_result("query_observations", result)) == result


def test_a_large_result_stays_within_budget():
    out = shape_tool_result("query_observations", _observations(500))
    assert len(out) <= DEFAULT_MAX_CHARS


# ---- the model has to know it was cut ------------------------------------


def test_truncation_is_announced_with_the_real_total():
    """Without this the model counts the rows it can see and says that
    number out loud."""
    out = json.loads(shape_tool_result("query_observations", _observations(500)))

    marker = out["_truncated"]
    assert marker["key"] == "observations"
    assert marker["total"] == 500
    assert marker["shown"] == len(out["observations"])
    assert marker["shown"] < 500


def test_the_marker_says_what_to_do_next():
    out = json.loads(shape_tool_result("query_observations", _observations(500)))
    assert "hours=" in out["_truncated"]["hint"]


def test_rows_kept_are_whole_rows():
    """Structural, not lexical. Every row that survives is complete."""
    out = json.loads(shape_tool_result("query_observations", _observations(500)))
    for row in out["observations"]:
        assert set(row) == {"observation_id", "camera_name", "description"}


def test_at_least_one_row_survives_when_there_were_rows():
    """An empty list reads as "no results", which means the opposite of
    what happened."""
    fat = {"observations": [{"id": f"o-{i}", "blob": "x" * 5000} for i in range(20)]}
    out = json.loads(shape_tool_result("query_observations", fat))
    assert len(out["observations"]) >= 1
    assert out["_truncated"]["total"] == 20


def test_sibling_fields_are_preserved():
    """The count and the widening note are how the model reasons about
    the query it just made."""
    result = _observations(400)
    result["widened_to"] = 168
    result["note"] = "the requested window was empty"
    out = json.loads(shape_tool_result("query_observations", result))

    assert out["widened_to"] == 168
    assert out["note"] == "the requested window was empty"
    assert out["count"] == 400


# ---- choosing what to trim -----------------------------------------------


def test_known_row_keys_are_preferred():
    result = {"observations": [{"i": i} for i in range(10)],
              "misc": [{"j": j} for j in range(100)]}
    assert _row_key(result) == "observations"


def test_an_unknown_list_key_is_still_trimmable():
    result = {"widgets": [{"i": i} for i in range(10)]}
    assert _row_key(result) == "widgets"


def test_the_longest_list_wins_among_unknowns():
    result = {"a": [1, 2], "b": [1, 2, 3, 4]}
    assert _row_key(result) == "b"


def test_no_lists_means_nothing_to_trim():
    assert _row_key({"answer": "yes", "confidence": 0.8}) is None
    assert _row_key({"observations": []}) is None


def test_every_known_row_key_is_a_string():
    assert all(isinstance(k, str) for k in ROW_KEYS)


# ---- results with no rows to drop ----------------------------------------


def test_a_huge_scalar_field_is_cut_with_a_marker():
    """A VLM transcript can blow the budget on its own. Cut it visibly
    rather than returning a broken string."""
    result = {"answer": "y" * 50_000, "confidence": 0.9}
    out = json.loads(shape_tool_result("analyze_clip", result))

    assert len(json.dumps(out)) <= DEFAULT_MAX_CHARS
    assert out["answer"].endswith("...[truncated]")
    assert out["confidence"] == 0.9
    assert "_truncated" in out


def test_a_single_oversized_row_is_kept_but_shortened():
    """Better a real, marked row than an empty list."""
    result = {"observations": [{"id": "o-1", "description": "z" * 40_000}]}
    out = json.loads(shape_tool_result("query_observations", result))

    assert len(json.dumps(out)) <= DEFAULT_MAX_CHARS
    assert out["observations"][0]["id"] == "o-1"
    assert out["observations"][0]["description"].endswith("...[truncated]")


def test_the_last_resort_still_parses():
    """Even when nothing can be salvaged, the model gets a valid object
    saying so rather than a fragment of a real one."""
    out = json.loads(shape_tool_result("x", {"a": "q" * 200}, max_chars=40))
    assert "_truncated" in out


# ---- misc ----------------------------------------------------------------


def test_a_non_dict_result_is_wrapped():
    assert json.loads(shape_tool_result("t", ["a", "b"])) == {"value": ["a", "b"]}
    assert json.loads(shape_tool_result("t", 42)) == {"value": 42}


def test_non_serializable_values_do_not_raise():
    import uuid as _uuid

    out = json.loads(shape_tool_result("t", {"id": _uuid.uuid4()}))
    assert isinstance(out["id"], str)


def test_trim_long_strings_leaves_short_ones_alone():
    row = {"a": "short", "b": "y" * 100}
    out = _trim_long_strings(row, 50)
    assert out["a"] == "short"
    assert out["b"].endswith("...[truncated]")
    assert len(out["b"]) <= 50


def test_an_error_result_survives_intact():
    """Error shapes are small and the model keys its recovery off them."""
    result = {"error": "tool_loop_detected", "message": "pick another approach"}
    assert json.loads(shape_tool_result("query_observations", result)) == result


def test_uuids_in_kept_rows_still_reach_the_citation_check():
    """The driver collects citable ids from the raw result, but the model
    can only cite what it was shown. Kept rows must keep their ids."""
    out = json.loads(shape_tool_result("query_observations", _observations(500)))
    assert all(r["observation_id"] for r in out["observations"])
