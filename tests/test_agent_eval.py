"""Parametrized pytest entry point for the agent eval harness.

Each YAML in ``tests/agent_fixtures`` becomes one test case. A failure
prints the fixture id plus every failed expectation so the diff is
self-explanatory in CI logs. The harness itself lives under
``services/agent/eval``; this module exists only to wire the YAMLs to
pytest's collection and to write the markdown report artifact.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.agent.eval import (
    EvalResult,
    format_report,
    list_fixture_paths,
    load_fixture,
    run_fixture,
)
from services.agent.eval.report import PASS_THRESHOLD, passed_threshold

FIXTURE_PATHS = list_fixture_paths()
REPORT_PATH = Path(__file__).resolve().parents[1] / ".eval-report.md"


@pytest.fixture(scope="session")
def _eval_results_bucket() -> list[EvalResult]:
    """Accumulates every parametrized result so the session-finalizer
    can format a single markdown report."""
    return []


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.stem)
def test_agent_fixture(fixture_path: Path, _eval_results_bucket: list[EvalResult]):
    fixture = load_fixture(fixture_path)
    result = run_fixture(fixture)
    _eval_results_bucket.append(result)
    if result.skipped:
        pytest.skip(result.skip_reason or "skipped")
    assert result.passed, "\n".join(
        [f"fixture {result.fixture_id} failed:"] + [f"  - {f}" for f in result.failures]
    )


def test_eval_summary_report(_eval_results_bucket: list[EvalResult]):
    """Writes ``.eval-report.md`` and asserts the Phase 1 pass
    threshold. Runs last so the per-fixture results are accumulated.

    The threshold check is only enforced when every fixture has been
    collected (full-suite runs). Running a subset via ``-k`` skips the
    threshold so dev iteration stays fast.
    """
    if not _eval_results_bucket:
        pytest.skip("no fixtures collected in this session")

    mocked = os.environ.get("AGENT_EVAL_REAL_LLM", "").strip().lower() not in {"1", "true", "yes"}
    report = format_report(_eval_results_bucket, mocked=mocked)
    REPORT_PATH.write_text(report, encoding="utf-8")

    if len(_eval_results_bucket) < len(FIXTURE_PATHS):
        pytest.skip(
            f"partial suite ({len(_eval_results_bucket)}/{len(FIXTURE_PATHS)}); "
            "threshold not enforced"
        )

    if not passed_threshold(_eval_results_bucket):
        passed = sum(1 for r in _eval_results_bucket if r.passed and not r.skipped)
        pytest.fail(
            f"agent eval below Phase 1 threshold. {passed}/{len(_eval_results_bucket)} "
            f"passed (need >= {PASS_THRESHOLD}). See .eval-report.md."
        )
