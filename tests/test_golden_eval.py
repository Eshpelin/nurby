"""Tests for the golden-set evaluation harness (issue #214).

These assert the harness *runs deterministically on the committed
fixtures* and that scoring, scorecard, coverage, the CLI, and the #195
intake path all behave. No live model, no network, no footage.
"""

from __future__ import annotations

from services.agent.eval.golden import (
    SCENARIO_FAMILIES,
    ReplayAnswerProvider,
    ReplayCaptionProvider,
    RunConfig,
    alert_to_golden_case,
    format_scorecard,
    load_golden_set,
    run_golden_set,
)
from services.agent.eval.golden import scoring
from services.agent.eval.golden.cli import main as cli_main


# ── Fixtures load + run ─────────────────────────────────────────────


def test_committed_golden_set_loads():
    cases = load_golden_set()
    assert len(cases) == 12
    kinds = {c.kind for c in cases}
    assert kinds == {"caption", "ask"}


def test_all_scenario_families_covered():
    cases = load_golden_set()
    covered = {c.scenario for c in cases}
    for family in SCENARIO_FAMILIES:
        assert family in covered, f"scenario family {family!r} missing from golden set"


def test_run_is_deterministic_on_replay():
    report = run_golden_set(load_golden_set())
    assert report.total == 12
    # Exactly one crafted partial-coverage case is expected to fail.
    assert report.passed == 11
    fails = [s.case_id for s in report.scores if not s.passed]
    assert fails == ["cap_rain_obscured_partial"]


def test_headline_metrics_have_expected_values():
    report = run_golden_set(load_golden_set())
    # caption cases: four full-coverage + one 0.5 => mean 0.9
    assert abs(report.caption_faithfulness - 0.9) < 1e-9
    # every ask answer fully covers its keywords
    assert abs(report.answer_correctness - 1.0) < 1e-9
    # every prediction agrees on event presence/absence
    assert abs(report.event_presence_accuracy - 1.0) < 1e-9


def test_partial_case_metrics():
    report = run_golden_set(load_golden_set())
    partial = next(s for s in report.scores if s.case_id == "cap_rain_obscured_partial")
    assert abs(partial.metrics["keyword_coverage"] - 0.5) < 1e-9
    assert not partial.passed
    assert partial.failures  # human-readable reason present


# ── Scoring unit checks ─────────────────────────────────────────────


def test_scoring_primitives():
    assert scoring.keyword_coverage("a package on the porch", ["package"]) == 1.0
    assert scoring.keyword_coverage("only rain here", ["rain", "vehicle"]) == 0.5
    assert scoring.keyword_coverage("anything", []) == 1.0
    assert scoring.forbidden_violations("an intruder appears", ["intruder"]) == ["intruder"]
    assert scoring.forbidden_violations("all clear", ["intruder"]) == []
    assert scoring.exact_match("A Package.", "a package") is True
    # multi-word phrase, punctuation/case insensitive
    assert scoring.phrase_present("Your Mail-Carrier arrived", "mail carrier") is True
    assert 0.0 < scoring.semantic_lite("a car in the driveway", "a car pulled in") < 1.0


# ── Scorecard ───────────────────────────────────────────────────────


def test_scorecard_is_attributable_and_complete():
    report = run_golden_set(
        load_golden_set(),
        config=RunConfig(provider="google", model="gemini-2.0-flash", prompt_version="v3", mode="live"),
    )
    card = format_scorecard(report)
    assert "gemini-2.0-flash" in card
    assert "Prompt version. v3" in card
    assert "Caption faithfulness" in card
    assert "Ask answer correctness" in card
    assert "Event presence/absence accuracy" in card
    # all families present -> no coverage-gap section
    assert "Coverage gaps" not in card
    # the one failure is surfaced
    assert "cap_rain_obscured_partial" in card


def test_scorecard_flags_missing_families_on_subset():
    cases = [c for c in load_golden_set() if c.scenario == "delivery"]
    report = run_golden_set(cases)
    card = format_scorecard(report)
    assert "Coverage gaps" in card
    assert "night_ir" in card


# ── Providers ───────────────────────────────────────────────────────


def test_replay_providers_read_mock_prediction():
    cases = load_golden_set()
    cap_case = next(c for c in cases if c.kind == "caption")
    ask_case = next(c for c in cases if c.kind == "ask")
    assert ReplayCaptionProvider().caption(cap_case).caption
    assert ReplayAnswerProvider().answer(ask_case).answer


# ── #195 intake path ────────────────────────────────────────────────


def test_alert_intake_wrong_object_becomes_forbidden():
    observation = {"id": "obs_123", "caption": "A raccoon knocks over a bin", "footage_hash": "sha256:xyz"}
    feedback = {"rating": "incorrect", "reason": "wrong_object"}
    case = alert_to_golden_case(observation, feedback)
    assert case.source == "alert_intake"
    # the mis-asserted caption is now something the fixed output must avoid
    assert "A raccoon knocks over a bin" in case.ground_truth.forbidden
    # content-wrong with no corrected label => treated as no such event
    assert case.ground_truth.event_present is False
    # it round-trips through the normal loader with no manual schema work
    assert case.kind == "caption"
    assert case.footage["hash"] == "sha256:xyz"


def test_alert_intake_with_correct_label():
    observation = {"id": "obs_9", "summary": "Unknown person at door"}
    feedback = {"rating": "incorrect", "reason": "wrong_person"}
    case = alert_to_golden_case(observation, feedback, correct_label="your daughter")
    assert "your daughter" in case.ground_truth.must_include
    assert case.ground_truth.event_present is True


def test_alert_intake_rejects_non_incorrect():
    import pytest

    with pytest.raises(ValueError):
        alert_to_golden_case({"id": "x"}, {"rating": "useful"})


# ── CLI ─────────────────────────────────────────────────────────────


def test_cli_runs_green_in_replay_mode(capsys):
    code = cli_main(["--provider", "replay", "--model", "mock", "--prompt-version", "v0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Golden-Set Scorecard" in out


def test_cli_min_pass_rate_gate_fails_when_unmet():
    # committed set passes 11/12 (~0.92); demand 100% and the gate trips
    code = cli_main(["--min-pass-rate", "1.0"])
    assert code == 1
