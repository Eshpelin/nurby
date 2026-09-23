"""Tests for the MQTT fan-out hook in rule firing (services/events/firing.py)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.events import firing


def make_rule():
    rule = SimpleNamespace(id=uuid.uuid4(), name="Stranger alert")
    return rule


@pytest.mark.asyncio
async def test_broadcast_fired_also_publishes_to_mqtt_bus():
    publisher = AsyncMock()
    ws = AsyncMock()
    rule = make_rule()
    event_id = uuid.uuid4()
    obs = {
        "camera_id": str(uuid.uuid4()),
        "camera_name": "Front Door",
        "observation_id": "obs-1",
        "timestamp": "2026-09-23T10:00:00+00:00",
    }
    with patch("services.api.ws.broadcast", new=ws), \
         patch("services.integrations.mqtt.publishers.publish_rule_event", new=publisher):
        await firing._broadcast_fired(event_id, rule, obs, "alert")
    ws.assert_awaited_once()
    publisher.assert_awaited_once_with(event_id, rule, obs, "alert")


@pytest.mark.asyncio
async def test_broadcast_fired_succeeds_when_mqtt_bus_is_down():
    """Redis/bridge failures must never break rule firing."""
    ws = AsyncMock()
    rule = make_rule()
    obs = {"camera_id": str(uuid.uuid4()), "camera_name": "x", "timestamp": None}
    with patch("services.api.ws.broadcast", new=ws), \
         patch("services.integrations.mqtt.publishers.publish_rule_event",
               new=AsyncMock(side_effect=RuntimeError("redis down"))):
        await firing._broadcast_fired(uuid.uuid4(), rule, obs, "alert")
    ws.assert_awaited_once()
