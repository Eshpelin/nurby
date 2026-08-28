"""Turn a real run into an eval fixture (issue #140).

The eval runner consumes YAML fixtures with ``seed`` / ``mocked_llm`` /
``expected`` blocks, all written by hand. Meanwhile every real run
already persists richer data than those fixtures contain: an ``AgentRun``
plus ``AgentToolCall`` rows carrying tool name, arguments, the full
result, errors, and latency.

The missing piece was one direction of conversion. With it, a production
failure becomes a regression fixture in one command instead of being
reconstructed from memory, which is what makes the agent-quality backlog
verifiable rather than anecdotal.

The ``expected`` block is deliberately pre-filled with **what actually
happened**, not with what should have happened. A human edits it into an
assertion. Writing the observed behaviour in as the expectation would
mint a test that passes by construction and proves nothing, so the
exporter marks it and says so in the file.

Pure: the caller supplies the rows, this shapes them.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("nurby.agent.eval.export")

REVIEW_MARKER = "REVIEW: generated from a real run"

# Statuses worth turning into a fixture without being asked. A completed
# run can still be wrong, but these ended badly by definition.
FAILURE_STATUSES = ("failed", "no_answer", "budget_exhausted")

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _slug(text: str, limit: int = 40) -> str:
    """A filename-safe stub from the question. Pure."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (cleaned[:limit].rstrip("_")) or "run"


def _seed_from_calls(tool_calls: list) -> dict[str, Any]:
    """``{tool_name: result}`` from the recorded calls.

    A tool called several times with different results becomes a list, so
    the mock registry replays them in order the way the run saw them.
    Pure, for tests.
    """
    by_tool: dict[str, list] = {}
    for call in tool_calls:
        result = getattr(call, "result", None)
        by_tool.setdefault(call.tool_name, []).append(
            result if isinstance(result, dict) else {"value": result}
        )
    seed: dict[str, Any] = {}
    for name, results in by_tool.items():
        # Collapse identical repeats: a list of one shape adds noise.
        unique = [results[0]]
        for item in results[1:]:
            if item != unique[-1]:
                unique.append(item)
        seed[name] = unique[0] if len(unique) == 1 else unique
    return {"tool_results": seed}


def _turns_from_calls(tool_calls: list, final_answer: str | None) -> list[dict]:
    """The ``mocked_llm`` transcript. Pure, for tests."""
    by_turn: dict[int, list] = {}
    for call in tool_calls:
        by_turn.setdefault(int(getattr(call, "turn_index", 0) or 0), []).append(call)

    turns: list[dict] = []
    for index in sorted(by_turn):
        turns.append({
            "tool_uses": [
                {"name": c.tool_name, "arguments": dict(c.arguments or {})}
                for c in by_turn[index]
            ]
        })
    turns.append({
        "text": final_answer or "",
        "stop_reason": "end_turn",
    })
    return turns


def _expected_from_run(run, tool_calls: list) -> dict[str, Any]:
    """What the run did, as a starting point for what it should do."""
    answer = getattr(run, "final_answer", "") or ""
    citations = len(_UUID_RE.findall(answer))
    tools = []
    for call in tool_calls:
        if call.tool_name not in tools:
            tools.append(call.tool_name)
    vlm_calls = sum(
        1 for c in tool_calls if c.tool_name in ("analyze_clip", "analyze_frame")
    )
    return {
        "final_answer_contains": [],
        "citations_min": citations,
        "tools_called": tools,
        "vlm_calls_max": vlm_calls,
        "status": getattr(run, "status", "completed"),
    }


def build_fixture(run, tool_calls: list) -> dict[str, Any]:
    """A fixture dict for one run. Pure, for tests.

    The result is intentionally not runnable as an assertion until a
    human edits it: ``final_answer_contains`` is left empty, because
    filling it from the observed answer would produce a test that passes
    by construction.
    """
    calls = sorted(tool_calls or [], key=lambda c: (
        int(getattr(c, "turn_index", 0) or 0), str(getattr(c, "created_at", "")),
    ))
    question = getattr(run, "question", "") or ""
    status = getattr(run, "status", "") or ""

    fixture: dict[str, Any] = {
        "id": f"{_slug(question)}_{str(getattr(run, 'id', ''))[:8]}",
        "question": question,
        "tags": ["exported", status] if status else ["exported"],
        "_review": (
            f"{REVIEW_MARKER} ({getattr(run, 'id', 'unknown')}). "
            "expected.* describes what the run DID, not what it should do. "
            "Edit it into an assertion before relying on this fixture, and "
            "fill in final_answer_contains."
        ),
        "seed": _seed_from_calls(calls),
        "mocked_llm": _turns_from_calls(calls, getattr(run, "final_answer", "")),
        "expected": _expected_from_run(run, calls),
    }
    error = getattr(run, "error_message", None)
    if error:
        fixture["_observed_error"] = str(error)
    return fixture
