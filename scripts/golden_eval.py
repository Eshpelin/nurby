#!/usr/bin/env python3
"""Golden-set evaluation CLI (#214).

Produces an attributable scorecard for a provider/model/prompt version over
the labeled real-footage golden set, validates scenario coverage, and pulls
incorrect reviewed alerts (#195) into the set.

Examples:

  # Score the recorded outputs already in the golden set (no footage/model,
  # deterministic keyword judge). This is the CI-friendly subset path.
  python3 scripts/golden_eval.py score --provider gemini --model gemini-2.0-flash \\
      --prompt-version v3

  # Check the set covers every scenario family with its minimum count.
  python3 scripts/golden_eval.py validate

  # Score a candidate prompt version against the current one and gate the
  # promotion on the comparison (exit 1 when it regresses).
  python3 scripts/golden_eval.py score ... --prompt-key live_caption \\
      --prompt-version v1 --out base.json
  python3 scripts/golden_eval.py score ... --prompt-key live_caption \\
      --prompt-version v2 --out cand.json
  python3 scripts/golden_eval.py compare base.json cand.json

  # Grow the set from users' "incorrect" alert reviews.
  python3 scripts/golden_eval.py intake

Real footage + a live model is opt-in and local only: wire a runner into
``run_scorecard`` (a caption/answer function). No footage ever lives in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.agent.eval.golden.harness import run_scorecard  # noqa: E402
from services.agent.eval.golden.schema import coverage_gaps, load_cases  # noqa: E402


def _cmd_score(args: argparse.Namespace) -> int:
    cases = load_cases()
    if not cases:
        print("No golden cases found. Add cases under tests/agent_fixtures/golden/.", file=sys.stderr)
        return 1
    card = run_scorecard(
        cases,
        provider=args.provider,
        model=args.model,
        prompt_version=args.prompt_version,
        prompt_key=args.prompt_key,
    )
    if args.json:
        print(card.to_json())
    else:
        print(card.to_markdown())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(card.to_json() if args.out.endswith(".json") else card.to_markdown())
        print(f"[golden] wrote {args.out}", file=sys.stderr)
    # Non-zero exit if coverage is incomplete and --require-coverage was set,
    # so CI can gate an accuracy claim on a complete set.
    if args.require_coverage and card.coverage_gaps:
        print("[golden] coverage incomplete; failing per --require-coverage", file=sys.stderr)
        return 2
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    import json

    from services.agent.eval.golden.harness import compare_scorecards

    with open(args.baseline, encoding="utf-8") as f:
        baseline = json.load(f)
    with open(args.candidate, encoding="utf-8") as f:
        candidate = json.load(f)
    result = compare_scorecards(baseline, candidate, tolerance=args.tolerance)
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.to_markdown())
    # Non-zero when the candidate should not be promoted, so a promotion can
    # be gated on this in CI or a release checklist.
    return 0 if result.promotable else 1


def _cmd_validate(_args: argparse.Namespace) -> int:
    cases = load_cases()
    gaps = coverage_gaps(cases)
    if not gaps:
        print(f"[golden] coverage complete across all families ({len(cases)} cases).")
        return 0
    print("[golden] coverage gaps (family: have/need):", file=sys.stderr)
    for fam, (have, need) in sorted(gaps.items()):
        print(f"  {fam}: {have}/{need}", file=sys.stderr)
    return 1


def _cmd_intake(_args: argparse.Namespace) -> int:
    from services.agent.eval.golden.intake import intake_incorrect_feedback
    from shared.database import async_session

    async def _run() -> list[str]:
        async with async_session() as db:
            return await intake_incorrect_feedback(db)

    written = asyncio.run(_run())
    if not written:
        print("[golden] no new incorrect-alert cases to add.")
    else:
        print(f"[golden] wrote {len(written)} draft case(s): {', '.join(written)}")
        print("[golden] fill each case's truth.reference with the correct description.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Golden-set evaluation (#214)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("score", help="produce a scorecard")
    ps.add_argument("--provider", required=True)
    ps.add_argument("--model", required=True)
    ps.add_argument("--prompt-version", required=True)
    ps.add_argument("--prompt-key", help="registry key (e.g. live_caption); pins the prompt text sha")
    ps.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ps.add_argument("--out", help="also write the scorecard to this path (.json or .md)")
    ps.add_argument("--require-coverage", action="store_true",
                    help="exit non-zero if the set does not cover every family")
    ps.set_defaults(func=_cmd_score)

    pc = sub.add_parser("compare", help="compare a candidate prompt's scorecard to a baseline")
    pc.add_argument("baseline", help="baseline scorecard JSON (score --json --out)")
    pc.add_argument("candidate", help="candidate scorecard JSON")
    pc.add_argument("--tolerance", type=float, default=0.0,
                    help="allowed metric drop (fraction) before counting a regression")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=_cmd_compare)

    pv = sub.add_parser("validate", help="check scenario-family coverage")
    pv.set_defaults(func=_cmd_validate)

    pi = sub.add_parser("intake", help="add incorrect reviewed alerts (#195) to the set")
    pi.set_defaults(func=_cmd_intake)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
