import asyncio
import logging
import os
import subprocess
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
from shared.ffmpeg_safe import (
    PROTOCOL_WHITELIST_ARGS,
    DisallowedFfmpegArgError,
    assert_allowed_args,
)
from shared.models import Camera, Observation, Person, Recording, Transcript, User, Vehicle
from shared.paths import escape_like, resolve_inside, safe_getsize
from shared.schemas import RecordingResponse

# A trimmed clip is capped so a request can't ask us to transcode an
# arbitrarily long segment on the API host. Over this returns 400.
_CLIP_MAX_SECONDS = 600

# A facet lookup is bounded so a caller can't ask us to aggregate an
# unbounded id list in one shot. The recordings grid pages at 24, so 200
# comfortably covers a page (plus slack) while capping the fan-out.
_FACETS_MAX_IDS = 200

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


def _recording_window_end():
    """SQL expression for a recording's window end. window_end falls back to
    started_at + duration (default 1h) when ended_at is NULL (still recording)."""
    return func.coalesce(
        Recording.ended_at,
        Recording.started_at
        + func.make_interval(0, 0, 0, 0, 0, 0, func.coalesce(Recording.duration_seconds, 3600)),
    )


def _overlapping_observation_matching(clause):
    """EXISTS() over observations that fall inside the correlated recording's
    window AND satisfy ``clause`` (a detection-JSON match). An observation
    belongs to a recording when its start falls within [started_at, window_end]."""
    return (
        select(Observation.id)
        .where(Observation.camera_id == Recording.camera_id)
        .where(Observation.started_at >= Recording.started_at)
        .where(Observation.started_at <= _recording_window_end())
        .where(clause)
        .correlate(Recording)
        .exists()
    )


async def _filtered_recordings_query(
    db: AsyncSession,
    camera_id: uuid.UUID | None,
    from_: datetime | None,
    to: datetime | None,
    object_labels: list[str] | None = None,
    person_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    allowed: AllowedCameras = ALL,
):
    """Base SELECT for recordings, with optional camera / time-window / object /
    person / vehicle filters. A recording matches when its window overlaps an
    observation carrying the requested detection (reuses the same detection-JSON
    match as observations.py / events.py).

    Filter groups combine with AND (a recording must satisfy every provided
    group); within the object group, labels combine with OR (any of them).
    Returns ``None`` when a person filter resolves to nobody, so the caller can
    short-circuit to an empty result.

    ``allowed`` is the per-user camera ACL (issue #40); it defaults to
    ``ALL`` (no filter) so existing callers and tests are unaffected."""
    query = apply_camera_filter(select(Recording), allowed, Recording.camera_id)
    if camera_id:
        query = query.where(Recording.camera_id == camera_id)
    # The from/to range must match on window OVERLAP, not just on started_at,
    # otherwise a recording that began before `from` but is still running (or
    # ended inside the window) is wrongly dropped.
    window_end = _recording_window_end()
    if from_:
        query = query.where(window_end >= from_)
    if to:
        query = query.where(Recording.started_at <= to)

    labels = [o for o in (object_labels or []) if o and o.strip()]
    if labels:
        # OR across selected labels: keep recordings whose window overlaps an
        # observation carrying ANY of them.
        from sqlalchemy import or_

        clause = or_(
            *[
                cast(Observation.object_detections, String).ilike(
                    f'%"label": "{escape_like(lbl)}"%', escape="\\"
                )
                for lbl in labels
            ]
        )
        query = query.where(_overlapping_observation_matching(clause))

    if person_id:
        # person_detections stores the canonical display_name (same match as
        # events.py / observations.py). Resolve the id; unknown id -> no rows.
        name = (
            await db.execute(select(Person.display_name).where(Person.id == person_id))
        ).scalars().first()
        if not name:
            return None
        query = query.where(
            _overlapping_observation_matching(
                cast(Observation.person_detections, String).ilike(
                    f'%"person_name": "{escape_like(name)}"%', escape="\\"
                )
            )
        )

    if vehicle_id:
        # vehicle_detections stores vehicle_id directly (no name resolution).
        query = query.where(
            _overlapping_observation_matching(
                cast(Observation.vehicle_detections, String).ilike(
                    f'%"vehicle_id": "{escape_like(str(vehicle_id))}"%', escape="\\"
                )
            )
        )
    return query


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from", description="Inclusive start (ISO 8601)"),
    to: datetime | None = Query(default=None, description="Inclusive end (ISO 8601)"),
    object: list[str] = Query(
        default=[], description="Only recordings containing any of these object labels (repeatable)"
    ),
    person_id: uuid.UUID | None = Query(
        default=None, description="Only recordings whose window overlaps a sighting of this person"
    ),
    vehicle_id: uuid.UUID | None = Query(
        default=None, description="Only recordings whose window overlaps a sighting of this vehicle"
    ),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    query = await _filtered_recordings_query(
        db, camera_id, from_, to, object, person_id, vehicle_id, allowed
    )
    if query is None:
        return []
    query = query.order_by(Recording.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


def _detection_labels(object_detections: dict | None) -> list[str]:
    """Distinct object labels from an observation's object_detections JSON."""
    if not isinstance(object_detections, dict):
        return []
    out: list[str] = []
    for obj in object_detections.get("objects") or []:
        if isinstance(obj, dict):
            label = obj.get("label")
            if isinstance(label, str) and label not in out:
                out.append(label)
    return out


def _detection_persons(person_detections: dict | None) -> list[str]:
    """Distinct named persons from an observation's person_detections JSON.
    Skips unnamed clusters (person_name is the canonical label when known)."""
    if not isinstance(person_detections, dict):
        return []
    out: list[str] = []
    for face in person_detections.get("faces") or []:
        if isinstance(face, dict):
            name = face.get("person_name")
            if isinstance(name, str) and name and name not in out:
                out.append(name)
    return out


def _detection_vehicles(vehicle_detections: dict | None) -> list[str]:
    """Distinct vehicle labels (plate when known, else type) from an
    observation's vehicle_detections JSON."""
    if not isinstance(vehicle_detections, dict):
        return []
    out: list[str] = []
    for v in vehicle_detections.get("vehicles") or []:
        if isinstance(v, dict):
            label = v.get("plate_text") or v.get("label") or "vehicle"
            if isinstance(label, str) and label not in out:
                out.append(label)
    return out


@router.get("/facets")
async def recordings_facets(
    ids: str = Query(..., description="Comma-separated recording ids to summarise"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-recording activity summary for the grid cards: which object classes,
    named people, and vehicles were seen during each recording's window, plus
    whether it carried any (unfiltered) audio transcript.

    Bounded to one page of ids. Runs two range-scoped queries (observations +
    transcripts) and buckets in Python by camera + time window, rather than one
    correlated query per recording, so the cost stays flat as the page fills."""
    id_list: list[uuid.UUID] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            id_list.append(uuid.UUID(raw))
        except ValueError:
            continue
        if len(id_list) >= _FACETS_MAX_IDS:
            break
    if not id_list:
        return {}

    allowed = await allowed_camera_ids(current_user, db)
    recs = (
        await db.execute(
            apply_camera_filter(
                select(Recording).where(Recording.id.in_(id_list)),
                allowed,
                Recording.camera_id,
            )
        )
    ).scalars().all()
    if not recs:
        return {}

    # Per-recording window [started_at, window_end] computed in Python.
    windows: list[tuple[Recording, datetime]] = []
    for r in recs:
        end = r.ended_at or (r.started_at + timedelta(seconds=r.duration_seconds or 3600))
        windows.append((r, end))

    cam_ids = {r.camera_id for r, _ in windows}
    t_min = min(r.started_at for r, _ in windows)
    t_max = max(end for _, end in windows)

    obs_rows = (
        await db.execute(
            select(Observation)
            .where(Observation.camera_id.in_(cam_ids))
            .where(Observation.started_at >= t_min)
            .where(Observation.started_at <= t_max)
        )
    ).scalars().all()

    tx_rows = (
        await db.execute(
            select(Transcript.camera_id, Transcript.started_at)
            .where(Transcript.camera_id.in_(cam_ids))
            .where(Transcript.started_at >= t_min)
            .where(Transcript.started_at <= t_max)
            .where(Transcript.filtered.is_(False))
        )
    ).all()

    result: dict[str, dict] = {}
    for r, end in windows:
        objs: list[str] = []
        persons: list[str] = []
        vehicles: list[str] = []
        for o in obs_rows:
            if o.camera_id != r.camera_id:
                continue
            if not (r.started_at <= o.started_at <= end):
                continue
            for lbl in _detection_labels(o.object_detections):
                if lbl not in objs:
                    objs.append(lbl)
            for name in _detection_persons(o.person_detections):
                if name not in persons:
                    persons.append(name)
            for v in _detection_vehicles(o.vehicle_detections):
                if v not in vehicles:
                    vehicles.append(v)
        has_audio = any(
            cam == r.camera_id and r.started_at <= ts <= end for cam, ts in tx_rows
        )
        # Cap chip counts so a busy hour doesn't bloat the card / payload.
        result[str(r.id)] = {
            "objects": objs[:6],
            "persons": persons[:4],
            "vehicles": vehicles[:4],
            "has_audio": has_audio,
        }
    return result


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
    object: list[str] = Query(default=[]),
    person_id: uuid.UUID | None = Query(default=None),
    vehicle_id: uuid.UUID | None = Query(default=None),
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
    query = await _filtered_recordings_query(
        db, camera_id, from_, to, object, person_id, vehicle_id, allowed
    )
    if query is None:
        raise HTTPException(status_code=404, detail="No recordings match those filters")
    query = query.order_by(Recording.started_at.asc())
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


def _render_clip(src_path: str, out_path: str, start: float, duration: float) -> bool:
    """Cut [start, start+duration] out of src into out (re-encoded, faststart).
    Sync; run in an executor. Input-seek (-ss before -i) is fast; a re-encode
    keeps the cut frame-accurate at the requested start rather than snapping to
    the previous keyframe. Returns True on a non-empty output."""
    cmd = [
        "ffmpeg", *PROTOCOL_WHITELIST_ARGS, "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", src_path, "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart",
        out_path,
    ]
    assert_allowed_args(cmd)
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        logger.warning("clip ffmpeg failed rc=%s: %s", proc.returncode, proc.stderr[-300:])
        return False
    return safe_getsize(out_path) > 0


@router.get("/{recording_id}/clip")
async def download_clip(
    recording_id: uuid.UUID,
    start: float = Query(..., ge=0, description="Clip start, seconds from recording start"),
    end: float = Query(..., gt=0, description="Clip end, seconds from recording start"),
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Download just [start, end] of a recording as its own mp4, cut server-side
    so the caller never pulls the whole file. Offloaded to a thread (ffmpeg is
    blocking), mirroring the annotated-download path."""
    user = await _user_from_query_token(token, db)
    allowed = await allowed_camera_ids(user, db)
    recording = await _get_recording_or_404(recording_id, db, allowed)
    src_path = _get_disk_path_or_404(recording)

    if end <= start:
        raise HTTPException(status_code=400, detail="end must be greater than start")
    # Clamp to the known recording length so a too-long `end` doesn't ask ffmpeg
    # to read past EOF; then enforce the max clip duration.
    if recording.duration_seconds:
        end = min(end, float(recording.duration_seconds))
    duration = end - start
    if duration <= 0:
        raise HTTPException(status_code=400, detail="Requested range is outside the recording")
    if duration > _CLIP_MAX_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Clip too long ({int(duration)}s). Max is {_CLIP_MAX_SECONDS}s.",
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()
    loop = asyncio.get_event_loop()
    try:
        ok = await loop.run_in_executor(None, _render_clip, src_path, tmp.name, start, duration)
    except (DisallowedFfmpegArgError, subprocess.TimeoutExpired, OSError) as exc:
        os.remove(tmp.name)
        logger.error("clip render error for %s: %s", recording.id, exc)
        raise HTTPException(status_code=500, detail="Could not build clip") from exc
    if not ok:
        os.remove(tmp.name)
        raise HTTPException(status_code=500, detail="Could not build clip")

    filename = f"{recording.started_at:%Y%m%d-%H%M%S}-clip-{int(start)}s-{int(end)}s.mp4"
    return FileResponse(
        tmp.name,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(os.remove, tmp.name),
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
