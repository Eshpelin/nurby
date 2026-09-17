"""Verified first-useful-result tracking (#193 / #204 phase 2).

Guards the three-step activation state machine and its API/engine seams:
  - A configured rule or a delivered synthetic test alone is never
    verified activation. Only a real, delivered, confirmed event is.
  - The engine recorder advances only the ``tested`` step, never regresses
    a real delivered test, and never invents a milestone.
  - The API scaffolds a DISABLED draft rule, refuses to mark a
    misconfigured rule as configured, and refuses to confirm without a
    delivered test.

Handlers run directly with a stubbed AsyncSession, the DB-free convention
of the suite.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services.api.routes import auth as auth_routes
from shared.activation import (
    ConfigureRequest,
    ConfirmRequest,
    DraftRuleRequest,
    compute_activation,
    starter_key_for_goal,
)
from shared.activation_recorder import record_event_for_activation


def _run(coro):
    return asyncio.run(coro)


T0 = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


# ── pure state machine ───────────────────────────────────────────────

def test_goal_starter_map_only_covers_detection_goals():
    assert starter_key_for_goal("entrance") == "someone-at-the-door"
    assert starter_key_for_goal("deliveries") == "package-arrived"
    assert starter_key_for_goal("after_hours") == "someone-at-night"
    assert starter_key_for_goal("review") is None
    assert starter_key_for_goal("explore") is None


def test_nothing_configured_points_at_configured_step():
    view = compute_activation(goal="entrance")
    assert view.verified is False
    assert view.next_step == "configured"
    assert [s.done for s in view.steps] == [False, False, False]


def test_configured_alone_is_not_tested_or_verified():
    view = compute_activation(goal="entrance", configured_at=T0)
    assert view.next_step == "tested"
    assert view.verified is False
    assert view.steps[0].done is True and view.steps[1].done is False


def test_fired_event_without_delivery_is_not_tested():
    # An event that fired but whose alert never left the box is not a
    # tested delivery path.
    view = compute_activation(goal="entrance", configured_at=T0, tested_at=T0, delivery_ok=False, test_kind="real")
    assert view.steps[1].done is False
    assert view.next_step == "tested"


def test_synthetic_delivered_confirmed_is_not_verified():
    view = compute_activation(
        goal="entrance",
        configured_at=T0,
        tested_at=T0,
        delivery_ok=True,
        test_kind="synthetic",
        confirmed_useful_at=T0,
        install_ready_at=T0,
    )
    assert view.steps[1].done is True and view.steps[1].synthetic is True
    assert view.verified is False
    # A synthetic-only confirmation still needs a real test.
    assert view.next_step == "tested"
    assert view.seconds_to_first_useful is None


def test_real_delivered_confirmed_is_verified_and_timed():
    view = compute_activation(
        goal="entrance",
        configured_at=T0,
        tested_at=T0 + timedelta(minutes=3),
        delivery_ok=True,
        test_kind="real",
        confirmed_useful_at=T0 + timedelta(minutes=5),
        install_ready_at=T0,
    )
    assert view.verified is True
    assert view.next_step is None
    assert view.seconds_to_first_useful == 300.0


# ── engine recorder ──────────────────────────────────────────────────

class _RecorderDB:
    def __init__(self, milestones, camera):
        self._milestones = milestones
        self._camera = camera
        self.committed = False

    async def execute(self, _stmt):
        res = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = self._milestones
        res.scalars.return_value = scalars
        return res

    async def get(self, _model, _id):
        return self._camera

    async def commit(self):
        self.committed = True


def _milestone(**kw):
    base = dict(test_kind=None, delivery_ok=None, tested_at=None, event_id=None, rule_id=uuid.uuid4())
    base.update(kw)
    return SimpleNamespace(**base)


def test_recorder_marks_real_delivered_test():
    m = _milestone()
    db = _RecorderDB([m], SimpleNamespace(stream_type="rtsp"))
    _run(record_event_for_activation(db, rule_id=m.rule_id, camera_id=uuid.uuid4(), event_id=uuid.uuid4(), delivered=True))
    assert m.test_kind == "real"
    assert m.delivery_ok is True
    assert m.tested_at is not None
    assert db.committed is True


def test_recorder_labels_demo_camera_synthetic():
    m = _milestone()
    db = _RecorderDB([m], SimpleNamespace(stream_type="file"))
    _run(record_event_for_activation(db, rule_id=m.rule_id, camera_id=uuid.uuid4(), event_id=uuid.uuid4(), delivered=True))
    assert m.test_kind == "synthetic"


def test_recorder_does_not_regress_a_real_delivered_test():
    m = _milestone(test_kind="real", delivery_ok=True, tested_at=T0)
    db = _RecorderDB([m], SimpleNamespace(stream_type="file"))
    _run(record_event_for_activation(db, rule_id=m.rule_id, camera_id=uuid.uuid4(), event_id=uuid.uuid4(), delivered=True))
    # Stays real; a later synthetic test does not overwrite it.
    assert m.test_kind == "real"
    assert m.tested_at == T0
    assert db.committed is False


def test_recorder_noop_without_milestone():
    db = _RecorderDB([], SimpleNamespace(stream_type="rtsp"))
    _run(record_event_for_activation(db, rule_id=uuid.uuid4(), camera_id=None, event_id=uuid.uuid4(), delivered=True))
    assert db.committed is False


# ── API handlers ─────────────────────────────────────────────────────

class _Admin:
    def __init__(self):
        self.id = uuid.uuid4()
        self.role = "admin"


class _ApiDB:
    """Stub AsyncSession. ``milestone`` is what _get_milestone returns;
    ``rule`` is what db.get(Rule, ...) returns."""

    def __init__(self, milestone=None, rule=None):
        self._milestone = milestone
        self._rule = rule
        self.added = []
        self.commits = 0
        self.add = MagicMock(side_effect=self.added.append)

    async def execute(self, _stmt):
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._milestone
        scalars = MagicMock()
        scalars.all.return_value = [self._milestone] if self._milestone else []
        res.scalars.return_value = scalars
        return res

    async def get(self, _model, _id):
        return self._rule

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def test_scaffold_creates_a_disabled_draft_rule_and_milestone():
    db = _ApiDB(milestone=None)
    body = DraftRuleRequest(goal="deliveries", camera_id=str(uuid.uuid4()))

    view = _run(auth_routes.scaffold_draft_rule(body=body, current_user=_Admin(), db=db))

    # A rule and a milestone were added; the rule is created disabled.
    from shared.models import Rule as RuleModel

    rules = [o for o in db.added if isinstance(o, RuleModel)]
    assert len(rules) == 1
    assert rules[0].enabled is False
    assert view.goal == "deliveries"
    # Saving a scaffold is not activation.
    assert view.verified is False
    assert view.next_step == "configured"


def test_scaffold_rejects_a_goal_with_no_rule():
    db = _ApiDB()
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.scaffold_draft_rule(body=DraftRuleRequest(goal="review"), current_user=_Admin(), db=db))
    assert ei.value.status_code == 400


def test_configure_requires_enabled_rule_with_camera_and_delivery():
    cam = uuid.uuid4()
    good = SimpleNamespace(
        id=uuid.uuid4(), enabled=True,
        trigger_pattern={"type": "object_detected", "label": "person", "camera_id": str(cam)},
        actions=[{"type": "notify", "message": "hi"}],
    )
    db = _ApiDB(milestone=None, rule=good)
    view = _run(auth_routes.mark_configured(body=ConfigureRequest(goal="entrance", rule_id=str(good.id)), current_user=_Admin(), db=db))
    assert view.steps[0].done is True  # configured
    assert view.verified is False


@pytest.mark.parametrize(
    "rule,status",
    [
        (SimpleNamespace(enabled=False, trigger_pattern={"camera_id": "x"}, actions=[{"type": "notify"}]), 409),
        (SimpleNamespace(enabled=True, trigger_pattern={}, actions=[{"type": "notify"}]), 409),
        (SimpleNamespace(enabled=True, trigger_pattern={"camera_id": "x"}, actions=[{"type": "verify"}]), 409),
    ],
)
def test_configure_rejects_incomplete_rules(rule, status):
    rule.id = uuid.uuid4()
    db = _ApiDB(rule=rule)
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.mark_configured(body=ConfigureRequest(goal="entrance", rule_id=str(rule.id)), current_user=_Admin(), db=db))
    assert ei.value.status_code == status


def test_confirm_refuses_without_a_delivered_test():
    m = SimpleNamespace(
        goal="entrance", rule_id=uuid.uuid4(), camera_id=None, draft_rule_id=None,
        configured_at=T0, tested_at=None, confirmed_useful_at=None,
        test_kind=None, delivery_ok=None, install_ready_at=T0,
    )
    db = _ApiDB(milestone=m)
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.confirm_useful(body=ConfirmRequest(goal="entrance"), current_user=_Admin(), db=db))
    assert ei.value.status_code == 409
    assert m.confirmed_useful_at is None


def test_confirm_marks_verified_after_a_real_delivered_test():
    m = SimpleNamespace(
        goal="entrance", rule_id=uuid.uuid4(), camera_id=None, draft_rule_id=None,
        configured_at=T0, tested_at=T0, confirmed_useful_at=None,
        test_kind="real", delivery_ok=True, install_ready_at=T0,
    )
    db = _ApiDB(milestone=m)
    view = _run(auth_routes.confirm_useful(body=ConfirmRequest(goal="entrance"), current_user=_Admin(), db=db))
    assert m.confirmed_useful_at is not None
    assert view.verified is True
