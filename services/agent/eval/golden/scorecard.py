"""Markdown scorecard for a golden run.

The scorecard is the citable artifact an accuracy claim must reference
(acceptance criterion: "Accuracy claims cite a scorecard, not the
mocked run"). It stamps provider / model / prompt version at the top so
a number is always attributable, and flags any scenario family missing
from the run.
"""

from __future__ import annotations

from services.agent.eval.golden.runner import GoldenReport
from services.agent.eval.golden.schema import SCENARIO_FAMILIES


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def format_scorecard(report: GoldenReport) -> str:
    cfg = report.config
    lines: list[str] = []
    lines.append("# Golden-Set Scorecard")
    lines.append("")
    lines.append("## Attribution")
    lines.append(f"- Provider. {cfg.provider}")
    lines.append(f"- Model. {cfg.model}")
    lines.append(f"- Prompt version. {cfg.prompt_version}")
    lines.append(f"- Mode. {cfg.mode}")
    if cfg.notes:
        lines.append(f"- Notes. {cfg.notes}")
    lines.append("")

    lines.append("## Headline metrics")
    lines.append(f"- Cases scored. {report.total}")
    lines.append(f"- Overall pass rate. {report.passed}/{report.total} ({_pct(report.pass_rate)})")
    lines.append(f"- Caption faithfulness. {_pct(report.caption_faithfulness)}")
    lines.append(f"- Ask answer correctness. {_pct(report.answer_correctness)}")
    lines.append(f"- Event presence/absence accuracy. {_pct(report.event_presence_accuracy)}")
    lines.append(f"- Semantic-lite overlap (informational). {_pct(report.semantic_lite_mean)}")
    lines.append("")

    lines.append("## By scenario family")
    covered = report.scenarios_covered()
    for scenario, (p, n) in report.by_scenario().items():
        lines.append(f"- {scenario}. {p}/{n}")
    missing = [f for f in SCENARIO_FAMILIES if f not in covered]
    if missing:
        lines.append("")
        lines.append("## Coverage gaps")
        lines.append(f"- Scenario families not present in this run. {', '.join(missing)}")
    lines.append("")

    fails = [s for s in report.scores if not s.passed]
    if fails:
        lines.append("## Failures")
        for s in fails:
            first = s.failures[0] if s.failures else "unknown failure"
            lines.append(f"- {s.case_id} ({s.scenario}). {first}")
        lines.append("")

    if cfg.mode == "replay":
        lines.append(
            "> Replay mode: scores reflect committed mock predictions, not a "
            "live model. This proves the harness and scoring wiring, not "
            "real-footage accuracy. Run against a live provider for a "
            "citable quality number."
        )
        lines.append("")

    return "\n".join(lines)


__all__ = ["format_scorecard"]
