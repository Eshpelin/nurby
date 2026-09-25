"""Remote upload worker: FTP (issue #269) and S3 (issue #270).

Drains the buffer-then-upload outbox. Recordings are marked ``pending``
either at finalize time, when their camera records to a remote profile
(stream.py), or by retention, when they age out of the local window and
an archive destination is set (shared/archive.py). This
worker transfers them (oldest first), verifies the upload, then deletes
the local copy when the profile says so. A failed or unreachable FTP
server never loses footage — the local file is only removed after a
size-verified upload, and attempts are capped at a terminal ``failed``
state that the storage overview surfaces.

Also sweeps the on-demand playback cache (recordings fetched back from
FTP are cached under <recordings root>/.remote_cache and evicted LRU by
mtime when the cache exceeds its cap).
"""

import asyncio
import logging
import os

from sqlalchemy import select

from shared.database import async_session
from shared.models import Recording, StorageProfile
from shared.remote_storage import (
    kind_label,
    parse_remote_config,
    remote_download,
    remote_path_for,
    remote_upload,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30.0
BATCH_SIZE = 10
ATTEMPT_CAP = 20
# Playback cache cap. Fixed for v1 — keep the knob count low until real
# installs tell us whether people need to tune it.
REMOTE_CACHE_MAX_BYTES = 20 * 1024**3
CACHE_SWEEP_EVERY = 20  # loops (~10 min at the 30s poll)


def local_cache_path(rel_file_path: str | None) -> str:
    """Where a remote recording is cached locally after on-demand download."""
    from shared.config import settings

    rel = (rel_file_path or "").replace("\\", "/")
    for prefix in ("./recordings/", "recordings/", "./"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(settings.recordings_path, ".remote_cache", rel.lstrip("/"))


class RemoteUploadWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._loops = 0

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.process_batch()
            except Exception:
                logger.exception("remote upload batch failed")
            self._loops += 1
            if self._loops % CACHE_SWEEP_EVERY == 0:
                try:
                    await self.sweep_cache()
                except Exception:
                    logger.debug("remote cache sweep failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def process_batch(self) -> None:
        async with async_session() as db:
            rows = await db.execute(
                select(Recording)
                .where(
                    Recording.remote_state.in_(["pending", "failed"])
                    & (Recording.remote_attempts < ATTEMPT_CAP)
                )
                .order_by(Recording.started_at)
                .limit(BATCH_SIZE)
            )
            recordings = list(rows.scalars().all())
            for rec in recordings:
                await self._process_one(db, rec)
            await db.commit()

    async def _process_one(self, db, rec: Recording) -> None:
        profile = (
            await db.get(StorageProfile, rec.remote_profile_id)
            if rec.remote_profile_id
            else None
        )
        cfg = parse_remote_config(profile.kind, profile.config_enc) if profile else None
        if profile is None or cfg is None:
            # Nothing to upload to. The local copy is the only copy, so keep
            # it and stop retrying.
            rec.remote_state = "failed"
            rec.remote_error = (
                "storage profile removed"
                if profile is None
                else "saved credentials could not be read (was the server secret key changed?). "
                "Re-enter them on the storage location"
            )
            return

        from services.ingestion.retention import _resolve_camera_path

        local_path = await _resolve_camera_path(rec.file_path, rec.camera_id)
        if not local_path or not os.path.exists(local_path):
            # Already gone (retention raced us) — nothing to transfer.
            rec.remote_state = "failed"
            rec.remote_error = "local buffer file missing"
            return

        remote_path = rec.remote_path or remote_path_for(profile.root, rec.file_path)
        ok, detail = await remote_upload(profile.kind, cfg, profile.root, local_path, remote_path)
        if ok:
            rec.remote_state = "uploaded"
            rec.remote_path = remote_path
            rec.remote_error = None
            # An archive move exists to free local disk, so it always drops
            # the local copy once the upload is verified.
            if cfg.delete_after_upload or await self._is_archive(profile.id):
                try:
                    os.remove(local_path)
                except OSError:
                    logger.warning(
                        "Could not remove local buffer copy %s after upload", local_path
                    )
            logger.info(
                "Uploaded recording %s to %s (%s)", rec.id, remote_path, profile.name
            )
        else:
            rec.remote_attempts = (rec.remote_attempts or 0) + 1
            rec.remote_error = (detail or "upload failed")[:500]
            if rec.remote_attempts >= ATTEMPT_CAP:
                rec.remote_state = "failed"
                logger.error(
                    "Recording %s failed %s upload after %d attempts: %s",
                    rec.id, kind_label(profile.kind), rec.remote_attempts, rec.remote_error,
                )
            else:
                rec.remote_state = "pending"
                logger.warning(
                    "%s upload attempt %d for recording %s failed: %s",
                    kind_label(profile.kind), rec.remote_attempts, rec.id, detail,
                )

    async def _is_archive(self, profile_id) -> bool:
        from shared.archive import archive_target

        target = await archive_target()
        return target is not None and target.profile_id == profile_id

    # ── playback cache ───────────────────────────────────────────────
    async def sweep_cache(self) -> None:
        """Evict least-recently-used cache entries over the cap."""
        from shared.config import settings

        cache_root = os.path.join(settings.recordings_path, ".remote_cache")
        entries: list[tuple[float, str, int]] = []
        total = 0
        for dirpath, _dirnames, filenames in os.walk(cache_root):
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                entries.append((st.st_mtime, path, st.st_size))
                total += st.st_size
        if total <= REMOTE_CACHE_MAX_BYTES:
            return
        entries.sort()  # oldest mtime first
        removed = 0
        for _mtime, path, size in entries:
            if total <= REMOTE_CACHE_MAX_BYTES:
                break
            try:
                os.remove(path)
                total -= size
                removed += size
            except OSError:
                continue
        if removed:
            logger.info("Evicted %.1f GB from the remote playback cache", removed / 1024**3)


_worker: RemoteUploadWorker | None = None


def get_worker() -> RemoteUploadWorker:
    global _worker
    if _worker is None:
        _worker = RemoteUploadWorker()
    return _worker


async def fetch_to_cache(recording: Recording) -> str | None:
    """Playback fallback (issues #269, #270): download a remotely stored
    recording into the local cache and return the cache path. Returns the
    existing cache entry when present. None when the recording is not
    remote, the profile is gone, or the download fails, so callers keep
    their local-only error paths. Raises ``RestorePendingError`` when the object
    is in an S3 archive class and a restore has been requested."""
    if (
        getattr(recording, "remote_state", None) != "uploaded"
        or not getattr(recording, "remote_profile_id", None)
    ):
        return None
    async with async_session() as db:
        profile = await db.get(StorageProfile, recording.remote_profile_id)
    cfg = parse_remote_config(profile.kind, profile.config_enc) if profile else None
    if profile is None or cfg is None:
        return None
    cache_path = local_cache_path(recording.file_path)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path
    remote_path = recording.remote_path or remote_path_for(
        profile.root, recording.file_path
    )
    ok, detail = await remote_download(profile.kind, cfg, remote_path, cache_path)
    if not ok:
        logger.warning(
            "%s playback download failed for %s: %s", kind_label(profile.kind), recording.id, detail
        )
        return None
    return cache_path
