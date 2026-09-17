"""Consequential rules are created review-first (#192).

A rule that takes a real-world action (drives a relay, speaks over a
camera, writes to another system) must land disabled so a suspected
trigger cannot act before a human has reviewed it. Informational rules
(notify) stay enabled. We also check that the create response flags the
demotion so the UI can explain it.

The create handler is called directly with a fake admin and an
AsyncMock db: an api_call to a plain URL carries no camera/person/device
reference, so `_stale_rule_refs` never touches the db.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

from services.api.routes.rules import create_from_starter, create_rule
from shared.consequential import (
    CONSEQUENTIAL_ACTION_TYPES,
    rule_is_consequential,
)
from shared.schemas import RuleCreate, RuleResponse


class _FakeUser:
    id = uuid.uuid4()
    role = "admin"
    is_active = True


def _create(body: RuleCreate):
    db = AsyncMock()
    db.add = MagicMock()
    return asyncio.run(create_rule(body, _current_user=_FakeUser(), db=db))


# ── pure detection ───────────────────────────────────────────────

def test_action_types_cover_the_real_world_executors():
    # The set must not silently drift from the executors that reach outside.
    assert CONSEQUENTIAL_ACTION_TYPES == {"api_call", "webhook", "device", "speak"}


def test_notify_and_telegram_are_not_consequential():
    assert not rule_is_consequential([{"type": "notify", "message": "hi"}])
    assert not rule_is_consequential([{"type": "telegram", "channel_id": "c"}])
    # broadcast is an in-app websocket push, not a real-world side effect.
    assert not rule_is_consequential([{"type": "broadcast"}])


def test_api_call_and_device_are_consequential():
    assert rule_is_consequential([{"type": "api_call", "url": "https://x"}])
    assert rule_is_consequential([{"type": "device", "device_id": "d"}])
    assert rule_is_consequential([{"type": "speak", "camera_id": "c", "text": "hi"}])


def test_consequential_action_in_sequence_on_timeout_counts():
    # The line-stoppage recipe opens a work order in on_timeout while the
    # top-level chain is empty.
    trigger = {
        "type": "object_detected",
        "sequence": {
            "steps": [{"check": {"type": "object_detected"}, "within_seconds": 300}],
            "on_timeout": [{"type": "api_call", "url": "https://cmms"}],
        },
    }
    assert rule_is_consequential([], trigger) is True
    assert rule_is_consequential([]) is False


# ── create endpoint enforcement ──────────────────────────────────

def test_consequential_rule_is_forced_review_first_even_when_enabled():
    body = RuleCreate(
        name="Post to WMS on dock dwell",
        enabled=True,
        trigger_pattern={"type": "object_detected", "label": "truck"},
        actions=[{"type": "api_call", "url": "https://your-wms.example.com/api/tasks"}],
    )
    rule = _create(body)
    assert rule.enabled is False
    assert rule.review_first is True
    # The response schema surfaces the demotion. The mocked db never assigns
    # server-side columns, so stand them in for the serialization check.
    from datetime import datetime, timezone

    rule.id = uuid.uuid4()
    rule.created_at = datetime.now(timezone.utc)
    assert RuleResponse.model_validate(rule).review_first is True


def test_informational_rule_stays_enabled():
    body = RuleCreate(
        name="Someone at the door",
        enabled=True,
        trigger_pattern={"type": "object_detected", "label": "person"},
        actions=[{"type": "notify", "message": "Someone is here"}],
    )
    rule = _create(body)
    assert rule.enabled is True
    assert rule.review_first is False


def test_on_timeout_consequential_rule_is_review_first():
    body = RuleCreate(
        name="Line stopped",
        enabled=True,
        trigger_pattern={
            "type": "object_detected",
            "sequence": {
                "steps": [{"check": {"type": "object_detected"}, "within_seconds": 300}],
                "on_timeout": [{"type": "api_call", "url": "https://cmms"}],
            },
        },
        actions=[{"type": "notify", "message": "line down"}],
    )
    rule = _create(body)
    assert rule.enabled is False
    assert rule.review_first is True


def test_read_of_a_stored_rule_defaults_review_first_false():
    # A plain ORM-shaped object without the transient attribute still
    # validates: reads of stored rules report review_first False.
    class _StoredRule:
        id = uuid.uuid4()
        name = "n"
        enabled = True
        trigger_pattern = {"type": "object_detected"}
        conditions = None
        actions = [{"type": "notify"}]
        cooldown_seconds = 300
        severity = "alert"
        snoozed_until = None
        from datetime import datetime, timezone

        created_at = datetime.now(timezone.utc)

    assert RuleResponse.model_validate(_StoredRule()).review_first is False


# ── starter path keeps the same guard ────────────────────────────

def test_starter_create_uses_the_same_review_first_guard(monkeypatch):
    # Force a consequential starter payload to prove the starter endpoint
    # also demotes it, even though the shipped starters are notify-only.
    from shared import rule_starters

    def _fake_starter(key, camera_id):
        return {
            "name": "relay starter",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "person"},
            "conditions": None,
            "actions": [{"type": "device", "device_id": str(uuid.uuid4())}],
            "cooldown_seconds": 300,
            "severity": "alert",
        }

    monkeypatch.setattr(rule_starters, "starter_rule", _fake_starter)

    from services.api.routes.rules import StarterCreate

    db = AsyncMock()
    db.add = MagicMock()
    rule = asyncio.run(
        create_from_starter(
            StarterCreate(key="whatever"), _current_user=_FakeUser(), db=db
        )
    )
    assert rule.enabled is False
    assert rule.review_first is True
