"""Audience-specific daily workflow priorities (#204 phase 3).

Guards that daily guidance is capability-aware, honest about blocked
prerequisites, read-only (never rewrites rules), and respects a paused
workflow. Also covers the new place_label / paused preference fields and
the endpoint wiring.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from services.api.routes import auth as auth_routes
from shared.daily_workflow import Capabilities, daily_workflow
from shared.onboarding import ExperiencePreferences, experience_response


def _run(coro):
    return asyncio.run(coro)


def _keys(wf):
    return [p.key for p in wf.priorities]


# ── preference fields ────────────────────────────────────────────────

def test_place_label_is_trimmed_and_optional():
    assert ExperiencePreferences(goal="review", place_label="  Front shop  ").place_label == "Front shop"
    assert ExperiencePreferences(goal="review", place_label="   ").place_label is None
    assert ExperiencePreferences(goal="review").place_label is None


def test_place_label_length_bounded():
    with pytest.raises(ValueError):
        ExperiencePreferences(goal="review", place_label="x" * 81)


def test_paused_defaults_false_and_persists():
    prefs = ExperiencePreferences(goal="entrance", place="home", paused=True)
    assert prefs.paused is True
    assert ExperiencePreferences(goal="entrance", place="home").paused is False


# ── audience routing ─────────────────────────────────────────────────

def test_viewer_gets_review_only():
    wf = daily_workflow(audience="viewer", goal=None)
    assert _keys(wf) == ["review-shared"]


def test_guardian_gets_portal_only():
    wf = daily_workflow(audience="guardian", goal=None)
    assert _keys(wf) == ["guardian-portal"]


def test_paused_admin_shows_only_resume_and_reassures_rules_run():
    wf = daily_workflow(audience="administrator", goal="entrance", paused=True, caps=Capabilities(has_real_camera=True))
    assert _keys(wf) == ["resume"]
    assert wf.paused is True
    assert "keep running" in wf.priorities[0].detail


# ── capability-awareness ─────────────────────────────────────────────

def test_no_real_camera_is_the_first_priority():
    wf = daily_workflow(audience="administrator", goal="entrance", caps=Capabilities())
    assert wf.priorities[0].key == "connect-camera"


def test_after_hours_without_provider_is_blocked_not_hidden():
    wf = daily_workflow(audience="administrator", goal="after_hours", caps=Capabilities(has_real_camera=True))
    verify = next(p for p in wf.priorities if p.key == "verify-activation")
    assert verify.blocked_reason == "Connect an AI provider for the after-hours check"


def test_detection_without_channel_is_blocked_on_delivery():
    wf = daily_workflow(audience="administrator", goal="entrance", caps=Capabilities(has_real_camera=True, has_provider=True))
    verify = next(p for p in wf.priorities if p.key == "verify-activation")
    assert verify.blocked_reason == "Add a way to be notified"


def test_verified_account_gets_daily_review_and_noise_control():
    caps = Capabilities(has_real_camera=True, has_channel=True, has_enabled_rule=True, verified=True)
    wf = daily_workflow(audience="administrator", goal="entrance", caps=caps)
    keys = _keys(wf)
    assert "review-activity" in keys and "tune-noisy-rules" in keys
    assert "verify-activation" not in keys
    # The tuning item promises rules are never auto-changed.
    tune = next(p for p in wf.priorities if p.key == "tune-noisy-rules")
    assert "never changed automatically" in tune.detail


def test_setup_focus_surfaces_system_health():
    caps = Capabilities(has_real_camera=True, has_channel=True, verified=True)
    wf = daily_workflow(audience="administrator", goal="entrance", focus="setup", caps=caps)
    assert "system-health" in _keys(wf)


# ── endpoint wiring ──────────────────────────────────────────────────

class _User:
    def __init__(self, role="admin", prefs=None):
        self.id = uuid.uuid4()
        self.role = role
        self.onboarding_preferences = prefs


def test_endpoint_passes_preferences_and_caps(monkeypatch):
    caps = Capabilities(has_real_camera=True, has_channel=True, verified=True)
    monkeypatch.setattr(auth_routes, "_account_capabilities", AsyncMock(return_value=caps))
    user = _User(prefs={"version": 1, "place": "home", "goal": "entrance", "focus": "daily", "place_label": "Home", "paused": False})

    wf = _run(auth_routes.get_daily_workflow(current_user=user, db=AsyncMock()))
    assert wf.audience == "administrator"
    assert wf.place_label == "Home"
    assert "review-activity" in _keys(wf)


def test_endpoint_downgrades_a_viewer(monkeypatch):
    monkeypatch.setattr(auth_routes, "_account_capabilities", AsyncMock(return_value=Capabilities()))
    # A demoted admin with stored setup prefs is still only a reviewer.
    user = _User(role="viewer", prefs={"version": 1, "place": "business", "goal": "after_hours", "focus": "setup"})
    resp = experience_response(user)
    assert resp.audience == "viewer"

    wf = _run(auth_routes.get_daily_workflow(current_user=user, db=AsyncMock()))
    assert _keys(wf) == ["review-shared"]
