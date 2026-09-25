"""Opt-in scheduled backup runner for the API process.

Scheduling is disabled unless both ``NURBY_BACKUP_SCHEDULE_HOURS`` and
``NURBY_BACKUP_PASSPHRASE`` are configured.  The passphrase is deployment
secret material, never a database setting or API response.  A scheduler is
useful for the normal single-API self-host deployment; operators running
multiple API replicas should keep the CLI/systemd timer instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from shared.config import settings

logger = logging.getLogger("nurby.backup-scheduler")


class BackupScheduler:
    def __init__(self, *, poll_seconds: float = 60.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(settings.backup_passphrase and settings.backup_schedule_hours > 0)

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.enabled:
            logger.info(
                "Scheduled backups disabled; configure NURBY_BACKUP_SCHEDULE_HOURS "
                "and NURBY_BACKUP_PASSPHRASE to enable them"
            )
            return
        logger.info(
            "Scheduled backups enabled every %.2f hours (retaining %d archives)",
            settings.backup_schedule_hours,
            settings.backup_retention_count,
        )
        # Check immediately so a newly deployed instance does not wait for a
        # full interval before establishing a recoverable baseline.
        await self.run_once(force=False)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                await self.run_once(force=False)

    async def run_once(self, *, force: bool = False) -> Path | None:
        if not self.enabled:
            return None
        from services.backup import backup_status, create_backup

        if not force and not self._due(backup_status().get("last_success_at")):
            return None
        try:
            archive = await asyncio.to_thread(
                create_backup,
                settings.backup_passphrase,
                include_recordings=settings.backup_include_recordings,
            )
            self._prune(Path(settings.backup_path), settings.backup_retention_count)
            logger.info("Scheduled backup completed: %s", archive.name)
            return archive
        except Exception:
            # A failed scheduled backup must not stop the API or erase the
            # previous known-good archive; Doctor will report it as stale.
            logger.exception("Scheduled backup failed")
            return None

    @staticmethod
    def _due(last_success_at: str | None) -> bool:
        if not last_success_at:
            return True
        try:
            from datetime import datetime

            last = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
            return (time.time() - last.timestamp()) >= settings.backup_schedule_hours * 3600
        except (TypeError, ValueError, OverflowError):
            return True

    @staticmethod
    def _prune(directory: Path, keep: int) -> None:
        if keep < 1:
            return
        archives = sorted(
            (p for p in directory.glob("nurby-*.nurby") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in archives[keep:]:
            try:
                old.unlink()
            except OSError:
                logger.warning("Could not prune old backup %s", old)
