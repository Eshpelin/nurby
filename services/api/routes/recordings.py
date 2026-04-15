import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_db
from shared.models import Camera, Recording
from shared.schemas import RecordingResponse

router = APIRouter()


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Recording).order_by(Recording.started_at.desc()).limit(limit).offset(offset)
    if camera_id:
        query = query.where(Recording.camera_id == camera_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@router.get("/{recording_id}/stream")
async def stream_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from shared.config import settings

    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Resolve file path. Stored paths may be relative to recordings_path
    file_path = recording.file_path
    if not os.path.isabs(file_path):
        # Strip leading ./ or recordings/ prefix to get relative portion
        rel = file_path
        for prefix in ["./recordings/", "recordings/", "./"]:
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        file_path = os.path.join(os.path.abspath(settings.recordings_path), rel)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Recording file not found on disk")
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=os.path.basename(file_path),
    )


@router.get("/{recording_id}/camera", response_model=dict)
async def get_recording_camera(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    camera = await db.get(Camera, recording.camera_id)
    return {"camera_name": camera.name if camera else "Unknown", "camera_id": str(recording.camera_id)}


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    await db.delete(recording)
    await db.commit()
