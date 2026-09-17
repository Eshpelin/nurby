"""Golden-set runner.

Loads committed fixtures, asks a provider for each prediction, scores
it against the label, and aggregates a ``GoldenReport``. Pure Python,
no I/O beyond reading the committed JSON fixtures, so it runs
identically in CI and on a laptop.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from services.agent.eval.golden import scoring
from services.agent.eval.golden.providers import (
    AnswerProvider,
    CaptionProvider,
    ReplayAnswerProvider,
    ReplayCaptionProvider,
    RunConfig,
)
from services.agent.eval.golden.schema import GoldenCase, load_case

# Committed fixtures live beside this package so the harness ships with
# a runnable set. Footage is not here; only labels + replay blobs.
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures"


@dataclass
class CaseScore:
    """The scored outcome of one golden case."""

    case_id: str
    kind: str
    scenario: str
    passed: bool
    metrics: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "passed" if self.passed else "failed"


@dataclass
class GoldenReport:
    """Aggregate over a whole golden run."""

    config: RunConfig
    scores: list[CaseScore] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.scores)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scores if s.passed)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    def _mean_metric(self, key: str, kind: str | None = None) -> float:
        vals = [
            s.metrics[key]
            for s in self.scores
            if key in s.metrics and (kind is None or s.kind == kind)
        ]
        return mean(vals) if vals else 0.0

    @property
    def caption_faithfulness(self) -> float:
        return self._mean_metric("keyword_coverage", kind="caption")

    @property
    def answer_correctness(self) -> float:
        return self._mean_metric("keyword_coverage", kind="ask")

    @property
    def event_presence_accuracy(self) -> float:
        return self._mean_metric("event_presence_correct")

    @property
    def semantic_lite_mean(self) -> float:
        return self._mean_metric("semantic_lite")

    def by_scenario(self) -> dict[str, tuple[int, int]]:
        buckets: dict[str, list[bool]] = defaultdict(list)
        for s in self.scores:
            buckets[s.scenario].append(s.passed)
        return {k: (sum(v), len(v)) for k, v in sorted(buckets.items())}

    def scenarios_covered(self) -> set[str]:
        return {s.scenario for s in self.scores}


# ── Loading ─────────────────────────────────────────────────────────


def load_golden_set(root: Path | None = None) -> list[GoldenCase]:
    """Load every committed fixture under ``root`` (recursively)."""
    base = root or GOLDEN_DIR
    cases = [load_case(p) for p in sorted(base.rglob("*.json"))]
    return cases


# ── Scoring one case ────────────────────────────────────────────────


def _score_text_case(
    *,
    case: GoldenCase,
    text: str,
    predicted_event: bool,
    coverage_keywords: list[str],
) -> CaseScore:
    gt = case.ground_truth
    coverage = scoring.keyword_coverage(text, coverage_keywords)
    violations = scoring.forbidden_violations(text, gt.forbidden)
    sem = scoring.semantic_lite(text, gt.reference)
    event_ok = bool(predicted_event) == bool(gt.event_present)

    failures: list[str] = []
    if coverage < 1.0:
        missing = [
            kw for kw in coverage_keywords if not scoring.phrase_present(text, kw)
        ]
        failures.append(f"missing required phrase(s) {missing}; coverage={coverage:.2f}")
    if violations:
        failures.append(f"forbidden phrase(s) present {violations}")
    if not event_ok:
        failures.append(
            f"event presence wrong; expected {gt.event_present}, got {predicted_event}"
        )

    metrics = {
        "keyword_coverage": coverage,
        "forbidden_violations": float(len(violations)),
        "semantic_lite": sem,
        "event_presence_correct": 1.0 if event_ok else 0.0,
    }
    return CaseScore(
        case_id=case.id,
        kind=case.kind,
        scenario=case.scenario,
        passed=not failures,
        metrics=metrics,
        failures=failures,
    )


def score_case(
    case: GoldenCase,
    *,
    caption_provider: CaptionProvider,
    answer_provider: AnswerProvider,
) -> CaseScore:
    """Route a case to the right provider and score its prediction."""
    if case.kind == "caption":
        pred = caption_provider.caption(case)
        return _score_text_case(
            case=case,
            text=pred.caption,
            predicted_event=pred.event_present,
            coverage_keywords=case.ground_truth.must_include,
        )
    # kind == "ask"
    pred = answer_provider.answer(case)
    return _score_text_case(
        case=case,
        text=pred.answer,
        predicted_event=pred.event_present,
        coverage_keywords=case.ground_truth.must_include,
    )


# ── Running the set ─────────────────────────────────────────────────


def run_golden_set(
    cases: list[GoldenCase],
    *,
    caption_provider: CaptionProvider | None = None,
    answer_provider: AnswerProvider | None = None,
    config: RunConfig | None = None,
) -> GoldenReport:
    """Score every case and return a ``GoldenReport``.

    Providers default to the deterministic replay providers so a bare
    ``run_golden_set(load_golden_set())`` works in CI.
    """
    caption_provider = caption_provider or ReplayCaptionProvider()
    answer_provider = answer_provider or ReplayAnswerProvider()
    config = config or RunConfig()

    scores = [
        score_case(
            c,
            caption_provider=caption_provider,
            answer_provider=answer_provider,
        )
        for c in cases
    ]
    return GoldenReport(config=config, scores=scores)


__all__ = [
    "GOLDEN_DIR",
    "CaseScore",
    "GoldenReport",
    "load_golden_set",
    "run_golden_set",
    "score_case",
]
