"""Mocks used by the eval harness.

We avoid hitting Postgres, Redis, or any real LLM provider during a
mocked eval run. ``MockLLMClient`` replays a scripted sequence of
provider responses (the ``mocked_llm`` block of a fixture YAML). The
``MockDriver`` walks that sequence, dispatches tool calls against an
in-memory tool registry, and produces a fake ``AgentRun`` snapshot the
runner can score against ``expected``.

This is intentionally a thin re-implementation of the agent loop's
*external contract* (turn N produces tool_uses or a final answer; tool
results feed back into turn N+1). When Wave 2A's real
``services.agent.driver.AgentDriver`` lands, swap ``MockDriver`` for it
inside ``run_fixture``; the rest of the harness is unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("nurby.agent.eval.mocks")


# ── Scripted LLM client ──────────────────────────────────────────────


@dataclass
class LLMTurnResponse:
    """One scripted LLM response.

    Either ``tool_uses`` is non-empty (the LLM wants to invoke tools) or
    ``text`` carries the final synthesis. ``stop_reason`` mirrors the
    Anthropic vocabulary the real driver normalizes onto.
    ``tokens_in`` / ``tokens_out`` / ``cost_cents`` are accounting
    knobs the fixture can use to assert budget behavior.
    """

    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    text: str | None = None
    stop_reason: str = "tool_use"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: int = 0


class MockLLMClient:
    """Replays a fixed list of LLMTurnResponse rows in order.

    Driver calls ``next_response(history)`` once per turn. If the script
    runs out, the client raises ``IndexError`` so an under-specified
    fixture fails loudly instead of hanging the loop.
    """

    def __init__(self, script: list[LLMTurnResponse]):
        self._script = list(script)
        self._cursor = 0
        self.calls: list[dict[str, Any]] = []

    def next_response(self, history: list[dict[str, Any]]) -> LLMTurnResponse:
        if self._cursor >= len(self._script):
            raise IndexError(
                f"MockLLMClient exhausted after {self._cursor} turns; "
                "fixture mocked_llm is too short"
            )
        resp = self._script[self._cursor]
        self._cursor += 1
        self.calls.append({"turn": self._cursor, "history_len": len(history)})
        return resp

    @property
    def turns_used(self) -> int:
        return self._cursor


# ── In-memory tool registry ──────────────────────────────────────────


@dataclass
class ToolInvocation:
    """One tool invocation captured by the mock driver."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    turn_index: int
    error: str | None = None
    cached: bool = False


class MockToolRegistry:
    """Dispatches scripted tool responses.

    Each fixture's ``seed`` block populates the registry with canned
    responses keyed by tool name. A fixture can also override a tool
    with a callable for richer behavior (loop detection, cache
    simulation). The contract matches the real registry shape from
    ``services.agent.tools.TOOL_REGISTRY``.
    """

    def __init__(self, canned: dict[str, Any], overrides: dict[str, Callable] | None = None):
        self._canned = canned or {}
        self._overrides = overrides or {}
        # (tool_name, args_hash) -> hit_count for loop detection assertions
        self._call_signatures: dict[tuple[str, str], int] = {}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        sig = (name, _hash_args(arguments))
        self._call_signatures[sig] = self._call_signatures.get(sig, 0) + 1
        repeat_count = self._call_signatures[sig]

        if name in self._overrides:
            return self._overrides[name](arguments, repeat_count)

        canned = self._canned.get(name)
        if canned is None:
            return {
                "error": "tool_not_canned",
                "message": f"no canned response for tool {name!r}",
            }

        # If the canned response is a list, treat as a sequence indexed
        # by repeat_count - 1; clamp at the last entry. Otherwise just
        # return the single dict every time.
        if isinstance(canned, list):
            idx = min(repeat_count - 1, len(canned) - 1)
            return dict(canned[idx])
        return dict(canned)

    def repeat_count(self, name: str, arguments: dict[str, Any]) -> int:
        return self._call_signatures.get((name, _hash_args(arguments)), 0)


def _hash_args(args: dict[str, Any]) -> str:
    """Stable hash of a tool-call argument dict."""
    import json

    blob = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ── Fake AgentRun snapshot ───────────────────────────────────────────


@dataclass
class FakeAgentRun:
    """In-memory shape the runner scores against.

    Mirrors the columns on ``shared.models.AgentRun`` the eval cares
    about, plus the captured tool + vlm calls so we can assert on the
    full audit trace. Not persisted anywhere.
    """

    id: uuid.UUID
    question: str
    status: str = "running"
    final_answer: str | None = None
    turns_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: int = 0
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    vlm_calls: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    parent_run_id: uuid.UUID | None = None


# ── Mock driver ──────────────────────────────────────────────────────


# Tools that touch the VLM analyzer. Used to count vlm_calls.
_VLM_TOOLS = {"analyze_clip", "analyze_frame"}


class MockDriver:
    """Stand-in for ``services.agent.driver.AgentDriver``.

    Public surface matches what the real driver is expected to expose
    so the runner code does not have to change when Wave 2A lands.
    ``run(question, ...)`` walks the LLM script, dispatches tool calls
    through ``MockToolRegistry``, dedupes loops at 2-repeat, and
    enforces an externally-configured budget cap.
    """

    # Drop a tool call when the same (tool, args) repeats this many
    # times. Matches the dedupe rule in docs/agent-design.md section 13.
    LOOP_LIMIT = 2

    def __init__(
        self,
        llm: MockLLMClient,
        tools: MockToolRegistry,
        *,
        budget_cents: int | None = None,
        max_turns: int = 8,
    ):
        self.llm = llm
        self.tools = tools
        self.budget_cents = budget_cents
        self.max_turns = max_turns

    def run(
        self,
        question: str,
        *,
        parent_run_id: uuid.UUID | None = None,
    ) -> FakeAgentRun:
        run = FakeAgentRun(id=uuid.uuid4(), question=question, parent_run_id=parent_run_id)
        history: list[dict[str, Any]] = [{"role": "user", "content": question}]

        for turn_index in range(self.max_turns):
            # Budget gate before each turn so an exhausted user never
            # gets to pay for one more synthesis turn.
            if self.budget_cents is not None and run.cost_cents >= self.budget_cents:
                run.status = "budget_exhausted"
                run.error_message = "user daily budget exhausted"
                run.final_answer = (
                    "I can't complete this request right now because the "
                    "agent budget for today is exhausted."
                )
                return run

            try:
                resp = self.llm.next_response(history)
            except IndexError as exc:
                run.status = "failed"
                run.error_message = str(exc)
                return run

            run.turns_used += 1
            run.tokens_in += resp.tokens_in
            run.tokens_out += resp.tokens_out
            run.cost_cents += resp.cost_cents

            if resp.tool_uses:
                turn_results: list[dict[str, Any]] = []
                for use in resp.tool_uses:
                    name = use["name"]
                    args = use.get("arguments", {}) or {}
                    repeat = self.tools.repeat_count(name, args) + 1
                    if repeat > self.LOOP_LIMIT:
                        # Hard-stop the loop; record a dedupe marker and
                        # let the LLM's next turn synthesize on what we
                        # have. Matches driver behavior per design 13.
                        invocation = ToolInvocation(
                            name=name,
                            arguments=args,
                            result={
                                "error": "tool_loop_detected",
                                "message": (
                                    f"{name} called {repeat} times with identical "
                                    "args; agent dedupe tripped"
                                ),
                            },
                            turn_index=turn_index,
                            error="tool_loop_detected",
                        )
                    else:
                        result = self.tools.call(name, args)
                        invocation = ToolInvocation(
                            name=name,
                            arguments=args,
                            result=result,
                            turn_index=turn_index,
                            error=result.get("error") if isinstance(result, dict) else None,
                            cached=bool(result.get("cached")) if isinstance(result, dict) else False,
                        )
                    run.tool_calls.append(invocation)
                    if name in _VLM_TOOLS:
                        run.vlm_calls.append(
                            {
                                "tool": name,
                                "cached": invocation.cached,
                                "cost_cents": int(invocation.result.get("cost_cents", 0))
                                if isinstance(invocation.result, dict)
                                else 0,
                                "frames_analyzed": int(
                                    invocation.result.get("frames_analyzed", 0)
                                )
                                if isinstance(invocation.result, dict)
                                else 0,
                            }
                        )
                        run.cost_cents += (
                            int(invocation.result.get("cost_cents", 0))
                            if isinstance(invocation.result, dict)
                            else 0
                        )
                    turn_results.append({"tool": name, "result": invocation.result})
                history.append({"role": "assistant", "content": resp.tool_uses})
                history.append({"role": "tool", "content": turn_results})
                continue

            # Text-only turn = final synthesis. End the loop.
            run.final_answer = resp.text or ""
            run.status = "completed"
            return run

        # Hit the turn cap without an explicit synthesis. Mark failed.
        run.status = "failed"
        run.error_message = f"exceeded max_turns={self.max_turns} without final answer"
        return run


__all__ = [
    "FakeAgentRun",
    "LLMTurnResponse",
    "MockDriver",
    "MockLLMClient",
    "MockToolRegistry",
    "ToolInvocation",
]
