"""Tests for per-camera storage roots (issue #251, shared/storage_paths.py)."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shared import storage_paths


@pytest.fixture(autouse=True)
def _reset_state():
    storage_paths._applied = None
    storage_paths._last_check = 0.0
    storage_paths._profile_roots.clear()
    storage_paths._profile_roots_at = 0.0
    yield
    storage_paths._applied = None
    storage_paths._last_check = 0.0
    storage_paths._profile_roots.clear()
    storage_paths._profile_roots_at = 0.0


def patch_settings_reads(value=None):
    async def fake_get(key, default=None):
        return value

    return patch.object(storage_paths, "get_setting", fake_get)


def fake_db(rows):
    """async_session stand-in whose execute() returns rows (tuples)."""

    class Result:
        def all(self):
            return rows

    async def execute(*a, **k):
        return Result()

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(execute=execute)

    return factory


CID = uuid.uuid4()


@pytest.mark.asyncio
async def test_camera_without_profile_uses_global_root():
    with patch_settings_reads(None), \
         patch("shared.database.async_session", new=fake_db([])):
        root = await storage_paths.recordings_root_for(CID)
    assert root == storage_paths.settings.recordings_path


@pytest.mark.asyncio
async def test_camera_with_profile_resolves_profile_root():
    profile_root = "/mnt/second-drive/nurby"
    with patch_settings_reads(None), \
         patch("shared.database.async_session", new=fake_db([(str(CID), profile_root)])):
        root = await storage_paths.recordings_root_for(CID)
    assert root == profile_root


@pytest.mark.asyncio
async def test_unknown_camera_and_none_fall_back_to_global():
    with patch_settings_reads(None), \
         patch("shared.database.async_session", new=fake_db([(str(CID), "/x")])):
        assert await storage_paths.recordings_root_for(None) == storage_paths.settings.recordings_path
        assert await storage_paths.recordings_root_for(uuid.uuid4()) == storage_paths.settings.recordings_path


@pytest.mark.asyncio
async def test_profile_cache_hit_does_not_requery():
    query_count = {"n": 0}

    def fake_db_counted(rows):
        class Result:
            def all(self):
                return rows

        async def execute(*a, **k):
            query_count["n"] += 1
            return Result()

        @asynccontextmanager
        async def factory():
            db = SimpleNamespace(execute=execute)
            yield db

        return factory

    with patch_settings_reads(None), \
         patch("shared.database.async_session", new=fake_db_counted([(str(CID), "/x")])):
        await storage_paths.recordings_root_for(CID)
        await storage_paths.recordings_root_for(CID)  # cache hit
        assert query_count["n"] == 1
        # Invalidate forces a re-read.
        storage_paths.invalidate()
        await storage_paths.recordings_root_for(CID)
    assert query_count["n"] == 2


@pytest.mark.asyncio
async def test_worker_segment_path_honors_camera_root(tmp_path):
    """The StreamWorker writes segments under the root it resolved at
    start (its profile), not the global one."""
    from services.ingestion.stream import StreamWorker

    worker = StreamWorker(
        camera_id=CID, stream_url="rtsp://x", recording_enabled=True,
    )
    worker._recordings_root = str(tmp_path)
    path = worker._segment_path(datetime(2026, 9, 23, 10, 30, 0, tzinfo=timezone.utc))
    assert str(tmp_path) in path
    assert str(CID) in path
    # Pre-roll staging stays inside the same root.
    assert worker._preroll_dir().startswith(str(tmp_path))
