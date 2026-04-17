"""
Recording retention cleanup.

Periodically checks each camera's retention policy and deletes
old recordings that exceed time or size limits.
"""

import asyncio
import logging
import os

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_

from shared.config import settings
from shared.database import async_session
from shared.models import Camera, Recording

logger = logging.getLogger("nurby.ingestion.retention")

CLEANUP_INTERVAL = 3600  # run every hour

_RELATIVE_PREFIXES = ["./recordings/", "recordings/", "./"]


def _resolve_path(file_path: str | None) -> str | None:
    """Turn a stored (possibly relative) file path into an absolute disk path."""
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
            result = await db.execute(
                select(Camera).where(Camera.retention_mode != "none")
            )
            cameras = list(result.scalars().all())

        if not cameras:
            return

        logger.info("Running retention cleanup for %d cameras", len(cameras))

        for cam in cameras:
            try:
                if cam.retention_mode == "time":
                    await self._enforce_time(cam, cam.retention_days)
                elif cam.retention_mode == "size":
                    await self._enforce_size(cam, cam.retention_gb)
            except Exception:
                logger.exception("Retention cleanup failed for camera %s", cam.id)

    async def _enforce_time(self, camera: Camera, retention_days: int):
        """Delete recordings older than retention_days."""
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
            freed_bytes = 0

            for rec in old_recordings:
                abs_path = _resolve_path(rec.file_path)
                size, ok = _remove_file(abs_path)
                if not ok:
                    logger.warning("Skipping DB delete for recording %s, file still on disk", rec.id)
                    continue
                freed_bytes += size
                _remove_file(_resolve_path(rec.thumbnail_path))

                logger.info(
                    "Deleting recording for camera %s, file %s, reason %s",
                    camera.name or camera.id, abs_path or rec.file_path, reason,
                )

                await db.delete(rec)
                deleted_count += 1

            await db.commit()

            freed_gb = freed_bytes / (1024 ** 3)
            logger.info(
                "Time retention for camera %s. deleted %d recordings, freed %.2f GB (cutoff %s)",
                camera.name or camera.id, deleted_count, freed_gb, cutoff.isoformat(),
            )

    async def _enforce_size(self, camera: Camera, max_gb: float):
        """Delete oldest recordings until total size is under max_gb."""
        max_bytes = int(max_gb * 1024 ** 3)
        reason = f"retention_size: exceeded {max_gb:.1f} GB limit"

        async with async_session() as db:
            total_result = await db.execute(
                select(func.coalesce(func.sum(Recording.file_size_bytes), 0)).where(
                    Recording.camera_id == camera.id
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
                .where(Recording.camera_id == camera.id)
                .order_by(Recording.started_at.asc())
            )
            recordings = list(result.scalars().all())

            deleted_count = 0
            freed_bytes = 0

            for rec in recordings:
                if freed_bytes >= excess:
                    break

                rec_size = rec.file_size_bytes or 0
                abs_path = _resolve_path(rec.file_path)
                size, ok = _remove_file(abs_path)
                if not ok:
                    logger.warning("Skipping DB delete for recording %s, file still on disk", rec.id)
                    continue
                _remove_file(_resolve_path(rec.thumbnail_path))

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
