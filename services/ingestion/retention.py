"""
Recording retention cleanup.

Periodically checks each camera's retention policy and deletes
old recordings that exceed time or size limits.

With an archive destination set (shared/archive.py, issue #270), a
recording that leaves its camera's local window is queued for upload to
the archive instead of deleted, and the archive is pruned on its own
lifetime (``archive_retention_days``).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, select

from shared.config import settings
from shared.database import async_session
from shared.models import (
    AudioCapture,
    AudioDetection,
    Camera,
    Conversation,
    Recording,
    Transcript,
)

logger = logging.getLogger("nurby.ingestion.retention")

CLEANUP_INTERVAL = 3600  # run every hour

_RELATIVE_PREFIXES = ["./recordings/", "recordings/", "./"]

_THUMBNAIL_PREFIXES = ["./thumbnails/", "thumbnails/", "./"]

# Observation retention (issue #213) batch bounds. Rows are deleted in
# bounded batches so a first run against a large backlog cannot hold the
# hourly loop (or lock the table) for minutes; whatever does not fit in
# one sweep is picked up by the next hourly pass. pgvector-backed tables
# make big deletes disproportionately expensive, so many small deletes
# beat one huge one.
OBSERVATION_PRUNE_BATCH = 500
OBSERVATION_PRUNE_MAX_BATCHES = 20


def _resolve_path(file_path: str | None, camera_id=None) -> str | None:
    """Turn a stored (possibly relative) file path into an absolute disk
    path under the recordings root. Sync on purpose: callers pass the
    root they already resolved (per-camera since storage profiles)."""
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    rel = file_path
    for prefix in _RELATIVE_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(os.path.abspath(settings.recordings_path), rel)


async def _delete_remote_copy(rec) -> bool:
    """Best-effort removal of the remote (FTP/S3) copy of an expired
    recording (issues #269, #270). Uses the profile snapshot stored at
    upload time, so the remote is cleaned even after the camera moved to
    another profile. Returns True when there is no remote copy left to
    worry about. A failed delete orphans one object, logged, not fatal."""
    if rec.remote_state != "uploaded" or not rec.remote_profile_id or not rec.remote_path:
        return True
    try:
        from shared.models import StorageProfile
        from shared.remote_storage import parse_remote_config, remote_delete

        async with async_session() as db:
            profile = await db.get(StorageProfile, rec.remote_profile_id)
        cfg = parse_remote_config(profile.kind, profile.config_enc) if profile else None
        if cfg is None:
            logger.warning(
                "Cannot delete remote copy of %s: storage profile gone", rec.id
            )
            return False
        ok, detail = await remote_delete(profile.kind, cfg, rec.remote_path)
        if not ok:
            logger.warning("Remote delete failed for %s: %s", rec.id, detail)
        return ok
    except Exception:
        logger.exception("remote delete failed for %s", getattr(rec, "id", "?"))
        return False


def mark_for_archive(rec, archive) -> None:
    """Queue ``rec`` for the upload worker to move into the archive. The
    local file stays until the upload is verified."""
    from shared.remote_storage import remote_path_for

    rec.remote_state = "pending"
    rec.remote_profile_id = archive.profile_id
    rec.remote_path = remote_path_for(archive.root, rec.file_path)
    rec.remote_attempts = 0
    rec.remote_error = None


def archive_owns(rec, archive) -> bool:
    """True when the archive is (or is about to be) responsible for this
    recording, so local retention must leave it alone. Includes a failed
    archive upload: the local file is then the only copy."""
    return archive is not None and rec.remote_profile_id == archive.profile_id


async def _resolve_camera_path(file_path: str | None, camera_id) -> str | None:
    """Recording-file variant: resolves against the ROOT THE CAMERA
    RECORDS INTO (its storage profile, else the global root)."""
    if not file_path:
        return None
    from shared.storage_paths import recordings_root_for

    root = await recordings_root_for(camera_id)
    if os.path.isabs(file_path):
        return file_path
    rel = file_path
    for prefix in _RELATIVE_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(os.path.abspath(root), rel)


def _resolve_audio_path(file_path: str | None) -> str | None:
    """Resolve an AudioCapture path to an absolute disk path.

    Audio blobs are written under ``settings.audio_storage_path`` (a
    different base than recordings), e.g. ``./audio_clips/<cam>/<day>/<id>
    .opus``. Resolving against that base makes cleanup independent of the
    process CWD. Relying on the stored relative path only worked while the
    retention loop happened to run from the same directory as the writer.
    """
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    base = os.path.abspath(settings.audio_storage_path)
    rel = file_path
    for prefix in ("./audio_clips/", "audio_clips/", "./"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(base, rel)


def _resolve_thumbnail_path(file_path: str | None) -> str | None:
    """Resolve an observation thumbnail/clean-frame path to an absolute path.

    Observation thumbnails are written under
    ``settings.thumbnails_path/observations`` (pipeline.THUMBNAIL_DIR) with
    paths stored the same (possibly relative) way as recordings. Strip the
    thumbnail base prefix so both the default relative path and an
    absolute custom ``thumbnails_path`` resolve correctly.
    """
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    base = os.path.abspath(settings.thumbnails_path)
    rel = file_path
    for prefix in _THUMBNAIL_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(base, rel)


def _remove_file(path: str | None) -> tuple[int, bool]:
    """Remove a file from disk. Returns (size_freed, success)."""
    if not path or not os.path.exists(path):
        return 0, True  # nothing to delete is fine
    try:
        size = os.path.getsize(path)
        os.remove(path)
        return size, True
    except OSError:
        logger.warning("Could not delete file %s", path)
        return 0, False


def prune_motion_samples_stmt(cutoff: datetime):
    """Build the bulk DELETE for motion_samples older than ``cutoff``.

    Pure builder (no DB), so the SQL can be compiled/asserted in tests the same
    way ``upsert_motion_sample_stmt`` is (cf. tests/test_motion_query.py). A
    single set-based DELETE with a timestamp predicate, NOT a row-by-row load +
    delete: the writer emits ~1 row/camera/second so the table is large and the
    per-row pattern the other retention sweeps use would not scale here. Safe
    no-op when the table is empty (the DELETE simply affects zero rows).
    """
    from shared.models import MotionSample

    return delete(MotionSample).where(MotionSample.bucket < cutoff)


def prune_observations_stmt(observation_ids: list):
    """Build the bulk DELETE for one observation-retention batch (issue #213).

    Pure builder (no DB) so tests can compile it. Children (VLM passes,
    actions, grounding results, incident junctions) are removed by the
    DB-level ``ondelete=CASCADE`` FKs; agent references go NULL via
    ``ondelete=SET NULL``. Events reference observations without an FK
    (deliberately) and keep their payload text, so nothing dangles at the
    schema level.
    """
    from shared.models import Observation

    return delete(Observation).where(Observation.id.in_(observation_ids))


class RetentionManager:
    async def run(self):
        """Periodically enforce retention policies for all cameras."""
        while True:
            try:
                await self._enforce_all()
            except Exception:
                logger.exception("Retention cleanup failed")
            await asyncio.sleep(CLEANUP_INTERVAL)

    async def _enforce_all(self):
        async with async_session() as db:
            # Recordings retention only fires for cameras with a non-off
            # policy. Audio + transcript retention runs on every camera
            # because the columns always have a meaningful default and
            # the user can lower them per camera.
            all_cams = list((await db.execute(select(Camera))).scalars().all())

        from shared.archive import archive_target

        try:
            archive = await archive_target()
        except Exception:
            logger.exception("Could not read the archive destination; deleting as usual")
            archive = None

        rec_cams = [c for c in all_cams if (c.retention_mode or "none") != "none"]
        if rec_cams:
            logger.info(
                "Running recording retention cleanup for %d cameras", len(rec_cams)
            )
            for cam in rec_cams:
                try:
                    if cam.retention_mode == "time":
                        await self._enforce_time(cam, cam.retention_days, archive)
                    elif cam.retention_mode == "size":
                        await self._enforce_size(cam, cam.retention_gb, archive)
                except Exception:
                    logger.exception(
                        "Recording retention failed for camera %s", cam.id
                    )

        try:
            await self._enforce_archive_retention(archive)
        except Exception:
            logger.exception("Archive retention failed")

        # Audio + transcript retention. always time-based.
        for cam in all_cams:
            try:
                await self._enforce_audio_retention(cam)
            except Exception:
                logger.exception(
                    "Audio retention failed for camera %s", cam.id
                )
            try:
                await self._enforce_transcript_retention(cam)
            except Exception:
                logger.exception(
                    "Transcript retention failed for camera %s", cam.id
                )
            # Conversations and audio-event detections are derived audio
            # signals. They aged forever because nothing cleaned them up,
            # so a chatty camera grew the DB without bound. Tie both to the
            # transcript window since they are the same class of data.
            try:
                await self._enforce_conversation_retention(cam)
            except Exception:
                logger.exception(
                    "Conversation retention failed for camera %s", cam.id
                )
            try:
                await self._enforce_audio_event_retention(cam)
            except Exception:
                logger.exception(
                    "Audio event retention failed for camera %s", cam.id
                )

        # HAR action segments. System-wide window (one setting), not per-camera, because
        # continuous HAR would otherwise grow person_action_segments without bound the same
        # way conversations/detections did. Best-effort; failure never blocks the loop.
        try:
            await self._enforce_har_segment_retention()
        except Exception:
            logger.exception("HAR segment retention failed")

        # Motion-score samples (#37). System-wide window (one setting), like HAR
        # segments. The motion-series writer emits ~1 row/camera/second once
        # enabled, so without this sweep motion_samples would grow without bound.
        # Best-effort; failure never blocks the loop.
        try:
            await self._enforce_motion_sample_retention()
        except Exception:
            logger.exception("Motion sample retention failed")

        # Observations + thumbnails + VLM passes (#213). System-wide window
        # (one setting), like HAR segments / motion samples. Nothing pruned
        # these before, so long-running installs grew observations, their
        # thumbnail JPEGs and observation_vlm_passes without bound. Best-effort;
        # failure never blocks the loop.
        try:
            await self._enforce_observation_retention()
        except Exception:
            logger.exception("Observation retention failed")

    async def _enforce_motion_sample_retention(self) -> None:
        """Delete motion_samples rows older than ``motion_series_retention_days``.

        Single bulk DELETE with a timestamp predicate (no row-by-row load), since
        the writer produces ~1 row/camera/second. A no-op when the window is
        disabled (days <= 0) and a harmless zero-row DELETE when the table is
        empty.
        """
        from shared.app_settings import get_setting

        days = int(await get_setting("motion_series_retention_days", 7) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            result = await db.execute(prune_motion_samples_stmt(cutoff))
            await db.commit()
            deleted = result.rowcount or 0
            if deleted:
                logger.info(
                    "Motion sample retention. deleted %d rows (cutoff %s, %d days)",
                    deleted, cutoff.isoformat(), days,
                )

    async def _enforce_observation_retention(self) -> None:
        """Delete observations older than ``observation_retention_days``, with
        their thumbnail files (annotated + clean) and cascade-owned children.

        Each hourly sweep deletes at most ``OBSERVATION_PRUNE_BATCH`` x
        ``OBSERVATION_PRUNE_MAX_BATCHES`` rows in committed batches, so a
        first run against a large backlog stays bounded. Thumbnail removal
        is best-effort (conversations set the precedent): a stale orphaned
        JPEG is a far smaller problem than rows that never age out, because
        the recording — not the observation thumbnail — is the evidence.
        """
        from shared.app_settings import get_setting
        from shared.models import Observation

        days = int(await get_setting("observation_retention_days", 90) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        total = 0
        async with async_session() as db:
            for _batch in range(OBSERVATION_PRUNE_MAX_BATCHES):
                rows = (
                    await db.execute(
                        select(
                            Observation.id,
                            Observation.thumbnail_path,
                            Observation.clean_frame_path,
                        )
                        .where(Observation.started_at < cutoff)
                        .order_by(Observation.started_at.asc())
                        .limit(OBSERVATION_PRUNE_BATCH)
                    )
                ).all()
                if not rows:
                    break
                for obs_id, thumb, clean in rows:
                    _remove_file(_resolve_thumbnail_path(thumb))
                    if clean and clean != thumb:
                        _remove_file(_resolve_thumbnail_path(clean))
                await db.execute(prune_observations_stmt([r[0] for r in rows]))
                await db.commit()
                total += len(rows)
                if len(rows) < OBSERVATION_PRUNE_BATCH:
                    break
        if total:
            logger.info(
                "Observation retention. deleted %d observations (cutoff %s, %d days)",
                total, cutoff.isoformat(), days,
            )

    async def _enforce_har_segment_retention(self) -> None:
        """Delete person_action_segments older than ``har_segment_retention_days``."""
        from shared.app_settings import get_setting
        from shared.models import PersonActionSegment

        days = int(await get_setting("har_segment_retention_days", 30) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(PersonActionSegment).where(PersonActionSegment.started_at < cutoff)
                )
            ).scalars().all()
            for seg in rows:
                await db.delete(seg)
            if rows:
                await db.commit()
                logger.info(
                    "HAR segment retention. deleted %d segments (cutoff %s, %d days)",
                    len(rows), cutoff.isoformat(), days,
                )

    async def _enforce_audio_retention(self, camera: Camera) -> None:
        """Delete AudioCapture rows + opus blobs older than the camera's
        ``audio_retention_days``.

        Transcripts may keep a foreign key to the deleted capture.
        ``ondelete=SET NULL`` on the FK takes care of the column. The
        transcript text survives independently and falls under the
        transcript retention window.
        """
        days = int(getattr(camera, "audio_retention_days", 0) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            rows = list(
                (
                    await db.execute(
                        select(AudioCapture)
                        .where(AudioCapture.camera_id == camera.id)
                        .where(AudioCapture.started_at < cutoff)
                    )
                ).scalars().all()
            )
            if not rows:
                return
            freed_bytes = 0
            deleted = 0
            for cap in rows:
                # Audio paths are stored the same (possibly relative) way as
                # recordings, so resolve to an absolute disk path before
                # removing. Without this, a relative path never matches a
                # file on disk, the delete is a silent no-op, and the row is
                # dropped anyway, leaking the opus blob forever.
                _, ok = _remove_file(_resolve_audio_path(cap.file_path))
                if not ok:
                    logger.warning(
                        "Skipping DB delete for audio capture %s, file still on disk",
                        cap.id,
                    )
                    continue
                freed_bytes += int(cap.size_bytes or 0)
                await db.delete(cap)
                deleted += 1
            await db.commit()
            if deleted:
                logger.info(
                    "Audio retention for camera %s. deleted %d captures, freed %.2f MB (cutoff %s, %d days)",
                    camera.name or camera.id,
                    deleted,
                    freed_bytes / (1024 ** 2),
                    cutoff.isoformat(),
                    days,
                )

    async def _enforce_transcript_retention(self, camera: Camera) -> None:
        days = int(getattr(camera, "transcript_retention_days", 0) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            rows = list(
                (
                    await db.execute(
                        select(Transcript)
                        .where(Transcript.camera_id == camera.id)
                        .where(Transcript.started_at < cutoff)
                    )
                ).scalars().all()
            )
            if not rows:
                return
            for tx in rows:
                await db.delete(tx)
            await db.commit()
            logger.info(
                "Transcript retention for camera %s. deleted %d rows (cutoff %s, %d days)",
                camera.name or camera.id, len(rows), cutoff.isoformat(), days,
            )

    async def _enforce_conversation_retention(self, camera: Camera) -> None:
        """Delete finalized conversations older than the transcript window.

        Only finalized rows are removed. an open conversation is still
        accumulating and must be left alone regardless of age. Any
        attached clip file is removed best-effort.
        """
        days = int(getattr(camera, "transcript_retention_days", 0) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            rows = list(
                (
                    await db.execute(
                        select(Conversation)
                        .where(Conversation.camera_id == camera.id)
                        .where(Conversation.finalized.is_(True))
                        .where(Conversation.started_at < cutoff)
                    )
                ).scalars().all()
            )
            if not rows:
                return
            for conv in rows:
                _remove_file(await _resolve_camera_path(getattr(conv, "clip_path", None), getattr(conv, "camera_id", None)))
                await db.delete(conv)
            await db.commit()
            logger.info(
                "Conversation retention for camera %s. deleted %d rows (cutoff %s, %d days)",
                camera.name or camera.id, len(rows), cutoff.isoformat(), days,
            )

    async def _enforce_audio_event_retention(self, camera: Camera) -> None:
        """Delete audio-event detections older than the transcript window."""
        days = int(getattr(camera, "transcript_retention_days", 0) or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session() as db:
            rows = list(
                (
                    await db.execute(
                        select(AudioDetection)
                        .where(AudioDetection.camera_id == camera.id)
                        .where(AudioDetection.detected_at < cutoff)
                    )
                ).scalars().all()
            )
            if not rows:
                return
            for det in rows:
                await db.delete(det)
            await db.commit()
            logger.info(
                "Audio event retention for camera %s. deleted %d detections (cutoff %s, %d days)",
                camera.name or camera.id, len(rows), cutoff.isoformat(), days,
            )

    async def _enforce_archive_retention(self, archive, batch: int = 500) -> None:
        """Delete archived recordings older than ``archive_retention_days``
        (0 = keep forever). The row goes only once the remote object is
        gone, so a failed delete retries next hour instead of orphaning a
        billed object."""
        if archive is None or archive.retention_days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=archive.retention_days)
        async with async_session() as db:
            rows = (await db.execute(
                select(Recording)
                .where(Recording.remote_profile_id == archive.profile_id)
                .where(Recording.remote_state == "uploaded")
                .where(Recording.started_at < cutoff)
                .order_by(Recording.started_at.asc())
                .limit(batch)
            )).scalars().all()
            deleted = 0
            for rec in rows:
                if not await _delete_remote_copy(rec):
                    continue
                _remove_file(await _resolve_camera_path(rec.file_path, rec.camera_id))
                _remove_file(_resolve_path(rec.thumbnail_path))
                await db.delete(rec)
                deleted += 1
            await db.commit()
        if deleted:
            logger.info(
                "Archive retention. deleted %d recordings from %s older than %d days",
                deleted, archive.name, archive.retention_days,
            )

    async def _enforce_time(self, camera: Camera, retention_days: int, archive=None):
        """Recordings older than retention_days leave this machine: moved to
        the archive when one is set, deleted otherwise."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        reason = f"retention_time: older than {retention_days} days"

        async with async_session() as db:
            result = await db.execute(
                select(Recording).where(
                    and_(
                        Recording.camera_id == camera.id,
                        Recording.started_at < cutoff,
                    )
                )
            )
            old_recordings = list(result.scalars().all())

            if not old_recordings:
                return

            deleted_count = 0
            archived_count = 0
            freed_bytes = 0

            for rec in old_recordings:
                if archive_owns(rec, archive):
                    continue  # archived or on its way; the archive lifetime governs it
                if archive is not None and rec.remote_state is None:
                    mark_for_archive(rec, archive)
                    archived_count += 1
                    continue
                abs_path = await _resolve_camera_path(rec.file_path, rec.camera_id)
                size, ok = _remove_file(abs_path)
                if not ok:
                    logger.warning("Skipping DB delete for recording %s, file still on disk", rec.id)
                    continue
                freed_bytes += size
                _remove_file(_resolve_path(rec.thumbnail_path))
                await _delete_remote_copy(rec)

                logger.info(
                    "Deleting recording for camera %s, file %s, reason %s",
                    camera.name or camera.id, abs_path or rec.file_path, reason,
                )

                await db.delete(rec)
                deleted_count += 1

            await db.commit()

            freed_gb = freed_bytes / (1024 ** 3)
            logger.info(
                "Time retention for camera %s. deleted %d recordings, freed %.2f GB, "
                "queued %d for archive (cutoff %s)",
                camera.name or camera.id, deleted_count, freed_gb, archived_count,
                cutoff.isoformat(),
            )

    async def _enforce_size(self, camera: Camera, max_gb: float, archive=None):
        """Free oldest recordings until total size is under max_gb. With an
        archive set, the budget is local disk: archived recordings do not
        count, and the oldest local ones move to the archive instead of
        being deleted."""
        max_bytes = int(max_gb * 1024 ** 3)
        reason = f"retention_size: exceeded {max_gb:.1f} GB limit"

        local_only = []
        if archive is not None:
            local_only = [
                (Recording.remote_state.is_(None)) | (Recording.remote_state != "uploaded")
            ]

        async with async_session() as db:
            total_result = await db.execute(
                select(func.coalesce(func.sum(Recording.file_size_bytes), 0)).where(
                    Recording.camera_id == camera.id, *local_only
                )
            )
            total_bytes = total_result.scalar()

            if total_bytes <= max_bytes:
                return

            excess = total_bytes - max_bytes
            logger.info(
                "Size retention for camera %s. %.2f GB used, limit %.2f GB, need to free %.2f GB",
                camera.name or camera.id,
                total_bytes / (1024 ** 3),
                max_gb,
                excess / (1024 ** 3),
            )

            result = await db.execute(
                select(Recording)
                .where(Recording.camera_id == camera.id, *local_only)
                .order_by(Recording.started_at.asc())
            )
            recordings = list(result.scalars().all())

            deleted_count = 0
            freed_bytes = 0

            for rec in recordings:
                if freed_bytes >= excess:
                    break

                rec_size = rec.file_size_bytes or 0
                if archive_owns(rec, archive):
                    # Already queued: its bytes leave once the upload lands.
                    # A failed upload is the only copy, so it stays.
                    if rec.remote_state == "pending":
                        freed_bytes += rec_size
                    continue
                if archive is not None and rec.remote_state is None:
                    mark_for_archive(rec, archive)
                    freed_bytes += rec_size
                    continue
                abs_path = await _resolve_camera_path(rec.file_path, rec.camera_id)
                size, ok = _remove_file(abs_path)
                if not ok:
                    logger.warning("Skipping DB delete for recording %s, file still on disk", rec.id)
                    continue
                _remove_file(_resolve_path(rec.thumbnail_path))
                await _delete_remote_copy(rec)

                logger.info(
                    "Deleting recording for camera %s, file %s, reason %s",
                    camera.name or camera.id, abs_path or rec.file_path, reason,
                )

                await db.delete(rec)
                freed_bytes += size or rec_size
                deleted_count += 1

            await db.commit()

            logger.info(
                "Size retention for camera %s. deleted %d recordings, freed %.2f GB",
                camera.name or camera.id, deleted_count, freed_bytes / (1024 ** 3),
            )
