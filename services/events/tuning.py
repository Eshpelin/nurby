"""Reversible alert-tuning suggestions from reviewed history (#196).

Once users mark alerts ``useful`` / ``correct_but_not_useful`` / ``incorrect``
(#195), we can propose concrete, reversible changes that cut nuisance alerts
without silently changing what is monitored. This module is the analysis +
replay core: pure functions over plain dicts, so it is fully testable and has
no opinion on how the data is fetched or applied.

Hard rules from the issue, enforced here:

* No automatic silent changes. :func:`analyze` only *proposes*; nothing is
  applied without an explicit accept at the API layer.
* Every suggestion carries its sample size and the reviewed example events
  behind it (positive and negative), so a user sees the evidence.
* Replay (:func:`preview`) explains its own limit: it can show nuisance
  reduction on past events but cannot establish future recall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Minimum reviewed examples before we propose anything, so a one-off gripe
# never drives a config change.
MIN_SAMPLE = 3

REPLAY_CAVEAT = (
    "Replay shows how this change would have affected these past events. "
    "It cannot establish future recall, so review the affected examples."
)


@dataclass
class Suggestion:
    kind: str                       # "cooldown" | "confidence" | "schedule" | "demote"
    field: str                      # dotted path into the rule, e.g. "cooldown_seconds"
    current_value: Any
    proposed_value: Any
    rationale: str
    sample_size: int
    negative_example_ids: list[str] = field(default_factory=list)
    positive_example_ids: list[str] = field(default_factory=list)
    reversible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "field": self.field,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "rationale": self.rationale,
            "sample_size": self.sample_size,
            "negative_example_ids": self.negative_example_ids,
            "positive_example_ids": self.positive_example_ids,
            "reversible": self.reversible,
        }


def _confidence_of(ev: dict) -> float | None:
    payload = ev.get("payload") or {}
    for key in ("_matched_confidence", "confidence", "matched_confidence"):
        v = payload.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    v = ev.get("matched_confidence")
    return float(v) if isinstance(v, (int, float)) else None


def _hour(ev: dict) -> int | None:
    ts = ev.get("fired_at")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    return ts.hour if isinstance(ts, datetime) else None


def analyze(rule: dict[str, Any], events: list[dict[str, Any]]) -> list[Suggestion]:
    """Propose reversible tuning for ``rule`` from its reviewed ``events``.

    Each event dict: ``id``, ``fired_at`` (datetime or ISO), optional
    ``payload``, and ``feedback`` = ``{rating, reason}`` (may be absent for
    unreviewed events). Returns zero or more suggestions, most-supported
    first.
    """
    conditions = rule.get("conditions") or {}
    reviewed = [e for e in events if e.get("feedback")]

    def _with(reason=None, rating=None):
        out = []
        for e in reviewed:
            fb = e["feedback"]
            if rating and fb.get("rating") != rating:
                continue
            if reason and fb.get("reason") != reason:
                continue
            out.append(e)
        return out

    positives = [e["id"] for e in _with(rating="useful")]
    suggestions: list[Suggestion] = []

    # 1) Duplicates -> raise cooldown.
    dupes = _with(rating="incorrect", reason="duplicate")
    if len(dupes) >= MIN_SAMPLE:
        cur = int(rule.get("cooldown_seconds") or 0)
        proposed = max(cur * 2, cur + 300, 300)
        suggestions.append(Suggestion(
            kind="cooldown", field="cooldown_seconds",
            current_value=cur, proposed_value=proposed,
            rationale=(f"{len(dupes)} alerts were marked duplicate. A longer cooldown "
                       "collapses repeats of the same event."),
            sample_size=len(dupes),
            negative_example_ids=[e["id"] for e in dupes],
            positive_example_ids=positives,
        ))

    # 2) Wrong object -> raise the confidence gate.
    wrong_obj = _with(rating="incorrect", reason="wrong_object")
    if len(wrong_obj) >= MIN_SAMPLE:
        cur = conditions.get("min_confidence")
        base = float(cur) if isinstance(cur, (int, float)) else 0.5
        proposed = round(min(0.9, base + 0.15), 2)
        if proposed > base:
            suggestions.append(Suggestion(
                kind="confidence", field="conditions.min_confidence",
                current_value=cur, proposed_value=proposed,
                rationale=(f"{len(wrong_obj)} alerts were the wrong object. A higher "
                           "confidence gate drops low-certainty detections."),
                sample_size=len(wrong_obj),
                negative_example_ids=[e["id"] for e in wrong_obj],
                positive_example_ids=positives,
            ))

    # 3) Timing complaints -> propose a quiet window around the bad hours.
    timing = _with(rating="incorrect", reason="timing")
    if len(timing) >= MIN_SAMPLE:
        bad_hours = sorted({h for e in timing if (h := _hour(e)) is not None})
        if bad_hours:
            # Propose alerting only OUTSIDE the contiguous bad span: keep the
            # day window that excludes [min_bad, max_bad+1).
            lo, hi = bad_hours[0], bad_hours[-1]
            after = f"{(hi + 1) % 24:02d}:00"
            before = f"{lo:02d}:00"
            suggestions.append(Suggestion(
                kind="schedule", field="conditions.time_window",
                current_value={"time_after": conditions.get("time_after"),
                               "time_before": conditions.get("time_before")},
                proposed_value={"time_after": after, "time_before": before},
                rationale=(f"{len(timing)} alerts were flagged as bad timing, clustered "
                           f"between {lo:02d}:00 and {hi:02d}:59. Suggest muting that window."),
                sample_size=len(timing),
                negative_example_ids=[e["id"] for e in timing],
                positive_example_ids=positives,
            ))

    # 4) Correct-but-not-useful dominates -> demote severity.
    cbnu = _with(rating="correct_but_not_useful")
    if len(cbnu) >= MIN_SAMPLE and rule.get("severity") == "alert":
        if len(cbnu) >= len(_with(rating="useful")):
            suggestions.append(Suggestion(
                kind="demote", field="severity",
                current_value="alert", proposed_value="detection",
                rationale=(f"{len(cbnu)} alerts were correct but not useful, at least as "
                           "many as the useful ones. Keep them as quiet detections."),
                sample_size=len(cbnu),
                negative_example_ids=[e["id"] for e in cbnu],
                positive_example_ids=positives,
            ))

    suggestions.sort(key=lambda s: s.sample_size, reverse=True)
    return suggestions


def preview(suggestion: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay a proposed change over historical ``events``.

    Returns which events the change would have suppressed vs kept, and, using
    the reviewed labels, how many of the suppressed were nuisance (good) vs
    useful (a recall cost). Deterministic; touches no live state.
    """
    kind = suggestion.get("kind")
    suppressed: list[str] = []
    kept: list[str] = []

    ordered = sorted(events, key=lambda e: e.get("fired_at") or "")

    if kind == "cooldown":
        window = float(suggestion["proposed_value"])
        last_kept_ts: datetime | None = None
        for e in ordered:
            ts = e.get("fired_at")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = None
            if last_kept_ts is not None and ts is not None and (ts - last_kept_ts).total_seconds() < window:
                suppressed.append(e["id"])
            else:
                kept.append(e["id"])
                if ts is not None:
                    last_kept_ts = ts
    elif kind == "confidence":
        gate = float(suggestion["proposed_value"])
        for e in ordered:
            c = _confidence_of(e)
            # Unknown confidence is kept (conservative: never claim a silent drop).
            (suppressed if (c is not None and c < gate) else kept).append(e["id"])
    elif kind == "schedule":
        pv = suggestion["proposed_value"]
        after, before = pv.get("time_after"), pv.get("time_before")
        for e in ordered:
            h = _hour(e)
            inside = _within_hours(h, after, before) if h is not None else True
            (kept if inside else suppressed).append(e["id"])
    else:  # demote or unknown: not a suppression
        kept = [e["id"] for e in ordered]

    by_id = {e["id"]: e for e in events}

    def _label(eid: str) -> str | None:
        return (by_id.get(eid, {}).get("feedback") or {}).get("rating")

    nuisance_removed = [i for i in suppressed if _label(i) in ("incorrect", "correct_but_not_useful")]
    useful_lost = [i for i in suppressed if _label(i) == "useful"]

    return {
        "would_suppress": suppressed,
        "would_keep": kept,
        "nuisance_removed": nuisance_removed,
        "useful_lost": useful_lost,
        "caveat": REPLAY_CAVEAT,
    }


def _within_hours(hour: int, after: str | None, before: str | None) -> bool:
    """Is ``hour`` inside [after, before) by hour, wrapping midnight?"""
    a = int(after.split(":")[0]) if after else 0
    b = int(before.split(":")[0]) if before else 24
    if a <= b:
        return a <= hour < b
    return hour >= a or hour < b
