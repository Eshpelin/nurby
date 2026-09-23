"""Scoring for the golden set (#214).

Two layers:

* **Deterministic checks** - no model needed, no cost, no flakiness. Event
  presence/absence accuracy against the closed-vocabulary ``event_present``
  label, plus ``must_include`` / ``must_not_include`` substring gates. These
  are the trustworthy backbone of a scorecard.
* **LLM-as-judge** - a :class:`Judge` scores open-ended faithfulness /
  correctness that substrings cannot capture. The judge is pluggable so the
  suite runs offline and deterministically in tests and CI with
  :class:`KeywordJudge`, and swaps to a fixed real judge model locally.

Keeping the judge behind a protocol means a scorecard always records *which*
judge produced it, so an accuracy claim is attributable and reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol

from services.agent.eval.golden.schema import GoldenCase


def infer_event_present(output: str) -> bool:
    """Cheap heuristic: does a caption/answer assert that nothing happened?

    Used only as a fallback when a caller has no structured presence signal.
    A handful of explicit "no event" phrasings map to absence; everything
    else is treated as an asserted event. Deliberately conservative.
    """
    text = (output or "").strip().lower()
    if not text:
        return False
    negatives = (
        "no event", "nothing happened", "no activity", "no motion",
        "no one", "nobody", "empty", "quiet", "all clear", "no people",
        "no person", "no vehicles", "no cars", "scene is unchanged",
        "no recording", "cannot be answered", "nothing clearly visible",
    )
    return not any(n in text for n in negatives)


def _contains(haystack: str, needle: str) -> bool:
    return re.search(re.escape(needle), haystack, flags=re.IGNORECASE) is not None


@dataclass
class CaseScore:
    case_id: str
    family: str
    kind: str
    event_correct: bool
    vocab_ok: bool          # must_include present AND must_not_include absent
    judge_score: float      # 0..1 faithfulness/correctness from the judge
    judge_threshold: float  # the bar this judge considers "faithful enough"
    detail: str = ""

    @property
    def passed(self) -> bool:
        """A case passes when presence is right, no vocab gate tripped, and
        the judge score clears the judge's own bar."""
        return self.event_correct and self.vocab_ok and self.judge_score >= self.judge_threshold


class Judge(Protocol):
    """Scores a candidate against a reference on [0, 1].

    ``pass_threshold`` is the score at or above which the judge considers a
    candidate faithful enough to pass. It belongs to the judge because the
    right bar depends on the scoring method: token overlap (KeywordJudge)
    lands lower than a calibrated LLM judge for the same paraphrase.
    """

    name: str
    pass_threshold: float

    def score(self, *, question: str | None, reference: str, candidate: str) -> tuple[float, str]:
        ...


class KeywordJudge:
    """Deterministic, offline judge: token overlap between candidate and
    reference (Jaccard over lowercased word sets, ignoring tiny stopwords).

    Not as nuanced as an LLM judge, but reproducible and free, which is what
    CI and unit tests need. A scorecard records ``name`` so nobody mistakes a
    KeywordJudge run for a real-judge accuracy claim.
    """

    name = "keyword-jaccard-v1"
    # Jaccard over paraphrases is naturally low (a good paraphrase often
    # overlaps ~0.2-0.4), so the bar is lower than a calibrated LLM judge's.
    pass_threshold = 0.2
    _STOP = frozenset("a an the is are was were of to in on at and or with no not".split())

    def _tokens(self, s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in self._STOP}

    def score(self, *, question: str | None, reference: str, candidate: str) -> tuple[float, str]:
        ref, cand = self._tokens(reference), self._tokens(candidate)
        if not ref and not cand:
            return 1.0, "both empty"
        if not ref or not cand:
            return 0.0, "one side empty"
        inter = ref & cand
        union = ref | cand
        j = len(inter) / len(union)
        return j, f"jaccard={j:.2f} ({len(inter)}/{len(union)})"


class LLMJudge:
    """LLM-as-judge with a *fixed* judge model (issue #214).

    The judge model is pinned so a scorecard is reproducible and the judge is
    never the same model under evaluation (which would flatter itself). The
    call is injected as ``ask(prompt) -> str`` so this is unit-testable with a
    fake and provider-agnostic: wire ``ask`` to a fixed model
    (e.g. a call into ``services.events.actions._call_vlm`` with a pinned
    provider/model) for a real run.

    The judge is asked for a single number in [0, 1]; we parse the first
    float. A parse failure scores 0.0 with the raw reply in the detail, so a
    flaky judge degrades to "fail", never to a false pass.
    """

    def __init__(self, ask: "Callable[[str], str]", *, model: str, pass_threshold: float = 0.6):
        self._ask = ask
        self.name = f"llm-judge:{model}"
        self.pass_threshold = pass_threshold

    def score(self, *, question: str | None, reference: str, candidate: str) -> tuple[float, str]:
        prompt = (
            "You are grading how faithfully a camera caption/answer matches the "
            "known-correct reference. Reply with ONLY a number from 0.0 (wrong or "
            "unfaithful) to 1.0 (fully faithful).\n\n"
            + (f"Question: {question}\n" if question else "")
            + f"Reference (correct): {reference}\nCandidate (to grade): {candidate}\nScore:"
        )
        try:
            reply = self._ask(prompt)
            m = re.search(r"[01](?:\.\d+)?|\.\d+", reply or "")
            if not m:
                return 0.0, f"unparseable judge reply: {reply!r:.80}"
            val = max(0.0, min(1.0, float(m.group(0))))
            return val, f"llm judge={val:.2f}"
        except Exception as e:
            return 0.0, f"judge error: {type(e).__name__}: {e}"


def score_case(case: GoldenCase, output: str, judge: Judge) -> CaseScore:
    """Score one case's ``output`` (a caption or an Ask answer)."""
    truth = case.truth

    predicted_present = infer_event_present(output)
    event_correct = predicted_present == truth.event_present

    missing = [s for s in truth.must_include if not _contains(output, s)]
    forbidden = [s for s in truth.must_not_include if _contains(output, s)]
    vocab_ok = not missing and not forbidden

    judge_score, judge_detail = judge.score(
        question=case.question, reference=truth.reference, candidate=output
    )

    bits = [judge_detail]
    if not event_correct:
        bits.append(f"event: said_present={predicted_present} truth={truth.event_present}")
    if missing:
        bits.append(f"missing={missing}")
    if forbidden:
        bits.append(f"forbidden={forbidden}")

    return CaseScore(
        case_id=case.id,
        family=case.family,
        kind=case.kind,
        event_correct=event_correct,
        vocab_ok=vocab_ok,
        judge_score=judge_score,
        judge_threshold=getattr(judge, "pass_threshold", 0.6),
        detail="; ".join(b for b in bits if b),
    )
