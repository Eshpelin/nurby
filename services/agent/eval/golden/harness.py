"""Golden-set run harness + scorecard (#214).

Ties the pieces together: for each case, obtain the model output, score it,
and aggregate into a :class:`ScoreCard` that is attributable to a specific
provider / model / prompt version and judge.

Output resolution order per case:

1. ``runner(case)`` if a runner is supplied (a real VLM caption or a real
   Ask answer). This is the local, footage-backed path.
2. ``case.recorded_output`` otherwise. This is the CI / unit-test path: no
   footage, no live model, fully deterministic.

A case with neither is skipped and reported as such, so a partial set never
silently inflates a score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from services.agent.eval.golden.schema import (
    SCENARIO_FAMILIES,
    GoldenCase,
    coverage,
    coverage_gaps,
)
from services.agent.eval.golden.scoring import CaseScore, Judge, KeywordJudge, score_case

# A runner turns a case into the model output string under test.
CaseRunner = Callable[[GoldenCase], str]


@dataclass
class ScoreCard:
    provider: str
    model: str
    prompt_version: str
    judge: str
    generated_at: str
    scores: list[CaseScore] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    coverage_counts: dict[str, int] = field(default_factory=dict)
    coverage_gaps: dict[str, tuple[int, int]] = field(default_factory=dict)

    # ── aggregate metrics ──
    def _subset(self, kind: str | None = None) -> list[CaseScore]:
        return [s for s in self.scores if kind is None or s.kind == kind]

    @staticmethod
    def _rate(vals: list[bool]) -> float | None:
        return round(sum(vals) / len(vals), 4) if vals else None

    @property
    def event_accuracy(self) -> float | None:
        return self._rate([s.event_correct for s in self.scores])

    @property
    def caption_faithfulness(self) -> float | None:
        caps = self._subset("caption")
        return round(sum(s.judge_score for s in caps) / len(caps), 4) if caps else None

    @property
    def answer_correctness(self) -> float | None:
        return self._rate([s.passed for s in self._subset("ask")])

    @property
    def pass_rate(self) -> float | None:
        return self._rate([s.passed for s in self.scores])

    def metrics(self) -> dict:
        return {
            "event_accuracy": self.event_accuracy,
            "caption_faithfulness": self.caption_faithfulness,
            "answer_correctness": self.answer_correctness,
            "pass_rate": self.pass_rate,
            "n_scored": len(self.scores),
            "n_skipped": len(self.skipped),
        }

    def per_family(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for fam in SCENARIO_FAMILIES:
            fam_scores = [s for s in self.scores if s.family == fam]
            if not fam_scores:
                continue
            out[fam] = {
                "n": len(fam_scores),
                "event_accuracy": round(sum(s.event_correct for s in fam_scores) / len(fam_scores), 4),
                "pass_rate": round(sum(s.passed for s in fam_scores) / len(fam_scores), 4),
            }
        return out

    def to_dict(self) -> dict:
        return {
            "provenance": {
                "provider": self.provider,
                "model": self.model,
                "prompt_version": self.prompt_version,
                "judge": self.judge,
                "generated_at": self.generated_at,
            },
            "metrics": self.metrics(),
            "per_family": self.per_family(),
            "coverage": {
                "counts": self.coverage_counts,
                "gaps": {k: list(v) for k, v in self.coverage_gaps.items()},
                "complete": not self.coverage_gaps,
            },
            "failures": [
                {"id": s.case_id, "family": s.family, "detail": s.detail}
                for s in self.scores
                if not s.passed
            ],
            "skipped": self.skipped,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        m = self.metrics()

        def pct(v):
            return "n/a" if v is None else f"{v * 100:.1f}%"

        lines = [
            "# Golden-set scorecard",
            "",
            f"- **Provider/model:** {self.provider} / {self.model}",
            f"- **Prompt version:** {self.prompt_version}",
            f"- **Judge:** {self.judge}",
            f"- **Generated:** {self.generated_at}",
            f"- **Scored:** {m['n_scored']} · **Skipped:** {m['n_skipped']}",
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Event presence/absence accuracy | {pct(m['event_accuracy'])} |",
            f"| Caption faithfulness (judge) | {pct(m['caption_faithfulness'])} |",
            f"| Ask answer correctness | {pct(m['answer_correctness'])} |",
            f"| Overall pass rate | {pct(m['pass_rate'])} |",
            "",
            "## Per family",
            "",
            "| Family | N | Event acc | Pass |",
            "| --- | --- | --- | --- |",
        ]
        pf = self.per_family()
        for fam in SCENARIO_FAMILIES:
            if fam in pf:
                d = pf[fam]
                lines.append(f"| {fam} | {d['n']} | {pct(d['event_accuracy'])} | {pct(d['pass_rate'])} |")
        if self.coverage_gaps:
            lines += ["", "## Coverage gaps", ""]
            for fam, (have, need) in sorted(self.coverage_gaps.items()):
                lines.append(f"- **{fam}**: {have}/{need}")
            lines.append("")
            lines.append("> Coverage incomplete: this scorecard does not yet cover the full set.")
        failures = [s for s in self.scores if not s.passed]
        if failures:
            lines += ["", "## Failures", ""]
            for s in failures:
                lines.append(f"- `{s.case_id}` ({s.family}): {s.detail}")
        return "\n".join(lines) + "\n"


def run_scorecard(
    cases: list[GoldenCase],
    *,
    provider: str,
    model: str,
    prompt_version: str,
    judge: Judge | None = None,
    runner: CaseRunner | None = None,
) -> ScoreCard:
    """Score ``cases`` and return a :class:`ScoreCard`.

    ``runner`` produces the live model output for a case; when omitted, the
    case's ``recorded_output`` is used (footage-free CI/test path). Cases
    with no available output are skipped, never scored as passing.
    """
    judge = judge or KeywordJudge()
    card = ScoreCard(
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        judge=judge.name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        coverage_counts=coverage(cases),
        coverage_gaps=coverage_gaps(cases),
    )
    for case in cases:
        output: str | None = None
        if runner is not None:
            try:
                output = runner(case)
            except Exception as e:  # a broken run must not crash the scorecard
                card.skipped.append(f"{case.id}: runner error: {type(e).__name__}: {e}")
                continue
        if output is None:
            output = case.recorded_output
        if output is None:
            card.skipped.append(f"{case.id}: no runner output and no recorded_output")
            continue
        card.scores.append(score_case(case, output, judge))
    return card
