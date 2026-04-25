"""Audio file streaming + per-camera audio config patch.

The /api/audio/{capture_id} endpoint accepts both Authorization header
and a ``?token=`` query parameter so HTML5 ``<audio>`` tags can load
clips without JS-side header injection.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import decode_access_token, get_current_user
from shared.config import settings
from shared.database import get_db
from shared.models import AudioAuditLog, AudioCapture, Camera, User

router = APIRouter()


@router.get("/{capture_id}")
async def stream_audio(
    capture_id: uuid.UUID,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not token or not decode_access_token(token):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    cap = await db.get(AudioCapture, capture_id)
    if cap is None:
        raise HTTPException(status_code=404, detail="Audio capture not found")
    path = os.path.abspath(cap.file_path)
    allowed = os.path.abspath(settings.audio_storage_path)
    if not (path.startswith(allowed + os.sep) or path == allowed):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file missing on disk")
    return FileResponse(path, media_type="audio/ogg")


class CameraAudioPatch(BaseModel):
    audio_capture_enabled: bool | None = None
    audio_transcribe_enabled: bool | None = None
    audio_store_raw: bool | None = None
    transcript_store: str | None = Field(default=None, pattern="^(full|redacted|summary_only|off)$")
    audio_language: str | None = None
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)
    transcript_retention_days: int | None = Field(default=None, ge=0, le=3650)
    stt_provider_id: uuid.UUID | None = None
    stt_budget_minutes_per_hour: int | None = Field(default=None, ge=0, le=600)


_AUDIT_FIELDS = (
    "audio_capture_enabled",
    "audio_transcribe_enabled",
    "audio_store_raw",
    "transcript_store",
    "audio_language",
    "audio_retention_days",
    "transcript_retention_days",
    "stt_provider_id",
    "stt_budget_minutes_per_hour",
)


@router.patch("/cameras/{camera_id}/audio")
async def patch_camera_audio(
    camera_id: uuid.UUID,
    body: CameraAudioPatch,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    ip = request.client.host if request.client else None
    changes = body.model_dump(exclude_unset=True)
    for field, new_value in changes.items():
        old_value = getattr(cam, field, None)
        if old_value == new_value:
            continue
        setattr(cam, field, new_value)
        # Privacy-relevant flips get an audit row. Every field in the
        # patch body is privacy-relevant, so we log all of them.
        if field in _AUDIT_FIELDS:
            db.add(
                AudioAuditLog(
                    camera_id=cam.id,
                    user_id=user.id,
                    field=field,
                    old_value=str(old_value) if old_value is not None else None,
                    new_value=str(new_value) if new_value is not None else None,
                    ip=ip,
                )
            )
    await db.commit()
    await db.refresh(cam)
    return {
        "id": str(cam.id),
        "audio_capture_enabled": cam.audio_capture_enabled,
        "audio_transcribe_enabled": cam.audio_transcribe_enabled,
        "audio_store_raw": cam.audio_store_raw,
        "transcript_store": cam.transcript_store,
        "audio_language": cam.audio_language,
        "audio_retention_days": cam.audio_retention_days,
        "transcript_retention_days": cam.transcript_retention_days,
        "stt_provider_id": str(cam.stt_provider_id) if cam.stt_provider_id else None,
        "stt_budget_minutes_per_hour": cam.stt_budget_minutes_per_hour,
    }
