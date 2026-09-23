"""Reversible alert-tuning suggestions from reviewed history (#196)."""

from datetime import datetime, timedelta, timezone

import pytest

from services.events import tuning

NOW = datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc)  # 03:00, a "night" hour


def _ev(i, *, rating=None, reason=None, at=None, confidence=None):
    payload = {}
    if confidence is not None:
        payload["_matched_confidence"] = confidence
    return {
        "id": f"e{i}",
        "fired_at": at or NOW,
        "payload": payload,
        "feedback": ({"rating": rating, "reason": reason} if rating else None),
    }


# ── analyze ──

def test_below_min_sample_yields_nothing():
    rule = {"cooldown_seconds": 60, "conditions": {}, "severity": "alert"}
    events = [_ev(1, rating="incorrect", reason="duplicate")]
    assert tuning.analyze(rule, events) == []


def test_duplicates_suggest_higher_cooldown():
    rule = {"cooldown_seconds": 60, "conditions": {}, "severity": "alert"}
    events = [_ev(i, rating="incorrect", reason="duplicate") for i in range(4)]
    events.append(_ev(99, rating="useful"))
    sugg = tuning.analyze(rule, events)
    s = next(s for s in sugg if s.kind == "cooldown")
    assert s.field == "cooldown_seconds"
    assert s.proposed_value > 60
    assert s.sample_size == 4
    assert len(s.negative_example_ids) == 4
    assert s.positive_example_ids == ["e99"]
    assert s.reversible is True


def test_wrong_object_suggests_higher_confidence():
    rule = {"cooldown_seconds": 60, "conditions": {"min_confidence": 0.5}, "severity": "alert"}
    events = [_ev(i, rating="incorrect", reason="wrong_object") for i in range(3)]
    s = next(s for s in tuning.analyze(rule, events) if s.kind == "confidence")
    assert s.current_value == 0.5
    assert s.proposed_value == 0.65


def test_timing_suggests_quiet_window():
    rule = {"cooldown_seconds": 60, "conditions": {}, "severity": "alert"}
    # three bad-timing alerts at 02:00, 03:00, 04:00
    events = [
        _ev(i, rating="incorrect", reason="timing",
            at=NOW.replace(hour=h))
        for i, h in enumerate([2, 3, 4])
    ]
    s = next(s for s in tuning.analyze(rule, events) if s.kind == "schedule")
    # Alert only outside 02:00-04:59 -> after 05:00, before 02:00.
    assert s.proposed_value == {"time_after": "05:00", "time_before": "02:00"}


def test_correct_but_not_useful_suggests_demote():
    rule = {"cooldown_seconds": 60, "conditions": {}, "severity": "alert"}
    events = [_ev(i, rating="correct_but_not_useful") for i in range(3)]
    s = next(s for s in tuning.analyze(rule, events) if s.kind == "demote")
    assert s.current_value == "alert"
    assert s.proposed_value == "detection"


def test_demote_skipped_when_useful_dominates():
    rule = {"cooldown_seconds": 60, "conditions": {}, "severity": "alert"}
    events = [_ev(i, rating="correct_but_not_useful") for i in range(3)]
    events += [_ev(100 + i, rating="useful") for i in range(4)]
    assert not any(s.kind == "demote" for s in tuning.analyze(rule, events))


# ── preview (replay) ──

def test_preview_cooldown_suppresses_bursts():
    base = NOW
    events = [
        {"id": "a", "fired_at": base, "feedback": {"rating": "useful"}},
        {"id": "b", "fired_at": base + timedelta(seconds=30), "feedback": {"rating": "incorrect"}},
        {"id": "c", "fired_at": base + timedelta(seconds=600), "feedback": {"rating": "useful"}},
    ]
    out = tuning.preview({"kind": "cooldown", "proposed_value": 300}, events)
    assert out["would_suppress"] == ["b"]      # within 300s of a
    assert set(out["would_keep"]) == {"a", "c"}
    assert out["nuisance_removed"] == ["b"]    # b was incorrect -> good to drop
    assert out["useful_lost"] == []
    assert "future recall" in out["caveat"]


def test_preview_confidence_keeps_unknown_confidence():
    events = [
        {"id": "hi", "payload": {"_matched_confidence": 0.9}, "feedback": None},
        {"id": "lo", "payload": {"_matched_confidence": 0.3}, "feedback": {"rating": "incorrect"}},
        {"id": "unk", "payload": {}, "feedback": None},
    ]
    out = tuning.preview({"kind": "confidence", "proposed_value": 0.6}, events)
    assert out["would_suppress"] == ["lo"]
    assert set(out["would_keep"]) == {"hi", "unk"}  # unknown confidence never silently dropped


def test_preview_reports_useful_lost():
    base = NOW
    events = [
        {"id": "a", "fired_at": base, "feedback": {"rating": "useful"}},
        {"id": "b", "fired_at": base + timedelta(seconds=10), "feedback": {"rating": "useful"}},
    ]
    out = tuning.preview({"kind": "cooldown", "proposed_value": 300}, events)
    assert out["useful_lost"] == ["b"]  # a real recall cost is surfaced, not hidden
