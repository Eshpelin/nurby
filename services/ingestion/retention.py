"""
Recording retention cleanup.

Periodically checks each camera's retention policy and deletes
old recordings that exceed time or size limits.
"""

import asyncio
import logging
import os
import uuid

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import async_session
from shared.models import Camera, Recording

logger = logging.getLogger("nurby.ingestion.retention")

CLEANUP_INTERVAL = 3600  # run every hour


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
                    await self._enforce_time(cam.id, cam.retention_days)
                elif cam.retention_mode == "size":
                    await self._enforce_size(cam.id, cam.retention_gb)
            except Exception:
                logger.exception("Retention cleanup failed for camera %s", cam.id)

    async def _enforce_time(self, camera_id: uuid.UUID, retention_days: int):
        """Delete recordings older than retention_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        async with async_session() as db:
            result = await db.execute(
                select(Recording).where(
                    and_(
                        Recording.camera_id == camera_id,
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
                # Delete file from disk
                if rec.file_path and os.path.exists(rec.file_path):
                    try:
                        size = os.path.getsize(rec.file_path)
                        os.remove(rec.file_path)
                        freed_bytes += size
                    except OSError:
                        logger.warning("Could not delete file %s", rec.file_path)

                await db.delete(rec)
                deleted_count += 1

            await db.commit()

            freed_gb = freed_bytes / (1024 ** 3)
            logger.info(
                "Time retention for camera %s. deleted %d recordings, freed %.2f GB (cutoff %s)",
                camera_id, deleted_count, freed_gb, cutoff.isoformat(),
            )

    async def _enforce_size(self, camera_id: uuid.UUID, max_gb: float):
        """Delete oldest recordings until total size is under max_gb."""
        max_bytes = int(max_gb * 1024 ** 3)

        async with async_session() as db:
            # Get total size
            total_result = await db.execute(
                select(func.coalesce(func.sum(Recording.file_size_bytes), 0)).where(
                    Recording.camera_id == camera_id
                )
            )
            total_bytes = total_result.scalar()

            if total_bytes <= max_bytes:
                return

            excess = total_bytes - max_bytes
            logger.info(
                "Size retention for camera %s. %.2f GB used, limit %.2f GB, need to free %.2f GB",
                camera_id,
                total_bytes / (1024 ** 3),
                max_gb,
                excess / (1024 ** 3),
            )

            # Get oldest recordings first
            result = await db.execute(
                select(Recording)
                .where(Recording.camera_id == camera_id)
                .order_by(Recording.started_at.asc())
            )
            recordings = list(result.scalars().all())

            deleted_count = 0
            freed_bytes = 0

            for rec in recordings:
                if freed_bytes >= excess:
                    break

                rec_size = rec.file_size_bytes or 0

                if rec.file_path and os.path.exists(rec.file_path):
                    try:
                        os.remove(rec.file_path)
                    except OSError:
                        logger.warning("Could not delete file %s", rec.file_path)

                await db.delete(rec)
                freed_bytes += rec_size
                deleted_count += 1

            await db.commit()

            logger.info(
                "Size retention for camera %s. deleted %d recordings, freed %.2f GB",
                camera_id, deleted_count, freed_bytes / (1024 ** 3),
            )
