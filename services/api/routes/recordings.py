import asyncio
import logging
import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.recording_annotate import render_annotated
from shared.auth import get_current_user, require_admin, require_query_token
from shared.database import get_db
from shared.models import Camera, Observation, Recording, User
from shared.paths import resolve_inside
from shared.schemas import RecordingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_RELATIVE_PREFIXES = ["./recordings/", "recordings/", "./"]


def _resolve_recording_path_raw(file_path: str) -> str:
    """Turn a stored (possibly relative) file path string into an absolute disk path."""
    from shared.config import settings

    if os.path.isabs(file_path):
        return file_path

    rel = file_path
    for prefix in _RELATIVE_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(os.path.abspath(settings.recordings_path), rel)


def _resolve_recording_path(recording: Recording) -> str:
    """Turn a stored (possibly relative) file_path into an absolute disk path."""
    return _resolve_recording_path_raw(recording.file_path)


async def _get_recording_or_404(
    recording_id: uuid.UUID, db: AsyncSession
) -> Recording:
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def _get_disk_path_or_404(recording: Recording) -> str:
    from shared.config import settings as _settings
    path = resolve_inside(_resolve_recording_path(recording), _settings.recordings_path)
    if path is None:
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Recording file not found on disk")
    return path


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    query = select(Recording).order_by(Recording.started_at.desc()).limit(limit).offset(offset)
    if camera_id:
        query = query.where(Recording.camera_id == camera_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(recording_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _get_recording_or_404(recording_id, db)


@router.get("/{recording_id}/stream")
async def stream_recording(recording_id: uuid.UUID, token: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    # Played in a <video src>, which cannot send an auth header. accept the
    # JWT as ?token= instead (same as thumbnails).
    require_query_token(token)
    recording = await _get_recording_or_404(recording_id, db)
    path = _get_disk_path_or_404(recording)
    return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))


@router.get("/{recording_id}/camera", response_model=dict)
async def get_recording_camera(recording_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    recording = await _get_recording_or_404(recording_id, db)
    camera = await db.get(Camera, recording.camera_id)
    return {"camera_name": camera.name if camera else "Unknown", "camera_id": str(recording.camera_id)}


async def _annotated_copy(
    recording: Recording, src_path: str, db: AsyncSession, opts: dict
) -> str:
    """Render (or reuse cached) an annotated copy of the recording. Falls back
    to the original on any failure so a download never 500s. Non-destructive:
    the stored recording is never modified."""
    cam = await db.get(Camera, recording.camera_id)
    end = recording.ended_at or (
        recording.started_at + timedelta(seconds=recording.duration_seconds or 3600)
    )
    rows = (
        await db.execute(
            select(Observation)
            .where(Observation.camera_id == recording.camera_id)
            .where(Observation.started_at >= recording.started_at)
            .where(Observation.started_at <= end)
            .order_by(Observation.started_at.asc())
        )
    ).scalars().all()
    obs = [
        {
            "offset": max(0.0, (o.started_at - recording.started_at).total_seconds()),
            "object_detections": o.object_detections,
            "vlm_description": o.vlm_description,
        }
        for o in rows
    ]
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None, render_annotated, src_path, obs, opts,
            cam.width if cam else None, cam.height if cam else None,
        )
    except Exception:
        logger.exception("annotated render failed for %s; serving original", recording.id)
        return src_path


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: uuid.UUID,
    token: str | None = Query(None),
    boxes: bool = Query(False),
    captions: bool = Query(False),
    strip: bool = Query(False),
    min_conf: float = Query(0.8, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    # Downloaded via <a href download>, which cannot send an auth header.
    require_query_token(token)
    recording = await _get_recording_or_404(recording_id, db)
    path = _get_disk_path_or_404(recording)

    # With no annotation flags this serves the pristine original (unchanged
    # behaviour). With any flag we render/serve a cached annotated copy.
    if boxes or captions or strip:
        path = await _annotated_copy(
            recording, path, db,
            {"boxes": boxes, "captions": captions, "strip": strip, "min_conf": min_conf},
        )
        filename = f"{os.path.splitext(os.path.basename(path))[0]}-annotated.mp4"
    else:
        filename = os.path.basename(path)

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(recording_id: uuid.UUID, _current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    rec_path = _resolve_recording_path(recording)
    try:
        os.remove(rec_path)
    except OSError:
        pass

    if recording.thumbnail_path:
        try:
            os.remove(_resolve_recording_path_raw(recording.thumbnail_path))
        except OSError:
            pass

    await db.delete(recording)
    await db.commit()
