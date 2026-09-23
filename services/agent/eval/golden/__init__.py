"""Golden-set real-footage evaluation (#214).

The accuracy yardstick that complements the mocked regression suite in
``services/agent/eval/runner.py``. See ``docs/golden-set-eval.md``.
"""

from services.agent.eval.golden.harness import ScoreCard, run_scorecard
from services.agent.eval.golden.schema import (
    SCENARIO_FAMILIES,
    GoldenCase,
    GroundTruth,
    MediaRef,
    coverage,
    coverage_gaps,
    load_cases,
    save_case,
)
from services.agent.eval.golden.scoring import Judge, KeywordJudge, LLMJudge, score_case

__all__ = [
    "SCENARIO_FAMILIES",
    "GoldenCase",
    "GroundTruth",
    "MediaRef",
    "ScoreCard",
    "Judge",
    "KeywordJudge",
    "LLMJudge",
    "coverage",
    "coverage_gaps",
    "load_cases",
    "save_case",
    "score_case",
    "run_scorecard",
]
