"""Golden-set real-footage eval harness (#214).

Covers the schema round-trip, deterministic + judge scoring, scorecard
aggregation and provenance, coverage validation, and #195 feedback intake.
No footage, no live model: the harness scores each case's recorded_output
through the deterministic KeywordJudge.
"""


import pytest

from services.agent.eval.golden.harness import run_scorecard
from services.agent.eval.golden.intake import case_from_feedback
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
from services.agent.eval.golden.scoring import (
    KeywordJudge,
    LLMJudge,
    infer_event_present,
    score_case,
)


def _case(**kw):
    base = dict(
        id="t1", family="delivery", kind="caption",
        truth=GroundTruth(event_present=True, reference="a courier drops a package"),
        recorded_output="a courier drops a package at the door",
    )
    base.update(kw)
    return GoldenCase(**base)


# ── schema ──

def test_case_json_round_trip():
    c = _case(media=MediaRef(sha256="a" * 64, path="/x.mp4"), source="curated")
    again = GoldenCase.from_dict(c.to_dict())
    assert again.to_dict() == c.to_dict()


def test_unknown_family_rejected():
    with pytest.raises(ValueError):
        _case(family="not_a_family")


def test_ask_requires_question():
    with pytest.raises(ValueError):
        _case(kind="ask", question=None)


def test_save_and_load(tmp_path):
    save_case(_case(id="c-a"), tmp_path)
    save_case(_case(id="c-b"), tmp_path)
    loaded = load_cases(tmp_path)
    assert [c.id for c in loaded] == ["c-a", "c-b"]  # sorted by id


# ── deterministic scoring ──

@pytest.mark.parametrize("text,present", [
    ("a person walks up", True),
    ("No activity, the yard is quiet", False),
    ("nobody around", False),
    ("", False),
])
def test_infer_event_present(text, present):
    assert infer_event_present(text) is present


def test_event_absence_scored_correct():
    c = _case(truth=GroundTruth(event_present=False, reference="empty driveway"),
              recorded_output="No activity, empty and quiet")
    s = score_case(c, c.recorded_output, KeywordJudge())
    assert s.event_correct is True


def test_forbidden_vocab_trips():
    c = _case(truth=GroundTruth(event_present=True, reference="courier drops a package",
                                must_not_include=["stole"]),
              recorded_output="a person stole a package")
    s = score_case(c, c.recorded_output, KeywordJudge())
    assert s.vocab_ok is False
    assert "forbidden" in s.detail


def test_missing_required_vocab_trips():
    c = _case(truth=GroundTruth(event_present=True, reference="x", must_include=["package"]),
              recorded_output="a person walks by")
    s = score_case(c, c.recorded_output, KeywordJudge())
    assert s.vocab_ok is False


def test_keyword_judge_scores_overlap():
    j = KeywordJudge()
    high, _ = j.score(question=None, reference="courier drops a package at the door",
                      candidate="a courier dropped a package by the door")
    low, _ = j.score(question=None, reference="courier drops a package",
                     candidate="a cat runs across the lawn")
    assert high > low
    assert 0.0 <= low <= high <= 1.0


def test_llm_judge_parses_score_and_is_reproducible():
    j = LLMJudge(lambda prompt: "0.9", model="fixed-judge-1")
    val, detail = j.score(question=None, reference="a courier drops a package",
                          candidate="a courier left a package")
    assert val == 0.9
    assert j.name == "llm-judge:fixed-judge-1"


def test_llm_judge_unparseable_fails_closed():
    j = LLMJudge(lambda prompt: "the caption looks great", model="m")
    val, _ = j.score(question=None, reference="x", candidate="y")
    assert val == 0.0


def test_llm_judge_error_fails_closed():
    def boom(prompt):
        raise RuntimeError("judge down")

    j = LLMJudge(boom, model="m")
    val, detail = j.score(question=None, reference="x", candidate="y")
    assert val == 0.0
    assert "judge error" in detail


def test_score_case_uses_judge_threshold():
    c = _case(recorded_output="a courier drops a package at the door")
    hi = LLMJudge(lambda p: "0.95", model="m", pass_threshold=0.6)
    lo = LLMJudge(lambda p: "0.3", model="m", pass_threshold=0.6)
    assert score_case(c, c.recorded_output, hi).passed is True
    assert score_case(c, c.recorded_output, lo).passed is False


# ── scorecard ──

def test_scorecard_metrics_and_provenance():
    cases = [
        _case(id="ok", recorded_output="a courier drops a package at the door"),
        _case(id="bad", family="no_event",
              truth=GroundTruth(event_present=False, reference="empty"),
              recorded_output="a person is clearly walking around"),  # says event, truth none
    ]
    card = run_scorecard(cases, provider="gemini", model="flash", prompt_version="v3")
    d = card.to_dict()
    assert d["provenance"] == {
        "provider": "gemini", "model": "flash", "prompt_version": "v3",
        "prompt_key": None, "prompt_sha": None,
        "judge": "keyword-jaccard-v1", "generated_at": card.generated_at,
    }
    assert d["metrics"]["n_scored"] == 2
    assert card.event_accuracy == 0.5  # one right, one wrong
    assert any(f["id"] == "bad" for f in d["failures"])


def test_scorecard_skips_cases_without_output():
    c = _case(id="no-out", recorded_output=None)
    card = run_scorecard([c], provider="p", model="m", prompt_version="v1")
    assert card.scores == []
    assert any("no-out" in s for s in card.skipped)


def test_runner_output_preferred_over_recorded():
    c = _case(recorded_output="recorded text")
    card = run_scorecard([c], provider="p", model="m", prompt_version="v1",
                         runner=lambda case: "a courier drops a package at the door")
    assert card.scores and card.scores[0].judge_score > 0


def test_runner_error_is_skipped_not_fatal():
    def boom(case):
        raise RuntimeError("model down")

    c = _case()
    card = run_scorecard([c], provider="p", model="m", prompt_version="v1", runner=boom)
    assert card.scores == []
    assert any("runner error" in s for s in card.skipped)


def test_markdown_renders():
    card = run_scorecard([_case()], provider="p", model="m", prompt_version="v1")
    md = card.to_markdown()
    assert "Golden-set scorecard" in md
    assert "Prompt version" in md


# ── coverage ──

def test_coverage_gaps_reported():
    cases = [_case(id=f"d{i}", family="delivery") for i in range(3)]
    gaps = coverage_gaps(cases)
    assert gaps["delivery"] == (3, SCENARIO_FAMILIES["delivery"])
    assert "no_event" in gaps  # zero cases -> gap
    assert coverage(cases)["delivery"] == 3


# ── intake from #195 feedback ──

def test_case_from_incorrect_feedback_needs_no_manual_schema():
    fb = {
        "event_id": "e123",
        "reason": "wrong_object",
        "clip_sha256": "f" * 64,
        "clip_path": "/clips/e123.mp4",
        "asserted_caption": "a person stole a package",
    }
    c = case_from_feedback(fb)
    assert c.id == "feedback-e123"
    assert c.source == "feedback:e123"
    assert c.family == "delivery"  # mapped from wrong_object
    assert c.recorded_output == "a person stole a package"
    assert c.media.sha256 == "f" * 64
    # It round-trips like any other case (no manual schema work).
    assert GoldenCase.from_dict(c.to_dict()).id == "feedback-e123"


def test_intake_defaults_family_for_unknown_reason():
    c = case_from_feedback({"event_id": "e9", "reason": "timing"})
    assert c.family == "no_event"


# ── the shipped example set loads and scores ──

def test_shipped_examples_load_and_score():
    cases = load_cases()  # tests/agent_fixtures/golden
    assert len(cases) >= 7
    # Every family in the examples has at least one case.
    fams = {c.family for c in cases}
    assert fams == set(SCENARIO_FAMILIES)
    card = run_scorecard(cases, provider="example", model="recorded", prompt_version="v0")
    # The curated examples are written to pass their own checks.
    assert card.event_accuracy == 1.0
    assert card.metrics()["n_scored"] == len(cases)


# ── prompt-version comparison (#218) ──

def _versioned_cases():
    good = "a courier drops a package at the door"
    bad = "an empty porch"
    return [
        _case(id="a", recorded_outputs={"v1": good, "v2": good}),
        _case(id="b", recorded_outputs={"v1": bad, "v2": good}),
        _case(id="c", recorded_outputs={"v1": good, "v2": bad}),
    ]


def test_recorded_outputs_are_picked_per_prompt_version():
    cases = _versioned_cases()
    v1 = run_scorecard(cases, provider="p", model="m", prompt_version="v1")
    v2 = run_scorecard(cases, provider="p", model="m", prompt_version="v2")
    assert {c["id"]: c["passed"] for c in v1.to_dict()["cases"]} == {"a": True, "b": False, "c": True}
    assert {c["id"]: c["passed"] for c in v2.to_dict()["cases"]} == {"a": True, "b": True, "c": False}
    # A version with no recorded output falls back to recorded_output.
    v3 = run_scorecard([_case()], provider="p", model="m", prompt_version="v3")
    assert v3.to_dict()["cases"] == [{"id": "t1", "passed": True}]


def test_compare_flags_case_regressions_even_when_rate_is_flat():
    from services.agent.eval.golden.harness import compare_scorecards

    cases = _versioned_cases()
    base = run_scorecard(cases, provider="p", model="m", prompt_version="v1").to_dict()
    cand = run_scorecard(cases, provider="p", model="m", prompt_version="v2").to_dict()
    cmp = compare_scorecards(base, cand)
    assert cmp.deltas["pass_rate"] == 0.0
    assert cmp.newly_failing == ["c"] and cmp.newly_passing == ["b"]
    assert not cmp.promotable
    md = cmp.to_markdown()
    assert "do not promote" in md and "`c`" in md


def test_compare_promotes_a_strict_improvement():
    from services.agent.eval.golden.harness import compare_scorecards

    good = "a courier drops a package at the door"
    cases = [_case(id="a", recorded_outputs={"v1": "an empty porch", "v2": good})]
    base = run_scorecard(cases, provider="p", model="m", prompt_version="v1").to_dict()
    cand = run_scorecard(cases, provider="p", model="m", prompt_version="v2").to_dict()
    cmp = compare_scorecards(base, cand)
    assert cmp.promotable and cmp.regressions == []
    assert cmp.deltas["pass_rate"] > 0


def test_scorecard_pins_registered_prompt_sha():
    from services.perception import prompt_registry as reg

    card = run_scorecard([_case()], provider="p", model="m", prompt_version="v1", prompt_key="live_caption")
    prov = card.to_dict()["provenance"]
    assert prov["prompt_key"] == "live_caption"
    assert prov["prompt_sha"] == reg.REGISTRY["live_caption"].sha
    with pytest.raises(ValueError):
        run_scorecard([_case()], provider="p", model="m", prompt_version="v99", prompt_key="live_caption")


def test_compare_cli_exit_code(tmp_path):
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import golden_eval

    cases = _versioned_cases()
    base = tmp_path / "base.json"
    cand = tmp_path / "cand.json"
    base.write_text(json.dumps(run_scorecard(cases, provider="p", model="m", prompt_version="v1").to_dict()))
    cand.write_text(json.dumps(run_scorecard(cases, provider="p", model="m", prompt_version="v2").to_dict()))
    assert golden_eval.main(["compare", str(base), str(cand)]) == 1
    assert golden_eval.main(["compare", str(base), str(base)]) == 0
