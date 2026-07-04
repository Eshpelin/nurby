"""Physical alert device catalog + registered device instances.

Preset endpoints are read-only catalog data ("ESP32 Buzzer Alarm", ...)
plus the matching receiver script. Instance endpoints CRUD the user's
registered devices (the Device table): named endpoints that rules fire
via the ``device`` action and that @ mentions resolve to.

Route order matters: every /instances* route must be registered BEFORE
the /{preset_id} catch-all or Starlette matches "instances" as a preset.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.devices import DEVICE_PRESETS, get_preset
from shared.auth import get_current_user, require_admin
from shared.camera_secrets import seal, unseal
from shared.database import get_db
from shared.models import Device, User
from shared.schemas import DeviceCreate, DeviceResponse, DeviceUpdate

router = APIRouter()

# Repo root. this file is services/api/routes/devices.py.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def _to_response(device: Device) -> DeviceResponse:
    resp = DeviceResponse.model_validate(device)
    resp.has_secret = bool(device.secret)
    return resp


@router.get("/instances", response_model=list[DeviceResponse])
async def list_device_instances(
    _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(Device).order_by(Device.created_at))).scalars().all()
    return [_to_response(d) for d in rows]


@router.post("/instances", response_model=DeviceResponse, status_code=201)
async def create_device_instance(
    body: DeviceCreate,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    payload_template = body.payload_template
    if payload_template is None and body.preset_id:
        preset = get_preset(body.preset_id)
        if preset is None:
            raise HTTPException(status_code=422, detail="Unknown device preset")
        # Snapshot the preset payload so later catalog edits don't silently
        # change what an existing device receives.
        payload_template = dict(preset["webhook_action"]["payload_template"])
    device = Device(
        name=body.name,
        preset_id=body.preset_id,
        endpoint_url=body.endpoint_url,
        secret=seal(body.secret),
        payload_template=payload_template,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return _to_response(device)


@router.patch("/instances/{device_id}", response_model=DeviceResponse)
async def update_device_instance(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    updates = body.model_dump(exclude_unset=True)
    if "secret" in updates:
        # Empty string clears, non-empty replaces (absent = unchanged).
        updates["secret"] = seal(updates["secret"]) if updates["secret"] else None
    for field, value in updates.items():
        setattr(device, field, value)
    await db.commit()
    await db.refresh(device)
    return _to_response(device)


@router.delete("/instances/{device_id}", status_code=204)
async def delete_device_instance(
    device_id: uuid.UUID,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(device)
    await db.commit()


@router.post("/instances/{device_id}/test")
async def test_device_instance(
    device_id: uuid.UUID,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Server-side test fire (device IPs are LAN-private and CORS-hostile,
    so the browser cannot do this itself). Renders the payload template
    with a synthetic context and delivers with the same signed/retried
    path rule actions use."""
    from services.events.actions import deliver_signed, render_device_payload

    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    context = {
        "rule_name": "Test fire",
        "camera_name": "Test",
        "timestamp_local": datetime.now(timezone.utc).isoformat(),
        "detections_summary": "Manual test from Nurby settings",
        "recording_url": "",
        "thumbnail_url": "",
    }
    payload = render_device_payload(
        device.payload_template or {"event": "{rule_name}", "description": "{detections_summary}"},
        context,
    )
    ok, detail = await deliver_signed(
        "POST",
        device.endpoint_url,
        payload,
        secret=unseal(device.secret),
        timeout=float(device.timeout_seconds),
    )
    device.last_test_at = datetime.now(timezone.utc)
    device.last_test_ok = ok
    device.last_error = None if ok else detail[:512]
    await db.commit()
    return {"ok": ok, "detail": detail}


@router.get("")
async def list_devices(_user: User = Depends(get_current_user)) -> list[dict]:
    """All device presets for the rule builder picker."""
    return DEVICE_PRESETS


@router.get("/{preset_id}")
async def get_device(preset_id: str, _user: User = Depends(get_current_user)) -> dict:
    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Device preset not found")
    return preset


@router.get("/{preset_id}/receiver", response_class=PlainTextResponse)
async def get_receiver_script(
    preset_id: str, _user: User = Depends(get_current_user)
) -> str:
    """Return the raw receiver script so the UI can show / copy it."""
    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Device preset not found")
    rel = preset["receiver"]
    # Guard against path traversal. only serve from the receivers dir.
    safe_root = os.path.join(_REPO_ROOT, "integrations", "devices", "receivers")
    path = os.path.abspath(os.path.join(_REPO_ROOT, rel))
    if not path.startswith(safe_root) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Receiver script not found")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
