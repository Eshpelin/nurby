"""Tests for the `device` rule action: executor, validation, refs, NL vocab."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.events.actions as actions
from services.api.routes.rules import _collect_rule_refs
from shared.rule_schema import ACTION_TYPES
from shared.schemas import _validate_action_chain

DEVICE_ID = uuid.uuid4()


def make_rule():
    rule = MagicMock()
    rule.id = uuid.uuid4()
    rule.name = "Porch alarm"
    return rule


def fake_session_factory(device):
    @asynccontextmanager
    async def factory():
        db = AsyncMock()
        db.get = AsyncMock(return_value=device)
        yield db

    return factory


def make_device(enabled=True, secret=None, template=None):
    from shared.camera_secrets import seal

    device = MagicMock()
    device.enabled = enabled
    device.endpoint_url = "http://10.0.0.9/alert"
    device.secret = seal(secret) if secret else None
    device.timeout_seconds = 5
    device.payload_template = template
    return device


CTX = {
    "event_id": "e", "rule_id": "r", "rule_name": "Porch alarm",
    "camera_id": "c", "camera_name": "Front Porch", "timestamp": "t",
    "timestamp_local": "t", "motion_score": 0, "object_detections": None,
    "person_detections": None, "vlm_description": "", "detections_summary": "1 person",
    "observation_id": "", "recording_id": "", "recording_url": "",
    "thumbnail_url": "", "event_url": "",
}


@pytest.mark.asyncio
async def test_execute_device_delivers_with_unsealed_secret():
    device = make_device(secret="hmac-key", template={"event": "{rule_name}"})
    delivered = {}

    async def fake_deliver(method, url, payload, *, secret=None, timeout=10.0, **kw):
        delivered.update(url=url, payload=payload, secret=secret, timeout=timeout)
        return True, "ok"

    status = AsyncMock()
    with patch.object(actions, "deliver_signed", new=fake_deliver), \
         patch("shared.database.async_session", new=fake_session_factory(device)), \
         patch.object(actions, "_update_event_status", new=status):
        await actions._execute_device(
            {"type": "device", "device_id": str(DEVICE_ID)}, {}, make_rule(), uuid.uuid4(), CTX,
        )
    assert delivered["secret"] == "hmac-key"
    assert delivered["payload"]["event"] == "Porch alarm"
    status.assert_awaited()
    assert status.await_args[0][2] == "success"


@pytest.mark.asyncio
async def test_execute_device_disabled_short_circuits():
    device = make_device(enabled=False)
    deliver = AsyncMock()
    status = AsyncMock()
    with patch.object(actions, "deliver_signed", new=deliver), \
         patch("shared.database.async_session", new=fake_session_factory(device)), \
         patch.object(actions, "_update_event_status", new=status):
        await actions._execute_device(
            {"type": "device", "device_id": str(DEVICE_ID)}, {}, make_rule(), uuid.uuid4(), CTX,
        )
    deliver.assert_not_awaited()
    assert status.await_args[0][2] == "failed"
    assert "disabled" in status.await_args[0][3]


@pytest.mark.asyncio
async def test_execute_device_missing_id_fails_cleanly():
    status = AsyncMock()
    with patch.object(actions, "_update_event_status", new=status):
        await actions._execute_device({"type": "device"}, {}, make_rule(), uuid.uuid4(), CTX)
    assert status.await_args[0][2] == "failed"


@pytest.mark.asyncio
async def test_execute_device_not_found():
    status = AsyncMock()
    with patch("shared.database.async_session", new=fake_session_factory(None)), \
         patch.object(actions, "_update_event_status", new=status):
        await actions._execute_device(
            {"type": "device", "device_id": str(DEVICE_ID)}, {}, make_rule(), uuid.uuid4(), CTX,
        )
    assert "not found" in status.await_args[0][3].lower()


@pytest.mark.asyncio
async def test_execute_device_extras_merged():
    device = make_device(template={"event": "{rule_name}"})
    delivered = {}

    async def fake_deliver(method, url, payload, **kw):
        delivered["payload"] = payload
        return True, "ok"

    with patch.object(actions, "deliver_signed", new=fake_deliver), \
         patch("shared.database.async_session", new=fake_session_factory(device)), \
         patch.object(actions, "_update_event_status", new=AsyncMock()):
        await actions._execute_device(
            {"type": "device", "device_id": str(DEVICE_ID), "extras": {"note": "{{camera_name}}"}},
            {}, make_rule(), uuid.uuid4(), CTX,
        )
    assert delivered["payload"]["note"] == "Front Porch"


def test_render_device_payload_both_dialects():
    out = actions.render_device_payload(
        {"a": "{rule_name}", "b": "{{camera_name}}"}, {"rule_name": "R", "camera_name": "C"}
    )
    assert out == {"a": "R", "b": "C"}


def test_validate_device_action():
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "device"}])
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "device", "device_id": "not-a-uuid"}])
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "device", "device_id": str(DEVICE_ID), "extras": "x"}])
    _validate_action_chain([{"type": "device", "device_id": str(DEVICE_ID)}])


def test_collect_refs_includes_device():
    refs, _malformed = _collect_rule_refs(
        {"type": "motion"}, None, [{"type": "device", "device_id": str(DEVICE_ID)}]
    )
    assert refs["device"] == [("actions[0].device_id", DEVICE_ID)]


def test_rule_schema_has_device_action():
    entry = next(a for a in ACTION_TYPES if a["type"] == "device")
    field = next(f for f in entry["fields"] if f["name"] == "device_id")
    assert field["required"] is True
    assert field["ref"] == "device"
