"""Mobile push notification devices.

The mobile app registers its FCM token here after login and the
dispatcher (shared/push.py) fans notifications out to the registered
devices. /config hands the app the admin-pasted Firebase client config
so a stock build can initialise Firebase against any self-hosted
install without baked-in credentials. Devices are strictly per-user:
you only ever see and delete your own.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.app_settings import get_setting
from shared.auth import get_current_user
from shared.database import get_db
from shared.models import PushDevice, User
from shared.push import send_push_to_user

router = APIRouter()


class DeviceRegister(BaseModel):
    platform: str = Field(pattern="^(ios|android)$")
    token: str = Field(min_length=1, max_length=4096)
    app_version: str | None = Field(default=None, max_length=32)


class DeviceResponse(BaseModel):
    id: uuid.UUID
    platform: str
    token: str
    app_version: str | None
    created_at: datetime
    last_seen_at: datetime


def _to_response(row: PushDevice) -> DeviceResponse:
    return DeviceResponse(
        id=row.id,
        platform=row.platform,
        token=row.token,
        app_version=row.app_version,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


@router.post("/devices", response_model=DeviceResponse)
async def register_device(
    body: DeviceRegister,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Upsert by token. An FCM token identifies one app install, so a
    re-register after a new login re-assigns the existing row to the
    current user (and bumps last_seen_at) instead of duplicating it."""
    row = (
        await db.execute(select(PushDevice).where(PushDevice.token == body.token))
    ).scalar_one_or_none()
    if row is None:
        row = PushDevice(
            user_id=user.id,
            platform=body.platform,
            token=body.token,
            app_version=body.app_version,
        )
        db.add(row)
    else:
        row.user_id = user.id
        row.platform = body.platform
        if body.app_version is not None:
            row.app_version = body.app_version
        row.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceResponse]:
    rows = (
        await db.execute(
            select(PushDevice)
            .where(PushDevice.user_id == user.id)
            .order_by(PushDevice.created_at.desc())
        )
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.get(PushDevice, device_id)
    # 404 for another user's device too, so the endpoint does not leak
    # which device ids exist.
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(row)
    await db.commit()


@router.post("/test")
async def send_test_push(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fire a test notification at the caller's own devices."""
    result = await send_push_to_user(
        db,
        user.id,
        title="Nurby test notification",
        body="Push notifications are working.",
        data={"type": "test"},
    )
    if result.get("skipped"):
        return {"sent": 0, "errors": ["Push is not configured (Settings -> push_fcm_service_account)"]}
    return {"sent": result.get("sent", 0), "errors": result.get("errors", [])}


@router.get("/config")
async def get_push_config(_user: User = Depends(get_current_user)) -> dict:
    """Client bootstrap info. ``configured`` says whether the server can
    send at all (service account pasted); ``firebase_web_config`` is the
    non-secret Firebase client config (apiKey / appId / projectId /
    messagingSenderId) the mobile app needs to initialise Firebase and
    obtain a token. The service account itself is never exposed."""
    service_account = await get_setting("push_fcm_service_account")
    client_config = await get_setting("push_firebase_client_config")
    return {
        "configured": isinstance(service_account, dict) and bool(service_account.get("project_id")),
        "firebase_web_config": client_config if isinstance(client_config, dict) else None,
    }
