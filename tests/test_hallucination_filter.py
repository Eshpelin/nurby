"""Unit tests for the audio hallucination filter.

Pure-function tests. One per filter rule plus a happy path. Reason
strings are part of the metrics contract, so we assert on them
directly. If a string changes, the metrics dashboard breaks.
"""

from __future__ import annotations

from services.perception.audio.hallucination_filter import filter_hallucination
from services.perception.audio.types import TranscriptResult


def _result(**overrides) -> TranscriptResult:
    base = dict(
        text="hello there how are you",
        language="en",
        provider="mock",
        model="m",
        no_speech_prob=0.1,
        avg_logprob=-0.3,
        duration_ms=2000,
    )
    base.update(overrides)
    return TranscriptResult(**base)


def test_keeps_normal_speech():
    keep, reason = filter_hallucination(_result())
    assert keep is True
    assert reason == "ok"


def test_drops_empty():
    keep, reason = filter_hallucination(_result(text=""))
    assert keep is False
    assert reason == "empty"


def test_drops_provider_error():
    keep, reason = filter_hallucination(_result(error="boom"))
    assert keep is False
    assert reason == "provider_error"


def test_drops_high_no_speech_prob():
    keep, reason = filter_hallucination(_result(no_speech_prob=0.9))
    assert keep is False
    assert reason == "no_speech_prob"


def test_drops_low_avg_logprob():
    keep, reason = filter_hallucination(_result(avg_logprob=-2.0))
    assert keep is False
    assert reason == "avg_logprob"


def test_drops_too_short_single_token():
    keep, reason = filter_hallucination(
        _result(text="ok", duration_ms=200)
    )
    assert keep is False
    assert reason == "too_short"


def test_drops_blocklist_phrase():
    keep, reason = filter_hallucination(_result(text="Thanks for watching!"))
    assert keep is False
    assert reason == "blocklist"


def test_drops_repetition_loop():
    keep, reason = filter_hallucination(
        _result(text="the the the the the the the")
    )
    assert keep is False
    assert reason == "repetition"


def test_long_short_token_phrase_with_diversity_kept():
    # Multi-token short phrases without repetition should still pass.
    keep, reason = filter_hallucination(_result(text="open the door now"))
    assert keep is True
    assert reason == "ok"


def test_blocklist_is_case_and_punct_insensitive():
    keep, reason = filter_hallucination(_result(text="MUSIC."))
    assert keep is False
    assert reason == "blocklist"
