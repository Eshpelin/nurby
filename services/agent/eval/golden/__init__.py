"""Golden-set evaluation harness for VLM captions and Ask answers.

Issue #214. This is the *real-footage yardstick* that complements the
mocked agent eval next door (``services.agent.eval``). Where the mocked
suite is a fast structural gate that proves the agent loop still wires
together, this harness scores the *quality* of two user-facing outputs
against labeled ground truth.

- Caption faithfulness. Does the VLM's structured caption describe what
  actually happened in the clip, and does it agree on event presence?
- Ask answer correctness. Does the agent's answer match the known
  answer for a labeled question?

Design constraints (see ``docs/golden-eval.md``).

- Deterministic in CI. The default providers are *replay* providers
  that read a committed ``mock_prediction`` block from each fixture, so
  the harness runs green with no live model and no external service.
- Footage stays out of git. Fixtures pin a footage hash + a source
  handle; the pixels live elsewhere. The committed set is the label +
  a replayable prediction, which is all CI needs.
- Pluggable seam. A live run swaps in a provider that calls the real
  VLM (``services.agent.analyzer.call_vlm_structured``) or the real
  agent driver. See ``services.agent.eval.golden.providers``.

Public surface.

- ``load_golden_set(root)`` -> list of ``GoldenCase``.
- ``run_golden_set(cases, caption_provider, answer_provider, config)``
  -> ``GoldenReport``.
- ``format_scorecard(report)`` -> markdown scorecard.
- ``ReplayCaptionProvider`` / ``ReplayAnswerProvider`` are the
  deterministic defaults; ``RunConfig`` carries provider/model/prompt
  attribution so a scorecard is citable.
- ``alert_to_golden_case(observation, feedback)`` is the #195 intake
  path: turn an "incorrect" reviewed alert into a golden case with no
  manual schema work.
"""

from services.agent.eval.golden.intake import alert_to_golden_case
from services.agent.eval.golden.providers import (
    ReplayAnswerProvider,
    ReplayCaptionProvider,
    RunConfig,
)
from services.agent.eval.golden.runner import (
    CaseScore,
    GoldenReport,
    load_golden_set,
    run_golden_set,
)
from services.agent.eval.golden.schema import (
    SCENARIO_FAMILIES,
    GoldenCase,
    load_case,
)
from services.agent.eval.golden.scorecard import format_scorecard

__all__ = [
    "SCENARIO_FAMILIES",
    "CaseScore",
    "GoldenCase",
    "GoldenReport",
    "ReplayAnswerProvider",
    "ReplayCaptionProvider",
    "RunConfig",
    "alert_to_golden_case",
    "format_scorecard",
    "load_case",
    "load_golden_set",
    "run_golden_set",
]
