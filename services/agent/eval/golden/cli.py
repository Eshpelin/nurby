"""Runner script for the golden harness.

Usage.

    python -m services.agent.eval.golden.cli \
        --provider replay --model mock --prompt-version v0

Prints the markdown scorecard to stdout and, with ``--out PATH``, writes
it there. Exit code is 0 in replay mode (structural gate) and reflects a
minimum pass rate only when ``--min-pass-rate`` is given (live gating).

A live run supplies its own provider in code; this CLI wires the
deterministic replay providers so ``python -m ...cli`` is a one-command
demonstration over the committed fixtures.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.agent.eval.golden.providers import RunConfig
from services.agent.eval.golden.runner import load_golden_set, run_golden_set
from services.agent.eval.golden.scorecard import format_scorecard


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Golden-set eval scorecard runner.")
    p.add_argument("--root", type=Path, default=None, help="fixtures dir (default: committed set)")
    p.add_argument("--provider", default="replay", help="attribution: provider name")
    p.add_argument("--model", default="mock", help="attribution: model id")
    p.add_argument("--prompt-version", default="v0", help="attribution: prompt version")
    p.add_argument("--mode", default="replay", choices=["replay", "live"], help="run mode label")
    p.add_argument("--out", type=Path, default=None, help="write scorecard markdown here")
    p.add_argument(
        "--min-pass-rate",
        type=float,
        default=None,
        help="fail (exit 1) if pass rate falls below this fraction (live gating)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = load_golden_set(args.root)
    if not cases:
        print("no golden fixtures found", file=sys.stderr)
        return 2

    config = RunConfig(
        provider=args.provider,
        model=args.model,
        prompt_version=args.prompt_version,
        mode=args.mode,
    )
    report = run_golden_set(cases, config=config)
    card = format_scorecard(report)

    if args.out is not None:
        args.out.write_text(card, encoding="utf-8")
    print(card)

    if args.min_pass_rate is not None and report.pass_rate < args.min_pass_rate:
        print(
            f"pass rate {report.pass_rate:.2f} below threshold {args.min_pass_rate:.2f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
