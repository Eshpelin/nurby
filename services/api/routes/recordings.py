import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user, require_admin
from shared.database import get_db
from shared.models import Camera, Recording, User
from shared.schemas import RecordingResponse

router = APIRouter()

_RELATIVE_PREFIXES = ["./recordings/", "recordings/", "./"]


def _resolve_recording_path(recording: Recording) -> str:
    """Turn a stored (possibly relative) file_path into an absolute disk path."""
    from shared.config import settings

    file_path = recording.file_path
    if os.path.isabs(file_path):
        return file_path

    rel = file_path
    for prefix in _RELATIVE_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(os.path.abspath(settings.recordings_path), rel)


async def _get_recording_or_404(
    recording_id: uuid.UUID, db: AsyncSession
) -> Recording:
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def _get_disk_path_or_404(recording: Recording) -> str:
    path = _resolve_recording_path(recording)
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
async def stream_recording(recording_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    recording = await _get_recording_or_404(recording_id, db)
    path = _get_disk_path_or_404(recording)
    return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))


@router.get("/{recording_id}/camera", response_model=dict)
async def get_recording_camera(recording_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    recording = await _get_recording_or_404(recording_id, db)
    camera = await db.get(Camera, recording.camera_id)
    return {"camera_name": camera.name if camera else "Unknown", "camera_id": str(recording.camera_id)}


@router.get("/{recording_id}/download")
async def download_recording(recording_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    recording = await _get_recording_or_404(recording_id, db)
    path = _get_disk_path_or_404(recording)
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
    await db.delete(recording)
    await db.commit()
