"""Tests for the MQTT status/test API routes (services/api/routes/mqtt.py)."""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiomqtt
import pytest

from services.api.routes import mqtt as mqtt_routes


def settings_side_effect(values):
    async def fake_get(key, default=None):
        return values.get(key, default)

    return fake_get


@pytest.mark.asyncio
async def test_status_reports_bridge_state_without_credentials():
    values = {
        "mqtt_enabled": True,
        "mqtt_host": "mosquitto",
        "mqtt_port": 1884,
        "mqtt_discovery_enabled": False,
    }
    with patch.object(mqtt_routes, "get_setting", new=settings_side_effect(values)), \
         patch.object(mqtt_routes, "bridge_status", return_value={
             "connected": True, "last_error": None, "last_connected_at": 1.0,
             "announced_entities": 9,
         }):
        out = await mqtt_routes.mqtt_status()
    assert out.enabled is True and out.host == "mosquitto" and out.port == 1884
    assert out.connected is True and out.announced_entities == 9
    model_dump = out.model_dump()
    assert "password" not in model_dump and "mqtt_password" not in model_dump


@pytest.mark.asyncio
async def test_test_endpoint_requires_host():
    with patch.object(mqtt_routes, "get_setting", new=settings_side_effect({"mqtt_host": ""})):
        with pytest.raises(Exception) as exc:
            await mqtt_routes.mqtt_test()
    assert "host" in str(exc.value)


@pytest.mark.asyncio
async def test_test_endpoint_success():
    values = {"mqtt_enabled": True, "mqtt_host": "mosquitto", "mqtt_port": 1883}

    class FakeClient:
        last_instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeClient.last_instance = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch.object(mqtt_routes, "get_setting", new=settings_side_effect(values)), \
         patch("services.integrations.mqtt.config.get_setting", new=settings_side_effect(values)), \
         patch.object(mqtt_routes.aiomqtt, "Client", new=FakeClient):
        out = await mqtt_routes.mqtt_test()
    assert out.ok is True and "Connected" in out.detail
    assert FakeClient.last_instance.kwargs["identifier"] == "nurby-test"


@pytest.mark.asyncio
async def test_test_endpoint_reports_broker_error():
    values = {"mqtt_enabled": True, "mqtt_host": "nowhere", "mqtt_port": 1}

    class Failing:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise aiomqtt.MqttError("refused")

        async def __aexit__(self, *exc):
            return False

    with patch.object(mqtt_routes, "get_setting", new=settings_side_effect(values)), \
         patch("services.integrations.mqtt.config.get_setting", new=settings_side_effect(values)), \
         patch.object(mqtt_routes.aiomqtt, "Client", new=Failing):
        out = await mqtt_routes.mqtt_test()
    assert out.ok is False and "refused" in out.detail


@pytest.mark.asyncio
async def test_load_config_unseals_password_and_normalizes_prefix():
    from services.integrations.mqtt.config import load_config
    from shared.camera_secrets import seal

    values = {
        "mqtt_enabled": True,
        "mqtt_host": " broker ",
        "mqtt_topic_prefix": "/nurby/inst1/",
        "mqtt_password": seal("s3cret"),
    }

    async def fake_get(key, default=None):
        return values.get(key, default)

    with patch("services.integrations.mqtt.config.get_setting", new=fake_get):
        cfg = await load_config()
    assert cfg.host == "broker"
    assert cfg.prefix == "nurby/inst1"
    assert cfg.password == "s3cret"
    assert cfg.connectable is True
