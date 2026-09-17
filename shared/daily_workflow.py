"""Audience-specific daily priorities (#204 phase 3).

After onboarding, each person should return to a workspace that shows the
few things worth doing today, ordered, and honest about what is blocked.
This is pure and read-only: it never creates or rewrites a rule, and a
paused workflow simply stops nudging. Capability-awareness means a flow
that needs an AI provider or a delivery channel is surfaced as blocked
rather than silently recommended.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Audience = Literal["administrator", "viewer", "guardian"]


class Capabilities(BaseModel):
    has_real_camera: bool = False
    has_provider: bool = False
    has_channel: bool = False
    has_enabled_rule: bool = False
    verified: bool = False


class DailyPriority(BaseModel):
    key: str
    title: str
    detail: str
    href: str
    # Set when the action cannot yet succeed. The item is still shown so the
    # person knows the prerequisite, never hidden as if it did not apply.
    blocked_reason: str | None = None


class DailyWorkflow(BaseModel):
    audience: Audience
    paused: bool = False
    place_label: str | None = None
    priorities: list[DailyPriority]


_DETECTION = {"entrance", "deliveries", "after_hours"}


def _admin_priorities(goal: str, focus: str, caps: Capabilities) -> list[DailyPriority]:
    items: list[DailyPriority] = []

    if not caps.has_real_camera:
        items.append(DailyPriority(
            key="connect-camera",
            title="Connect a real camera",
            detail="A demo camera cannot produce a real, verified alert.",
            href="/?setup=camera",
        ))

    if focus == "setup":
        items.append(DailyPriority(
            key="system-health",
            title="Check system health",
            detail="Review camera status, recording coverage and worker health.",
            href="/settings",
        ))

    if goal in _DETECTION:
        needs_provider = goal == "after_hours" and not caps.has_provider
        if not caps.verified:
            items.append(DailyPriority(
                key="verify-activation",
                title="Finish verifying your first alert",
                detail="Configure the rule, trigger the camera, and confirm the clip.",
                href="/",
                blocked_reason=(
                    "Connect an AI provider for the after-hours check" if needs_provider
                    else "Add a way to be notified" if not caps.has_channel
                    else None
                ),
            ))
        else:
            items.append(DailyPriority(
                key="review-activity",
                title="Review today's activity",
                detail="Open the timeline and scan what your rule caught.",
                href="/timeline",
            ))
            items.append(DailyPriority(
                key="tune-noisy-rules",
                title="Quiet any noisy rules",
                detail="Snooze or edit rules that alerted too often. Your saved rules are never changed automatically.",
                href="/rules",
            ))
    elif goal == "review":
        items.append(DailyPriority(
            key="review-recent",
            title="Review recent footage",
            detail="Open the timeline, pick a camera and time.",
            href="/timeline",
        ))
    else:  # explore
        items.append(DailyPriority(
            key="pick-goal",
            title="Choose a monitoring goal",
            detail="Pick a goal from your setup card when you are ready.",
            href="/",
        ))

    return items


def daily_workflow(
    *,
    audience: Audience,
    goal: str | None,
    focus: str = "daily",
    paused: bool = False,
    place_label: str | None = None,
    caps: Capabilities | None = None,
) -> DailyWorkflow:
    caps = caps or Capabilities()

    if audience == "guardian":
        return DailyWorkflow(audience=audience, place_label=place_label, priorities=[DailyPriority(
            key="guardian-portal",
            title="Open your dependant updates",
            detail="Review updates for the people linked to your account.",
            href="/guardian",
        )])

    if audience == "viewer":
        return DailyWorkflow(audience=audience, place_label=place_label, priorities=[DailyPriority(
            key="review-shared",
            title="Review shared activity",
            detail="Look through activity from the cameras shared with you.",
            href="/timeline",
        )])

    # Administrator. A paused workflow shows only how to resume; nothing is
    # changed on the rules while paused.
    if paused:
        return DailyWorkflow(audience=audience, paused=True, place_label=place_label, priorities=[DailyPriority(
            key="resume",
            title="Daily guidance paused",
            detail="Your rules keep running. Resume to see daily priorities again.",
            href="/",
        )])

    return DailyWorkflow(
        audience=audience,
        place_label=place_label,
        priorities=_admin_priorities(goal or "explore", focus, caps),
    )
