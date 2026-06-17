"""Audio file streaming + per-camera audio config patch.

The /api/audio/{capture_id} endpoint accepts both Authorization header
and a ``?token=`` query parameter so HTML5 ``<audio>`` tags can load
clips without JS-side header injection.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin, require_query_token
from shared.config import settings
from shared.database import get_db
from shared.models import AudioAuditLog, AudioCapture, Camera, User
from shared.paths import resolve_inside

router = APIRouter()


@router.get("/{capture_id}")
async def stream_audio(
    capture_id: uuid.UUID,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    require_query_token(token)
    cap = await db.get(AudioCapture, capture_id)
    if cap is None:
        raise HTTPException(status_code=404, detail="Audio capture not found")
    path = resolve_inside(cap.file_path, settings.audio_storage_path)
    if path is None:
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
    audio_stt_beam_size: int | None = Field(default=None, ge=1, le=10)
    audio_stt_condition_on_previous_text: bool | None = None
    audio_stt_no_speech_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


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
    user: User = Depends(require_admin),
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
        "audio_stt_beam_size": cam.audio_stt_beam_size,
        "audio_stt_condition_on_previous_text": cam.audio_stt_condition_on_previous_text,
        "audio_stt_no_speech_threshold": cam.audio_stt_no_speech_threshold,
    }
