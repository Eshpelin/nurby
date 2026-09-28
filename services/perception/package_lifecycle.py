"""Noise-resistant package presence lifecycle decisions.

This module deliberately contains no database or notification code. A camera
pipeline can feed it observations, persist the returned state, and decide
which product surface to update. Keeping the transition contract pure makes
wind, occlusion, and detector flapping testable without a live camera.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID


class PackageState(StrEnum):
    DELIVERED = "delivered"
    WAITING = "waiting"
    GONE = "gone"


class RemovalKind(StrEnum):
    PICKED_UP_BY_PERSON = "picked_up_by_person"
    REMOVED_UNOBSERVED = "removed_unobserved"


@dataclass(frozen=True)
class PackageEvidence:
    """One normalized package presence check from a camera or VLM."""

    observed_at: datetime
    present: bool
    observation_id: UUID | None = None
    remover_person_id: UUID | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class PackageLifecycle:
    """Current lifecycle plus evidence used to explain a transition."""

    state: PackageState = PackageState.DELIVERED
    last_present_at: datetime | None = None
    absent_checks: int = 0
    gone_at: datetime | None = None
    removal_kind: RemovalKind | None = None
    remover_person_id: UUID | None = None
    last_observation_id: UUID | None = None


def advance(
    lifecycle: PackageLifecycle,
    evidence: PackageEvidence,
    *,
    required_absent_checks: int = 2,
    minimum_absence: timedelta = timedelta(minutes=2),
) -> PackageLifecycle:
    """Apply one check without oscillating on a single occluded frame.

    Presence always resets an unconfirmed absence streak and moves a newly
    delivered package into ``waiting``. Absence only becomes ``gone`` after
    the configured consecutive checks and elapsed time. A known remover is
    retained as evidence, but callers must still present the result as a
    possible pickup rather than a confirmed handover.
    """
    if required_absent_checks < 1:
        raise ValueError("required_absent_checks must be at least 1")
    if evidence.observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    if lifecycle.state == PackageState.GONE:
        return lifecycle

    if evidence.present:
        return replace(
            lifecycle,
            # The first positive check is the delivery transition. A later
            # positive check means the delivered package is still waiting.
            state=(
                PackageState.WAITING
                if lifecycle.last_present_at is not None
                else PackageState.DELIVERED
            ),
            last_present_at=evidence.observed_at,
            absent_checks=0,
            last_observation_id=evidence.observation_id,
        )

    absent_checks = lifecycle.absent_checks + 1
    last_present_at = lifecycle.last_present_at
    enough_time = (
        last_present_at is not None
        and evidence.observed_at >= last_present_at + minimum_absence
    )
    if absent_checks < required_absent_checks or not enough_time:
        return replace(
            lifecycle,
            absent_checks=absent_checks,
            last_observation_id=evidence.observation_id,
        )

    removal_kind = (
        RemovalKind.PICKED_UP_BY_PERSON
        if evidence.remover_person_id is not None
        else RemovalKind.REMOVED_UNOBSERVED
    )
    return replace(
        lifecycle,
        state=PackageState.GONE,
        absent_checks=absent_checks,
        gone_at=evidence.observed_at,
        removal_kind=removal_kind,
        remover_person_id=evidence.remover_person_id,
        last_observation_id=evidence.observation_id,
    )
