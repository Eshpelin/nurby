"""Physical alert device catalog.

Read-only endpoints the rule builder uses to offer out-of-box device
presets ("ESP32 Buzzer Alarm", "Raspberry Pi Speaker", ...) and to serve
the matching receiver script so the user can copy it onto their device.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from integrations.devices import DEVICE_PRESETS, get_preset
from shared.auth import get_current_user
from shared.models import User

router = APIRouter()

# Repo root. this file is services/api/routes/devices.py.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


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
