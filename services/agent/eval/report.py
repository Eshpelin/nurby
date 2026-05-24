"""Markdown report formatter for the agent eval harness.

Writes a self-contained ``.eval-report.md`` artifact CI uploads (and
optionally posts as a PR comment). The format is deliberately easy to
eyeball; the failure section names each failed fixture plus its first
failure line so reviewers can triage without opening the raw YAML.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from services.agent.eval.runner import EvalResult

# Phase 1 exit criterion. Documented in docs/agent-design.md section 11.3.
PASS_THRESHOLD = 27


def _per_tag_summary(results: Iterable[EvalResult]) -> dict[str, tuple[int, int]]:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        for tag in r.tags or ["untagged"]:
            buckets[tag].append(r.passed and not r.skipped)
    return {tag: (sum(passes), len(passes)) for tag, passes in buckets.items()}


def format_report(results: list[EvalResult], *, mocked: bool = True) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = total - passed - skipped

    avg_turns = 0.0
    counted = 0
    for r in results:
        if r.run is not None:
            avg_turns += r.run.turns_used
            counted += 1
    avg_turns = (avg_turns / counted) if counted else 0.0

    total_cost = sum((r.run.cost_cents if r.run else 0) for r in results)
    cost_str = "$0.00 (mocked)" if mocked else f"${total_cost / 100:.2f}"

    lines: list[str] = []
    lines.append("# Agent Eval Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Passed. {passed} / {total}")
    lines.append(f"- Failed. {failed}")
    lines.append(f"- Skipped. {skipped}")
    lines.append(f"- Cost. {cost_str}")
    lines.append(f"- Avg turns per fixture. {avg_turns:.1f}")
    lines.append(f"- Phase 1 exit threshold. {PASS_THRESHOLD} / {total}")
    lines.append(f"- Threshold met. {'yes' if passed >= PASS_THRESHOLD else 'no'}")
    lines.append("")

    fails = [r for r in results if not r.passed and not r.skipped]
    if fails:
        lines.append("## Failures")
        for r in fails:
            first = r.failures[0] if r.failures else "unknown failure"
            lines.append(f"- {r.fixture_id}. {first}")
        lines.append("")

    skips = [r for r in results if r.skipped]
    if skips:
        lines.append("## Skipped")
        for r in skips:
            lines.append(f"- {r.fixture_id}. {r.skip_reason or 'unspecified'}")
        lines.append("")

    lines.append("## By tag")
    for tag, (p, n) in sorted(_per_tag_summary(results).items()):
        lines.append(f"- {tag}. {p}/{n}")
    lines.append("")

    return "\n".join(lines)


def passed_threshold(results: list[EvalResult]) -> bool:
    passed = sum(1 for r in results if r.passed and not r.skipped)
    return passed >= PASS_THRESHOLD


__all__ = ["PASS_THRESHOLD", "format_report", "passed_threshold"]
