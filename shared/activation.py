"""Verified first-useful-result tracking (#193 / #204 phase 2).

A configured channel or an enabled rule is *not* activation. Verified
activation requires all three, in order:

  1. ``configured``  a rule exists, is enabled, points at a camera and has
     a delivery action. Necessary, never sufficient.
  2. ``tested``      a real event fired on that rule and its alert was
     delivered. A test off the demo camera is labelled ``synthetic`` and
     never counts as verified.
  3. ``confirmed``   the person opened the exact clip and confirmed it was
     the thing they wanted to see.

This module is pure. The state is computed from timestamps and flags that
the API and the event engine persist onto an ``ActivationMilestone`` row,
so the logic is unit-testable without a database. The goal → starter map
reuses ``shared.rule_starters`` so a draft rule is real rule data, never a
second definition that could drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

# Goals that can be driven to a verified detection result. ``review`` and
# ``explore`` are deliberately absent: they open the timeline and never
# create or test a rule, so they have no activation to verify.
GOAL_STARTER: dict[str, str] = {
    "entrance": "someone-at-the-door",
    "deliveries": "package-arrived",
    "after_hours": "someone-at-night",
}

Step = Literal["configured", "tested", "confirmed"]
TestKind = Literal["synthetic", "real"]

# Action types that actually deliver an alert somewhere. A rule with none
# of these is configured to detect but not to reach anyone.
DELIVERY_ACTIONS = {"notify", "email", "telegram", "webhook", "api_call", "device", "broadcast", "speak"}


class DraftRuleRequest(BaseModel):
    goal: str
    camera_id: str | None = None


class ConfigureRequest(BaseModel):
    goal: str
    rule_id: str


class ConfirmRequest(BaseModel):
    goal: str
    event_id: UUID


class RetestRequest(BaseModel):
    goal: str


def clear_activation_test(milestone) -> None:
    """A new configuration or test cannot inherit someone else's evidence."""
    milestone.tested_at = None
    milestone.test_kind = None
    milestone.delivery_ok = None
    milestone.event_id = None
    milestone.confirmed_useful_at = None


def starter_key_for_goal(goal: str) -> str | None:
    """The starter rule key a goal scaffolds, or None for a no-rule goal."""
    return GOAL_STARTER.get(goal)


class ActivationStepView(BaseModel):
    key: Step
    done: bool
    # A test done only against the demo camera is real progress but is
    # flagged so the UI never presents it as a proven live result.
    synthetic: bool = False


class ActivationView(BaseModel):
    goal: str
    event_id: str | None = None
    rule_id: str | None = None
    camera_id: str | None = None
    draft_rule_id: str | None = None
    steps: list[ActivationStepView]
    # True only for a real (non-synthetic) delivered event the user
    # confirmed. This is the single flag any UI may use to claim success.
    verified: bool
    # None until every step is done; then the next step to act on.
    next_step: Step | None
    test_kind: TestKind | None = None
    # Server-ready-to-first-useful-result, measured apart from install time.
    seconds_to_first_useful: float | None = None


def _elapsed(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def compute_activation(
    *,
    goal: str,
    event_id: str | None = None,
    rule_id: str | None = None,
    camera_id: str | None = None,
    draft_rule_id: str | None = None,
    configured_at: datetime | None = None,
    tested_at: datetime | None = None,
    confirmed_useful_at: datetime | None = None,
    test_kind: TestKind | None = None,
    delivery_ok: bool | None = None,
    install_ready_at: datetime | None = None,
) -> ActivationView:
    """Fold the persisted milestone fields into the view the UI renders.

    The ordering guard matters: ``tested`` cannot be done unless a delivery
    actually succeeded, and ``confirmed`` cannot outrank a missing test.
    """
    configured = configured_at is not None
    # A test only counts once its delivery succeeded. A fired event whose
    # alert never left the box is not a tested delivery path.
    tested = configured and tested_at is not None and delivery_ok is True
    synthetic = test_kind == "synthetic"
    confirmed = tested and confirmed_useful_at is not None

    steps = [
        ActivationStepView(key="configured", done=configured),
        ActivationStepView(key="tested", done=tested, synthetic=tested and synthetic),
        ActivationStepView(key="confirmed", done=confirmed),
    ]

    verified = confirmed and test_kind == "real"
    if not configured:
        next_step: Step | None = "configured"
    elif not tested:
        next_step = "tested"
    elif not confirmed or not verified:
        # A synthetic-only confirmation still needs a real test to verify.
        next_step = "confirmed" if not confirmed else "tested"
    else:
        next_step = None

    return ActivationView(
        goal=goal,
        event_id=event_id,
        rule_id=rule_id,
        camera_id=camera_id,
        draft_rule_id=draft_rule_id,
        steps=steps,
        verified=verified,
        next_step=next_step,
        test_kind=test_kind,
        seconds_to_first_useful=_elapsed(install_ready_at, confirmed_useful_at) if verified else None,
    )


class ActivationList(BaseModel):
    milestones: list[ActivationView]
