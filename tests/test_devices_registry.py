"""Tests for the device registry CRUD + test-fire endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import services.api.routes.devices as devices_route
from shared.schemas import DeviceCreate, DeviceUpdate


def make_user():
    class U:
        role = "admin"

    return U()


def make_db(device=None):
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=device)

    async def refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            from datetime import datetime, timezone

            obj.created_at = datetime.now(timezone.utc)
        # Model-level defaults only apply at INSERT; mirror them here.
        if getattr(obj, "timeout_seconds", None) is None:
            obj.timeout_seconds = 5
        if getattr(obj, "enabled", None) is None:
            obj.enabled = True
        obj.last_test_at = getattr(obj, "last_test_at", None)
        obj.last_test_ok = getattr(obj, "last_test_ok", None)
        obj.last_error = getattr(obj, "last_error", None)

    db.refresh = AsyncMock(side_effect=refresh)
    return db


@pytest.mark.asyncio
async def test_create_seals_secret_and_hides_it():
    db = make_db()
    body = DeviceCreate(
        name="FrontPorchAlarm",
        endpoint_url="http://192.168.1.40:80/alert",
        secret="shared-hmac-key",
    )
    resp = await devices_route.create_device_instance(body, make_user(), db)
    stored = db.add.call_args[0][0]
    assert stored.secret.startswith("gAAAA")  # Fernet-sealed
    assert resp.has_secret is True
    assert not hasattr(resp, "secret") or "secret" not in resp.model_dump()


@pytest.mark.asyncio
async def test_create_from_preset_snapshots_payload():
    db = make_db()
    body = DeviceCreate(
        name="Buzzer",
        preset_id="esp32-buzzer-alarm",
        endpoint_url="http://10.0.0.9:80/alert",
    )
    await devices_route.create_device_instance(body, make_user(), db)
    stored = db.add.call_args[0][0]
    assert stored.payload_template  # snapshot of STANDARD_PAYLOAD
    assert "{rule_name}" in str(stored.payload_template)


@pytest.mark.asyncio
async def test_create_unknown_preset_422():
    db = make_db()
    body = DeviceCreate(name="X", preset_id="nope", endpoint_url="http://x/alert")
    with pytest.raises(HTTPException) as exc:
        await devices_route.create_device_instance(body, make_user(), db)
    assert exc.value.status_code == 422


def make_device_row(**overrides):
    from datetime import datetime, timezone

    device = MagicMock()
    device.id = uuid.uuid4()
    device.name = "Alarm"
    device.preset_id = None
    device.endpoint_url = "http://10.0.0.9/alert"
    device.secret = None
    device.payload_template = None
    device.timeout_seconds = 5
    device.enabled = True
    device.last_test_at = None
    device.last_test_ok = None
    device.last_error = None
    device.created_at = datetime.now(timezone.utc)
    for k, v in overrides.items():
        setattr(device, k, v)
    return device


@pytest.mark.asyncio
async def test_update_secret_semantics():
    device = make_device_row(secret="gAAAAold")
    db = make_db(device)
    # empty string clears
    await devices_route.update_device_instance(uuid.uuid4(), DeviceUpdate(secret=""), make_user(), db)
    assert device.secret is None
    # non-empty replaces (sealed)
    await devices_route.update_device_instance(
        uuid.uuid4(), DeviceUpdate(secret="new-key"), make_user(), db
    )
    assert device.secret.startswith("gAAAA")


@pytest.mark.asyncio
async def test_test_fire_passes_unsealed_secret_and_records_health():
    from shared.camera_secrets import seal

    device = MagicMock()
    device.endpoint_url = "http://10.0.0.9/alert"
    device.secret = seal("plain-key")
    device.timeout_seconds = 7
    device.payload_template = {"event": "{rule_name}"}
    db = make_db(device)

    delivered = {}

    async def fake_deliver(method, url, payload, *, secret=None, timeout=10.0, **kw):
        delivered.update(method=method, url=url, payload=payload, secret=secret, timeout=timeout)
        return True, "delivered (200)"

    with patch("services.events.actions.deliver_signed", new=fake_deliver):
        out = await devices_route.test_device_instance(uuid.uuid4(), make_user(), db)
    assert out["ok"] is True
    assert delivered["secret"] == "plain-key"
    assert delivered["timeout"] == 7.0
    assert delivered["payload"]["event"] == "Test fire"
    assert device.last_test_ok is True


@pytest.mark.asyncio
async def test_test_fire_failure_records_error():
    device = MagicMock()
    device.endpoint_url = "http://10.0.0.9/alert"
    device.secret = None
    device.timeout_seconds = 5
    device.payload_template = None
    db = make_db(device)
    with patch(
        "services.events.actions.deliver_signed",
        new=AsyncMock(return_value=(False, "connect error")),
    ):
        out = await devices_route.test_device_instance(uuid.uuid4(), make_user(), db)
    assert out["ok"] is False
    assert device.last_test_ok is False
    assert device.last_error == "connect error"


def test_instance_routes_registered_before_preset_catchall():
    paths = [r.path for r in devices_route.router.routes]
    assert paths.index("/instances") < paths.index("/{preset_id}")
