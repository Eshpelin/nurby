"""Onboarding validation metrics and isolation (#204 phase 4).

Covers the aggregate metrics maths, the admin metrics endpoint wiring, and
the account-isolation property that per-user activation reads are scoped by
the caller's own id.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.api.routes import auth as auth_routes
from shared.onboarding_metrics import MilestoneRow, PreferenceRow, compute_metrics


def _run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


# ── pure aggregation ─────────────────────────────────────────────────

def test_empty_metrics_are_zero_not_error():
    m = compute_metrics([], [], now=NOW)
    assert m.users_with_preferences == 0
    assert m.verified_rate == 0.0
    assert m.median_seconds_to_first_useful is None


def test_goal_place_focus_and_pause_counts():
    prefs = [
        PreferenceRow(goal="entrance", place="home", focus="daily"),
        PreferenceRow(goal="entrance", place="business", focus="setup", paused=True),
        PreferenceRow(goal="review", place=None, focus="daily"),
    ]
    m = compute_metrics(prefs, [], now=NOW)
    assert m.goal_counts == {"entrance": 2, "review": 1}
    assert m.place_counts == {"home": 1, "business": 1, "unset": 1}
    assert m.focus_counts == {"daily": 2, "setup": 1}
    assert m.paused_count == 1


def test_verified_rate_and_median_time():
    ms = [
        MilestoneRow(goal="entrance", configured_at=NOW - timedelta(days=1),
                     install_ready_at=NOW - timedelta(minutes=6), confirmed_useful_at=NOW,
                     test_kind="real", delivery_ok=True),
        MilestoneRow(goal="deliveries", configured_at=NOW - timedelta(days=1),
                     install_ready_at=NOW - timedelta(minutes=4), confirmed_useful_at=NOW,
                     test_kind="real", delivery_ok=True),
        MilestoneRow(goal="after_hours", configured_at=NOW - timedelta(days=1)),
    ]
    m = compute_metrics(ms and [], ms, now=NOW)
    assert m.configured_count == 3
    assert m.verified_count == 2
    assert m.verified_rate == round(2 / 3, 4)
    # medians of 360s and 240s
    assert m.median_seconds_to_first_useful == 300.0
    assert m.verified_by_goal == {"entrance": 1, "deliveries": 1}


def test_synthetic_and_undelivered_do_not_count_as_verified():
    ms = [
        MilestoneRow(goal="entrance", configured_at=NOW, test_kind="synthetic", delivery_ok=True, confirmed_useful_at=NOW),
        MilestoneRow(goal="entrance", configured_at=NOW, test_kind="real", delivery_ok=False, confirmed_useful_at=NOW),
    ]
    m = compute_metrics([], ms, now=NOW)
    assert m.verified_count == 0
    assert m.synthetic_only_count == 0  # this synthetic one was confirmed, so not "only"


def test_abandonment_window():
    ms = [
        MilestoneRow(goal="entrance", configured_at=NOW - timedelta(days=8)),   # stale
        MilestoneRow(goal="entrance", configured_at=NOW - timedelta(days=2)),   # recent
        MilestoneRow(goal="entrance", configured_at=None),                      # never configured
    ]
    m = compute_metrics([], ms, now=NOW, abandon_after_days=7)
    assert m.abandoned_count == 1


def test_synthetic_only_counts_unconfirmed_demo_tests():
    ms = [MilestoneRow(goal="entrance", configured_at=NOW, test_kind="synthetic")]
    m = compute_metrics([], ms, now=NOW)
    assert m.synthetic_only_count == 1


# ── endpoint wiring ──────────────────────────────────────────────────

class _MetricsDB:
    def __init__(self, prefs, milestones):
        self._prefs = prefs
        self._milestones = milestones
        self._call = 0

    async def execute(self, _stmt):
        self._call += 1
        res = MagicMock()
        scalars = MagicMock()
        # First execute() is the preferences query, second the milestones.
        scalars.all.return_value = self._prefs if self._call == 1 else self._milestones
        res.scalars.return_value = scalars
        return res


def test_metrics_endpoint_folds_rows():
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin")
    prefs = [{"goal": "entrance", "place": "home", "focus": "daily", "paused": False}]
    milestones = [SimpleNamespace(
        goal="entrance", configured_at=NOW - timedelta(days=1),
        install_ready_at=NOW - timedelta(minutes=5), confirmed_useful_at=NOW,
        test_kind="real", delivery_ok=True,
    )]
    db = _MetricsDB(prefs, milestones)
    out = _run(auth_routes.onboarding_metrics(current_user=admin, db=db))
    assert out.users_with_preferences == 1
    assert out.verified_count == 1
    assert out.median_seconds_to_first_useful == 300.0


# ── account isolation ────────────────────────────────────────────────

class _CaptureDB:
    def __init__(self):
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = stmt
        res = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        res.scalars.return_value = scalars
        return res


def test_list_activation_is_scoped_to_the_caller():
    user = SimpleNamespace(id=uuid.uuid4(), role="admin")
    db = _CaptureDB()
    _run(auth_routes.list_activation(current_user=user, db=db))
    # The query must filter by this user's id, so no one reads another
    # account's activation milestones.
    compiled = str(db.stmt.compile(compile_kwargs={"literal_binds": True}))
    assert user.id.hex in compiled.replace("-", "")
    assert "activation_milestones.user_id" in compiled
