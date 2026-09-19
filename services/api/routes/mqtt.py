"""MQTT / Home Assistant integration routes (docs/integrations/mqtt.md).

Admin-only: connection status plus a one-shot broker connect test. The
heavy lifting lives in the bridge supervisor (services/integrations/
mqtt/bridge.py); these endpoints only report and probe.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiomqtt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shared.app_settings import DEFAULTS, get_setting
from shared.auth import require_admin
from services.integrations.mqtt.bridge import bridge_status
from services.integrations.mqtt.config import load_config

router = APIRouter()
logger = logging.getLogger("nurby.api.mqtt")


class MqttStatusResponse(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 1883
    discovery_enabled: bool = True
    connected: bool = False
    last_error: str | None = None
    last_connected_at: float | None = None
    announced_entities: int = 0


class MqttTestResponse(BaseModel):
    ok: bool
    detail: str


@router.get("/integrations/mqtt", response_model=MqttStatusResponse)
async def mqtt_status(_current_user=Depends(require_admin)) -> MqttStatusResponse:
    """Broker config (minus credentials) plus live bridge state."""
    enabled = bool(await get_setting("mqtt_enabled", DEFAULTS["mqtt_enabled"]))
    host = str(await get_setting("mqtt_host", DEFAULTS["mqtt_host"]) or "")
    port = int(await get_setting("mqtt_port", DEFAULTS["mqtt_port"]) or 1883)
    discovery = bool(
        await get_setting("mqtt_discovery_enabled", DEFAULTS["mqtt_discovery_enabled"])
    )
    status = bridge_status()
    return MqttStatusResponse(
        enabled=enabled,
        host=host,
        port=port,
        discovery_enabled=discovery,
        connected=bool(status.get("connected")),
        last_error=status.get("last_error"),
        last_connected_at=status.get("last_connected_at"),
        announced_entities=int(status.get("announced_entities") or 0),
    )


@router.post("/integrations/mqtt/test", response_model=MqttTestResponse)
async def mqtt_test(_current_user=Depends(require_admin)) -> MqttTestResponse:
    """One-shot broker connection probe with the stored settings. Does
    not disturb the bridge's own session (separate client, clean
    disconnect)."""
    cfg = await load_config()
    if not cfg.host:
        raise HTTPException(status_code=400, detail="Set a broker host first")
    started = time.monotonic()
    try:
        client = aiomqtt.Client(
            hostname=cfg.host,
            port=cfg.port,
            identifier=f"{cfg.client_id}-test",
            username=cfg.username or None,
            password=cfg.password or None,
            tls_params=aiomqtt.TLSParameters() if cfg.tls else None,
            timeout=5.0,
        )
        async with client:
            elapsed = round((time.monotonic() - started) * 1000)
            return MqttTestResponse(ok=True, detail=f"Connected in {elapsed} ms")
    except aiomqtt.MqttError as exc:
        return MqttTestResponse(ok=False, detail=str(exc) or type(exc).__name__)
    except asyncio.CancelledError:
        raise
    except OSError as exc:
        return MqttTestResponse(ok=False, detail=str(exc))
