"""Onboarding validation metrics (#204 phase 4).

Aggregate, install-wide counts that let us judge whether goal-based
onboarding works: which goals people pick, how many reach a verified first
useful result, how long it took, and how many stall. Pure and county: it
takes plain rows and returns numbers, no PII beyond aggregates, and is
unit-testable without a database.

Time to first useful result is measured from server-ready
(``install_ready_at``) to the confirmed-useful moment, deliberately apart
from install duration. A test that only ever fired against the demo camera
is counted as synthetic-only and never as verified.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from pydantic import BaseModel


class PreferenceRow(BaseModel):
    goal: str | None = None
    place: str | None = None
    focus: str = "daily"
    paused: bool = False


class MilestoneRow(BaseModel):
    goal: str
    configured_at: datetime | None = None
    confirmed_useful_at: datetime | None = None
    install_ready_at: datetime | None = None
    test_kind: str | None = None
    delivery_ok: bool | None = None


def _verified(m: MilestoneRow) -> bool:
    return m.test_kind == "real" and m.delivery_ok is True and m.confirmed_useful_at is not None


class OnboardingMetrics(BaseModel):
    users_with_preferences: int
    goal_counts: dict[str, int]
    place_counts: dict[str, int]
    focus_counts: dict[str, int]
    paused_count: int

    configured_count: int
    verified_count: int
    verified_rate: float  # verified / configured, 0 when nothing configured
    abandoned_count: int  # configured, not verified, older than the window
    synthetic_only_count: int  # tested only against the demo camera
    median_seconds_to_first_useful: float | None
    verified_by_goal: dict[str, int]
    # First-run wizard funnel counters (#293), aggregated from the
    # onboarding_funnel app setting. Absent keys mean zero.
    funnel: dict[str, int] = {}


FUNNEL_EVENTS = ("wizard_shown", "magic_clicked", "manual_clicked", "wizard_completed")


def normalize_funnel_event(event: object) -> str | None:
    """Return the canonical funnel event name, or None for anything that
    is not one. Pure, for tests."""
    if isinstance(event, str) and event in FUNNEL_EVENTS:
        return event
    return None


def bump_funnel(counts: dict, event: str) -> dict:
    """Return counts with `event` incremented (does not mutate the input).
    Pure, for tests."""
    return {**counts, event: int(counts.get(event, 0)) + 1}


def _bump(counter: dict[str, int], key: str | None) -> None:
    if key is None:
        key = "unset"
    counter[key] = counter.get(key, 0) + 1


def compute_metrics(
    preferences: list[PreferenceRow],
    milestones: list[MilestoneRow],
    *,
    now: datetime,
    abandon_after_days: int = 7,
    funnel: dict[str, int] | None = None,
) -> OnboardingMetrics:
    goal_counts: dict[str, int] = {}
    place_counts: dict[str, int] = {}
    focus_counts: dict[str, int] = {}
    paused_count = 0
    for p in preferences:
        _bump(goal_counts, p.goal)
        _bump(place_counts, p.place)
        _bump(focus_counts, p.focus)
        if p.paused:
            paused_count += 1

    configured_count = 0
    verified_count = 0
    abandoned_count = 0
    synthetic_only_count = 0
    verified_by_goal: dict[str, int] = {}
    durations: list[float] = []
    cutoff = now - timedelta(days=abandon_after_days)

    for m in milestones:
        is_configured = m.configured_at is not None
        if is_configured:
            configured_count += 1
        if _verified(m):
            verified_count += 1
            _bump(verified_by_goal, m.goal)
            if m.install_ready_at is not None:
                durations.append(max(0.0, (m.confirmed_useful_at - m.install_ready_at).total_seconds()))
        else:
            # Stalled: configured long enough ago and still not verified.
            if is_configured and m.configured_at < cutoff:
                abandoned_count += 1
            # Reached a synthetic test but never a real verified one.
            if m.test_kind == "synthetic" and m.confirmed_useful_at is None:
                synthetic_only_count += 1

    verified_rate = (verified_count / configured_count) if configured_count else 0.0

    return OnboardingMetrics(
        users_with_preferences=len(preferences),
        goal_counts=goal_counts,
        place_counts=place_counts,
        focus_counts=focus_counts,
        paused_count=paused_count,
        configured_count=configured_count,
        verified_count=verified_count,
        verified_rate=round(verified_rate, 4),
        abandoned_count=abandoned_count,
        synthetic_only_count=synthetic_only_count,
        median_seconds_to_first_useful=round(median(durations), 2) if durations else None,
        verified_by_goal=verified_by_goal,
        funnel=funnel or {},
    )
