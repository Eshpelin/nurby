"""Fit a tool result into the model's view without lying to it (#134).

The driver serialized every tool result with ``json.dumps(result)[:8000]``.
That slices a JSON string mid-token, so the model received things like
``..."camera_name": "Back Do`` with nothing saying the payload had been
cut. Two failures follow from that, and the second is the dangerous one:

1. The tail is malformed, so whatever the model makes of it is guesswork.
2. The model cannot tell a truncated result from a short one. It has no
   way to know the twenty rows it can see are not all the rows there
   were, so it counts them and answers confidently. Silent truncation is
   exactly the input that produces a wrong number stated as fact.

``summarize_activity``, ``get_journeys``, and ``query_observations`` on a
busy household pass 8k routinely, so this is the normal path, not an edge
case.

The fix is to truncate **structurally**: drop whole rows, keep the object
valid, and say so in the payload. The model then knows both that there
was more and what to do about it.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("nurby.agent.result_shaping")

DEFAULT_MAX_CHARS = 8000

# Never cut a result down to nothing. One row plus an honest count beats
# an empty list, which reads as "no results" and means the opposite.
MIN_ROWS_KEPT = 1

# Keys whose value is a list of rows, in the order we prefer to trim.
# Taken from the shapes the tools in services/agent/tools.py actually
# return; an unlisted list key is still trimmable, it just sorts last.
ROW_KEYS = (
    "observations",
    "journeys",
    "events",
    "sightings",
    "incidents",
    "results",
    "items",
    "vehicles",
    "associations",
    "persons",
    "cameras",
    "rules",
    "digests",
    "labels",
    "transitions",
)

# What to tell the model to do about the rows it cannot see. Keyed by row
# key, because the useful next move differs: a time filter helps for
# observations, a different subject helps for journeys.
_HINTS = {
    "observations": "narrow the window with hours=, or filter by person or label",
    "journeys": "narrow the window with hours=, or ask about one subject",
    "events": "narrow the window with hours=, or filter by rule",
    "sightings": "ask about one entity at a time",
    "vehicles": "filter by plate or description",
    "associations": "filter by subject or relation",
}
_DEFAULT_HINT = "narrow the query; these are the most recent rows only"

# A scalar string long enough to blow the budget on its own (a VLM
# transcript, a long summary). Cut with a visible marker rather than
# letting it push every row out of the payload.
_LONG_TEXT_MARKER = " ...[truncated]"


def _size(payload) -> int:
    return len(json.dumps(payload, default=str))


def _row_key(result: dict) -> str | None:
    """The list key worth trimming, or None. Prefers the known row keys,
    then the longest list. Pure, for tests."""
    lists = {
        k: v for k, v in result.items()
        if isinstance(v, list) and v
    }
    if not lists:
        return None
    for key in ROW_KEYS:
        if key in lists:
            return key
    return max(lists, key=lambda k: len(lists[k]))


def _trim_long_strings(result: dict, budget: int) -> dict:
    """Cut oversized scalar strings, marking each one. Pure, for tests."""
    out = dict(result)
    for key, value in out.items():
        if isinstance(value, str) and len(value) > budget:
            out[key] = value[: max(0, budget - len(_LONG_TEXT_MARKER))] + _LONG_TEXT_MARKER
    return out


def shape_tool_result(
    name: str, result, max_chars: int = DEFAULT_MAX_CHARS
) -> str:
    """Serialize a tool result to at most ``max_chars`` of VALID JSON.

    When rows have to be dropped the payload gains a ``_truncated`` block
    naming the key, how many rows are shown, how many there were, and
    what to do about it. Callers can rely on the output parsing: that is
    the property the old slice did not have. Pure, for tests.
    """
    if not isinstance(result, dict):
        result = {"value": result}

    full = json.dumps(result, default=str)
    if len(full) <= max_chars:
        return full

    key = _row_key(result)
    if key is None:
        # Nothing to drop. The bulk is in scalar fields, so cut those
        # with a marker rather than returning a broken string.
        trimmed = _trim_long_strings(result, max_chars // 2)
        trimmed["_truncated"] = {
            "reason": "result too large",
            "hint": "this result was shortened; ask for a narrower slice",
        }
        out = json.dumps(trimmed, default=str)
        if len(out) <= max_chars:
            return out
        # Last resort. Return a valid object that says what happened
        # instead of a broken fragment of the real one.
        return json.dumps({
            "_truncated": {
                "reason": "result too large to include",
                "tool": name,
                "hint": "ask for a narrower slice of this data",
            }
        })

    rows = list(result[key])
    total = len(rows)
    # Largest prefix of rows that still fits, found by halving rather than
    # walking: a 500-row result should not cost 500 serializations.
    lo, hi = 0, total
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = dict(result)
        candidate[key] = rows[:mid]
        candidate["_truncated"] = {
            "key": key,
            "shown": mid,
            "total": total,
            "hint": _HINTS.get(key, _DEFAULT_HINT),
        }
        if _size(candidate) <= max_chars:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    shown = max(best, MIN_ROWS_KEPT if total else 0)
    out = dict(result)
    out[key] = rows[:shown]
    out["_truncated"] = {
        "key": key,
        "shown": shown,
        "total": total,
        "hint": _HINTS.get(key, _DEFAULT_HINT),
    }
    serialized = json.dumps(out, default=str)
    if len(serialized) > max_chars:
        # A single row is bigger than the whole budget. Keep the row but
        # shorten its long strings, so the model sees a real, marked row
        # rather than nothing.
        out[key] = [_trim_long_strings(r, max_chars // 4) if isinstance(r, dict) else r
                    for r in out[key]]
        serialized = json.dumps(out, default=str)
    if len(serialized) > max_chars:
        return json.dumps({
            "_truncated": {
                "key": key,
                "shown": 0,
                "total": total,
                "tool": name,
                "hint": _HINTS.get(key, _DEFAULT_HINT),
            }
        })
    logger.debug(
        "shaped %s result: kept %d/%d %s rows", name, shown, total, key
    )
    return serialized
