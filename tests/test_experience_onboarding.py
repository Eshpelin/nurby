"""Tests for per-user onboarding experience preferences (#204).

Preferences are personal presentation defaults only. They never grant
permissions, never target another account, and never activate a rule.
The suite guards:
  - Goal/place validation (monitoring goals need a place; after-hours is
    business only).
  - Audience derivation from role, and the immediate downgrade of a stored
    admin preference once the account is no longer an administrator.
  - The PUT guard that stops a restricted role from writing setup-focused
    or installation preferences (no target user id, no role/grant field).

Handlers are invoked directly with a stubbed AsyncSession, matching the
DB-free, unit-style convention of the rest of the suite.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.api.routes import auth as auth_routes
from shared.onboarding import (
    ExperiencePreferences,
    experience_response,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeUser:
    def __init__(self, *, role: str = "admin", preferences=None):
        self.id = uuid.uuid4()
        self.role = role
        self.onboarding_preferences = preferences


# ── preference validation ────────────────────────────────────────────

@pytest.mark.parametrize("goal", ["entrance", "deliveries"])
def test_home_monitoring_goal_requires_a_place(goal):
    # A monitoring goal with no place is ambiguous; reject it.
    with pytest.raises(ValueError):
        ExperiencePreferences(goal=goal, place=None)
    assert ExperiencePreferences(goal=goal, place="home").place == "home"


def test_after_hours_is_business_only():
    with pytest.raises(ValueError):
        ExperiencePreferences(goal="after_hours", place="home")
    assert ExperiencePreferences(goal="after_hours", place="business").goal == "after_hours"


@pytest.mark.parametrize("goal", ["review", "explore"])
def test_review_and_explore_need_no_place(goal):
    assert ExperiencePreferences(goal=goal).place is None


def test_preferences_reject_unknown_fields():
    # extra="forbid" keeps a role/grant field from ever riding along.
    with pytest.raises(ValueError):
        ExperiencePreferences.model_validate({"goal": "review", "role": "admin"})


# ── audience derivation ──────────────────────────────────────────────

def test_admin_keeps_saved_preferences():
    prefs = {"version": 1, "place": "business", "goal": "after_hours", "focus": "setup"}
    out = experience_response(_FakeUser(role="admin", preferences=prefs))
    assert out.audience == "administrator"
    assert out.preferences.goal == "after_hours"
    assert out.preferences.focus == "setup"


def test_viewer_is_downgraded_to_review_even_with_stored_admin_prefs():
    # A demoted admin must lose setup recommendations immediately, without a
    # migration or a rewrite of the stored blob.
    prefs = {"version": 1, "place": "business", "goal": "after_hours", "focus": "setup"}
    out = experience_response(_FakeUser(role="viewer", preferences=prefs))
    assert out.audience == "viewer"
    assert out.preferences.goal == "review"
    assert out.preferences.place is None
    assert out.preferences.focus == "daily"


def test_guardian_audience():
    out = experience_response(_FakeUser(role="guardian", preferences=None))
    assert out.audience == "guardian"


def test_admin_with_no_preferences_reports_none():
    out = experience_response(_FakeUser(role="admin", preferences=None))
    assert out.audience == "administrator"
    assert out.preferences is None


# ── save handler (authorization boundary) ────────────────────────────

def _db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def test_admin_saves_full_preferences():
    user = _FakeUser(role="admin", preferences=None)
    db = _db()
    body = ExperiencePreferences(version=1, place="business", goal="after_hours", focus="setup")

    out = _run(auth_routes.save_experience(body=body, current_user=user, db=db))

    assert user.onboarding_preferences == body.model_dump()
    assert out.preferences.goal == "after_hours"
    db.commit.assert_awaited()


def test_viewer_may_save_review_preference():
    user = _FakeUser(role="viewer", preferences=None)
    db = _db()
    body = ExperiencePreferences(version=1, place=None, goal="review", focus="daily")

    out = _run(auth_routes.save_experience(body=body, current_user=user, db=db))

    # Stored, and read back as the review audience default.
    assert out.audience == "viewer"
    assert out.preferences.goal == "review"
    db.commit.assert_awaited()


@pytest.mark.parametrize(
    "body",
    [
        ExperiencePreferences(version=1, place="home", goal="entrance", focus="daily"),
        ExperiencePreferences(version=1, place=None, goal="explore", focus="setup"),
    ],
)
def test_restricted_role_cannot_write_setup_or_installation_preferences(body):
    user = _FakeUser(role="viewer", preferences=None)
    db = _db()

    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.save_experience(body=body, current_user=user, db=db))

    assert ei.value.status_code == 403
    # Nothing was written or committed.
    assert user.onboarding_preferences is None
    db.commit.assert_not_awaited()


def test_get_experience_passes_through():
    prefs = {"version": 1, "place": "home", "goal": "entrance", "focus": "daily"}
    user = _FakeUser(role="admin", preferences=prefs)
    out = _run(auth_routes.get_experience(current_user=user))
    assert out.preferences.goal == "entrance"
    assert out.audience == "administrator"
