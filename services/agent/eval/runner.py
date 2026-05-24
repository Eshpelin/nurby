"""Eval fixture runner.

A fixture is a YAML file with five blocks.

- ``id`` / ``question`` / ``tags`` describe the case.
- ``seed`` carries the canned tool responses (and minimal entity rows)
  the case needs. The runner does NOT touch a real database; the seed
  is consumed by the in-memory tool registry.
- ``mocked_llm`` is the scripted LLM transcript (turn-by-turn).
- ``expected`` is the scoring contract; see ``_check_expectations``
  for the full vocabulary.
- ``conversation`` (optional) lets a fixture chain a follow-up turn
  with a parent run id so we can exercise multi-turn memory.

The runner returns an ``EvalResult`` per fixture and accumulates them
for the report formatter. Real-LLM mode (``AGENT_EVAL_REAL_LLM=1``) is
checked here so we have a single switch point when Wave 2A's real
driver lands.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from services.agent.eval.mocks import (
    FakeAgentRun,
    LLMTurnResponse,
    MockDriver,
    MockLLMClient,
    MockToolRegistry,
)

logger = logging.getLogger("nurby.agent.eval.runner")

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "agent_fixtures"


# ── Fixture data model ──────────────────────────────────────────────


@dataclass
class EvalFixture:
    """Parsed shape of a fixture YAML file."""

    id: str
    path: Path
    question: str
    tags: list[str] = field(default_factory=list)
    seed: dict[str, Any] = field(default_factory=dict)
    mocked_llm: list[dict[str, Any]] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    conversation: list[dict[str, Any]] = field(default_factory=list)
    budget_cents: int | None = None

    @property
    def primary_tag(self) -> str:
        """First tag if present, else 'untagged'. Used by the report."""
        return self.tags[0] if self.tags else "untagged"


@dataclass
class EvalResult:
    """Outcome of running one fixture."""

    fixture_id: str
    tags: list[str]
    passed: bool
    failures: list[str] = field(default_factory=list)
    run: FakeAgentRun | None = None
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        return "passed" if self.passed else "failed"


# ── Loading ──────────────────────────────────────────────────────────


def list_fixture_paths(root: Path | None = None) -> list[Path]:
    base = root or FIXTURE_DIR
    return sorted(base.glob("*.yaml"))


def load_fixture(path: Path) -> EvalFixture:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return EvalFixture(
        id=data.get("id") or path.stem,
        path=path,
        question=data["question"],
        tags=list(data.get("tags") or []),
        seed=dict(data.get("seed") or {}),
        mocked_llm=list(data.get("mocked_llm") or []),
        expected=dict(data.get("expected") or {}),
        conversation=list(data.get("conversation") or []),
        budget_cents=data.get("budget_cents"),
    )


# ── Script translation ──────────────────────────────────────────────


def _script_from_mocked_llm(mocked: list[dict[str, Any]]) -> list[LLMTurnResponse]:
    script: list[LLMTurnResponse] = []
    for row in mocked:
        script.append(
            LLMTurnResponse(
                tool_uses=list(row.get("tool_uses") or []),
                text=row.get("text"),
                stop_reason=row.get("stop_reason") or ("tool_use" if row.get("tool_uses") else "end_turn"),
                tokens_in=int(row.get("tokens_in", 0)),
                tokens_out=int(row.get("tokens_out", 0)),
                cost_cents=int(row.get("cost_cents", 0)),
            )
        )
    return script


def _tools_from_seed(seed: dict[str, Any]) -> MockToolRegistry:
    """Translate the seed block into a canned tool registry.

    The seed YAML can carry two shapes.

    - ``tool_results``. Mapping tool_name -> dict or list. List entries
      are returned in order on repeated calls (useful for cache
      simulation where call N is a miss and call N+1 is a hit).
    - High-level keys like ``observations`` / ``cameras`` / ``journeys``
      get auto-wrapped into the canonical tool result envelope so simple
      fixtures stay short.
    """
    canned: dict[str, Any] = dict(seed.get("tool_results") or {})

    if "observations" in seed and "query_observations" not in canned:
        obs = list(seed["observations"])
        canned["query_observations"] = {"count": len(obs), "observations": obs}

    if "cameras" in seed and "get_camera_layout" not in canned:
        canned["get_camera_layout"] = {"cameras": list(seed["cameras"])}

    if "journeys" in seed and "get_journeys" not in canned:
        canned["get_journeys"] = {"journeys": list(seed["journeys"])}

    return MockToolRegistry(canned)


# ── Scoring ─────────────────────────────────────────────────────────


def _check_expectations(run: FakeAgentRun, expected: dict[str, Any]) -> list[str]:
    """Return a list of human-readable failure strings (empty = pass)."""
    failures: list[str] = []

    answer = (run.final_answer or "").lower()

    needles = expected.get("final_answer_contains") or []
    for needle in needles:
        if needle.lower() not in answer:
            failures.append(
                f"final_answer missing substring {needle!r}; got {run.final_answer!r}"
            )

    forbidden = expected.get("final_answer_forbidden") or []
    for needle in forbidden:
        if needle.lower() in answer:
            failures.append(f"final_answer contains forbidden substring {needle!r}")

    if "status" in expected and run.status != expected["status"]:
        failures.append(
            f"status mismatch; expected {expected['status']!r}, got {run.status!r}"
        )

    if "tools_called" in expected:
        called = [c.name for c in run.tool_calls]
        for required in expected["tools_called"]:
            if required not in called:
                failures.append(
                    f"expected tool {required!r} to be called; calls were {called}"
                )

    if "tools_not_called" in expected:
        called = {c.name for c in run.tool_calls}
        for banned in expected["tools_not_called"]:
            if banned in called:
                failures.append(f"tool {banned!r} should not have been called")

    if "tool_calls_min" in expected and len(run.tool_calls) < expected["tool_calls_min"]:
        failures.append(
            f"too few tool calls; expected >= {expected['tool_calls_min']}, "
            f"got {len(run.tool_calls)}"
        )
    if "tool_calls_max" in expected and len(run.tool_calls) > expected["tool_calls_max"]:
        failures.append(
            f"too many tool calls; expected <= {expected['tool_calls_max']}, "
            f"got {len(run.tool_calls)}"
        )

    if "vlm_calls_min" in expected and len(run.vlm_calls) < expected["vlm_calls_min"]:
        failures.append(
            f"too few vlm calls; expected >= {expected['vlm_calls_min']}, "
            f"got {len(run.vlm_calls)}"
        )
    if "vlm_calls_max" in expected and len(run.vlm_calls) > expected["vlm_calls_max"]:
        failures.append(
            f"too many vlm calls; expected <= {expected['vlm_calls_max']}, "
            f"got {len(run.vlm_calls)}"
        )

    if "vlm_cached" in expected:
        want_cached = bool(expected["vlm_cached"])
        any_cached = any(c.get("cached") for c in run.vlm_calls)
        if want_cached and not any_cached:
            failures.append("expected at least one cached VLM call, got none")
        if not want_cached and any_cached:
            failures.append("expected no cached VLM calls; got at least one")

    if "cost_cents_max" in expected and run.cost_cents > expected["cost_cents_max"]:
        failures.append(
            f"cost over budget; expected <= {expected['cost_cents_max']}, "
            f"got {run.cost_cents}"
        )

    if "turns_max" in expected and run.turns_used > expected["turns_max"]:
        failures.append(
            f"too many turns; expected <= {expected['turns_max']}, "
            f"got {run.turns_used}"
        )

    if "citations_min" in expected:
        # A "citation" in the mocked harness is any tool call that
        # returned a non-empty result list (observations / journeys /
        # cameras / vlm answer). Loose proxy for the real driver's
        # citation block; tight enough to catch a synthesis with
        # nothing under it.
        cited = sum(1 for c in run.tool_calls if _looks_like_citation(c.result))
        if cited < expected["citations_min"]:
            failures.append(
                f"too few citations; expected >= {expected['citations_min']}, "
                f"got {cited}"
            )

    return failures


def _looks_like_citation(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return False
    for key in ("observations", "journeys", "cameras"):
        if result.get(key):
            return True
    if result.get("answer"):
        return True
    return False


# ── Execution ───────────────────────────────────────────────────────


def _real_llm_requested() -> bool:
    return os.environ.get("AGENT_EVAL_REAL_LLM", "").strip() in {"1", "true", "yes"}


def run_fixture(fixture: EvalFixture) -> EvalResult:
    """Execute one fixture and score it.

    Real-LLM mode is opt-in via ``AGENT_EVAL_REAL_LLM=1``. Until the
    Wave 2A driver lands the real path falls back to mock + records a
    skip on the result so the operator sees the gap clearly.
    """
    if _real_llm_requested():
        try:
            from services.agent import driver as _driver  # noqa. presence probe only

            _ = _driver
        except Exception:
            return EvalResult(
                fixture_id=fixture.id,
                tags=fixture.tags,
                passed=False,
                skipped=True,
                skip_reason="AGENT_EVAL_REAL_LLM=1 but services.agent.driver not yet implemented",
            )
        # When the real driver lands, swap MockDriver out for it here.
        # The rest of the harness already speaks its contract.
        return _run_with_mock(fixture)

    return _run_with_mock(fixture)


def _run_with_mock(fixture: EvalFixture) -> EvalResult:
    script = _script_from_mocked_llm(fixture.mocked_llm)
    llm = MockLLMClient(script)
    tools = _tools_from_seed(fixture.seed)
    driver = MockDriver(llm, tools, budget_cents=fixture.budget_cents)

    parent_id: uuid.UUID | None = None
    last_run: FakeAgentRun | None = None

    # The optional ``conversation`` block lets us run a second turn that
    # inherits the parent run id (mirrors the real driver's follow-up
    # path). When absent, we run a single turn against fixture.question.
    turns_to_run = fixture.conversation or [{"question": fixture.question}]
    for turn_spec in turns_to_run:
        q = turn_spec.get("question") or fixture.question
        last_run = driver.run(q, parent_run_id=parent_id)
        parent_id = last_run.id

    assert last_run is not None
    failures = _check_expectations(last_run, fixture.expected)
    return EvalResult(
        fixture_id=fixture.id,
        tags=fixture.tags,
        passed=not failures,
        failures=failures,
        run=last_run,
    )


__all__ = [
    "EvalFixture",
    "EvalResult",
    "FIXTURE_DIR",
    "list_fixture_paths",
    "load_fixture",
    "run_fixture",
]
