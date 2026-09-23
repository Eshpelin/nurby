"""Evaluate scheduled expected-activity windows (#215).

This is deliberately a pure decision layer. A scheduler supplies the saved
expectation, observations found in the window, the last sighting, and the
coverage report for the same cameras. Missing evidence is never treated as a
violation when the cameras were degraded or unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Iterable


@dataclass(frozen=True)
class ExpectedWindow:
    """One local-time expectation evaluated by the scheduled worker."""

    subject_key: str
    weekdays: frozenset[int]
    start: time
    end: time
    camera_ids: frozenset[str] = frozenset()

    def applies_on(self, local_now: datetime) -> bool:
        return local_now.weekday() in self.weekdays


def evaluate_window(
    expectation: ExpectedWindow,
    *,
    local_now: datetime,
    sightings: Iterable[dict[str, Any]],
    last_seen: dict[str, Any] | None = None,
    coverage: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return a stable, notification-ready result for one expectation.

    Results are ``not_applicable`` (wrong weekday), ``satisfied`` (a matching
    sighting exists), ``unknown`` (the window was not fully observable), or
    ``violated`` (the window was covered and no sighting was found).
    Overnight windows are supported. The caller decides when the grace period
    has elapsed; this function only evaluates a closed window.
    """
    if not expectation.applies_on(local_now):
        return {"status": "not_applicable", "subject_key": expectation.subject_key}

    matching = [
        s for s in sightings
        if str(s.get("subject_key")) == expectation.subject_key
        and (not expectation.camera_ids or str(s.get("camera_id")) in expectation.camera_ids)
    ]
    if matching:
        return {
            "status": "satisfied",
            "subject_key": expectation.subject_key,
            "sighting": matching[-1],
        }

    gaps = []
    for item in coverage:
        if expectation.camera_ids and str(item.get("camera_id")) not in expectation.camera_ids:
            continue
        if item.get("evidence_state") in {"outage", "degraded", "unprocessed"}:
            gaps.append({
                "camera_id": item.get("camera_id"),
                "camera_name": item.get("camera_name"),
                "evidence_state": item.get("evidence_state"),
                "gaps": item.get("gaps", []),
            })
    if gaps:
        return {
            "status": "unknown",
            "subject_key": expectation.subject_key,
            "last_seen": last_seen,
            "coverage_gaps": gaps,
            "reason": "Expected activity could not be confirmed because coverage was incomplete.",
        }
    return {
        "status": "violated",
        "subject_key": expectation.subject_key,
        "last_seen": last_seen,
        "coverage_gaps": [],
        "reason": "No matching sighting was found during the covered expectation window.",
    }
