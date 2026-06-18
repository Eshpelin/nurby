import asyncio
import logging
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from services.api.recording_annotate import render_annotated
from shared.auth import get_current_user, require_admin, require_query_token
from shared.camera_access import ALL, AllowedCameras, allowed_camera_ids, apply_camera_filter
from shared.config import settings
from shared.database import get_db
from shared.models import Camera, Observation, Recording, User
from shared.paths import escape_like, resolve_inside
from shared.schemas import RecordingResponse

# A bundle download is capped so a too-broad range can't build an enormous
# zip / temp file. Over either limit returns 413 asking to narrow the window.
_BUNDLE_MAX_FILES = 200
_BUNDLE_MAX_BYTES = 5 * 1024**3  # 5 GB

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


def _camera_in_scope(allowed: AllowedCameras, camera_id: uuid.UUID | None) -> bool:
    """True when ``camera_id`` is visible under the ``allowed`` ACL.

    ``ALL`` (admin / zero-grant) sees everything. For a concrete allowlist,
    a row with no camera is treated as out of scope for restricted users."""
    if allowed is ALL:
        return True
    return camera_id is not None and camera_id in allowed


async def _user_from_query_token(token: str | None, db: AsyncSession) -> User:
    """Resolve a ``?token=`` media-route caller to a live User.

    Raises 401 on a missing/invalid token (via ``require_query_token``) and
    on a deactivated/unknown user, mirroring ``get_current_user``."""
    user_id = require_query_token(token)
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


async def _get_recording_or_404(
    recording_id: uuid.UUID,
    db: AsyncSession,
    allowed: AllowedCameras = ALL,
) -> Recording:
    """Load a recording, 404ing when it is absent *or* outside the caller's
    camera ACL (issue #40).

    The out-of-scope case returns 404 (not 403) on purpose: a restricted
    user must not be able to probe which recording ids exist on cameras they
    cannot see. ``allowed`` defaults to ``ALL`` so unscoped callers behave
    exactly as before."""
    recording = await db.get(Recording, recording_id)
    if not recording or not _camera_in_scope(allowed, recording.camera_id):
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


def _filtered_recordings_query(
    camera_id: uuid.UUID | None,
    from_: datetime | None,
    to: datetime | None,
    object_label: str | None,
    allowed: AllowedCameras = ALL,
):
    """Base SELECT for recordings, with optional camera / time-window / object
    filters. The object filter keeps recordings whose window overlaps an
    observation carrying that label (reuses the observations.py label match).

    ``allowed`` is the per-user camera ACL (issue #40); it defaults to
    ``ALL`` (no filter) so existing callers and tests are unaffected."""
    query = apply_camera_filter(select(Recording), allowed, Recording.camera_id)
    if camera_id:
        query = query.where(Recording.camera_id == camera_id)
    # A recording occupies the window [started_at, window_end]; window_end falls
    # back to started_at + duration (default 1h) when ended_at is NULL (still
    # recording). The from/to range must match on window OVERLAP, not just on
    # started_at, otherwise a recording that began before `from` but is still
    # running (or ended inside the window) is wrongly dropped.
    window_end = func.coalesce(
        Recording.ended_at,
        Recording.started_at
        + func.make_interval(0, 0, 0, 0, 0, 0, func.coalesce(Recording.duration_seconds, 3600)),
    )
    if from_:
        query = query.where(window_end >= from_)
    if to:
        query = query.where(Recording.started_at <= to)
    if object_label:
        # An observation belongs to a recording if it falls within the
        # recording's window: [started_at, ended_at or started_at+duration].
        obs_exists = (
            select(Observation.id)
            .where(Observation.camera_id == Recording.camera_id)
            .where(Observation.started_at >= Recording.started_at)
            .where(Observation.started_at <= window_end)
            .where(
                cast(Observation.object_detections, String).ilike(
                    f'%"label": "{escape_like(object_label)}"%', escape="\\"
                )
            )
            .correlate(Recording)
            .exists()
        )
        query = query.where(obs_exists)
    return query


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from", description="Inclusive start (ISO 8601)"),
    to: datetime | None = Query(default=None, description="Inclusive end (ISO 8601)"),
    object: str | None = Query(default=None, description="Only recordings containing this object label"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    query = (
        _filtered_recordings_query(camera_id, from_, to, object, allowed)
        .order_by(Recording.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


def _build_zip(entries: list[tuple[str, str]], zip_path: str) -> None:
    """Write a stored (uncompressed) zip of (arcname, src_path) pairs. Sync;
    run in an executor. mp4 is already compressed, so ZIP_STORED just bundles."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for arcname, src in entries:
            zf.write(src, arcname)


@router.get("/download-bundle")
async def download_bundle(
    token: str | None = Query(None),
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, description="Inclusive end (ISO 8601)"),
    object: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Download every recording matching the filters as a single zip. Bundles
    the original files (non-destructive); capped by file count + total size."""
    user_id = require_query_token(token)
    # Scope the bundle to the caller's allowed cameras (issue #40). The
    # token only carries a user id, so load the user to resolve the ACL.
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    allowed = await allowed_camera_ids(user, db)
    query = _filtered_recordings_query(camera_id, from_, to, object, allowed).order_by(
        Recording.started_at.asc()
    )
    recs = (await db.execute(query)).scalars().all()

    entries: list[tuple[str, str]] = []
    total = 0
    for r in recs:
        path = resolve_inside(_resolve_recording_path(r), settings.recordings_path)
        if path is None or not os.path.exists(path):
            continue
        total += os.path.getsize(path)
        if len(entries) >= _BUNDLE_MAX_FILES or total > _BUNDLE_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Selected range is too large to bundle. Narrow the time window or camera.",
            )
        arcname = f"{r.started_at:%Y%m%d-%H%M%S}-{os.path.basename(path)}"
        entries.append((arcname, path))

    if not entries:
        raise HTTPException(status_code=404, detail="No recordings match those filters")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _build_zip, entries, tmp.name)
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename="nurby-recordings.zip",
        background=BackgroundTask(os.remove, tmp.name),
    )


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(
    recording_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    return await _get_recording_or_404(recording_id, db, allowed)


@router.get("/{recording_id}/stream")
async def stream_recording(
    recording_id: uuid.UUID, token: str | None = Query(None), db: AsyncSession = Depends(get_db)
):
    # Played in a <video src>, which cannot send an auth header. accept the
    # JWT as ?token= instead (same as thumbnails).
    user = await _user_from_query_token(token, db)
    allowed = await allowed_camera_ids(user, db)
    recording = await _get_recording_or_404(recording_id, db, allowed)
    path = _get_disk_path_or_404(recording)
    return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))


@router.get("/{recording_id}/camera", response_model=dict)
async def get_recording_camera(
    recording_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    recording = await _get_recording_or_404(recording_id, db, allowed)
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
    user = await _user_from_query_token(token, db)
    allowed = await allowed_camera_ids(user, db)
    recording = await _get_recording_or_404(recording_id, db, allowed)
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
async def delete_recording(
    recording_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
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
