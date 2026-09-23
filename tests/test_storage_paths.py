"""Tests for the runtime storage-location resolver (shared/storage_paths.py)."""

import pytest

from shared import storage_paths
from shared.config import settings


@pytest.fixture(autouse=True)
def _restore_singleton():
    """Tests mutate the process-wide recordings root; always restore it."""
    original = settings.recordings_path
    storage_paths._applied = None
    storage_paths._last_check = 0.0
    yield
    settings.recordings_path = original
    storage_paths._applied = None
    storage_paths._last_check = 0.0


def settings_stub(value):
    calls = {"n": 0}

    async def fake_get(key, default=None):
        calls["n"] += 1
        return value

    return fake_get, calls


@pytest.mark.asyncio
async def test_no_override_keeps_env_default():
    fake_get, calls = settings_stub(None)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(storage_paths, "get_setting", fake_get)
        await storage_paths.apply_storage_overrides(force=True)
    assert calls["n"] == 1
    assert settings.recordings_path == storage_paths.ENV_DEFAULT


@pytest.mark.asyncio
async def test_override_moves_recordings_root():
    fake_get, _ = settings_stub("/srv/nurby/recordings")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(storage_paths, "get_setting", fake_get)
        await storage_paths.apply_storage_overrides(force=True)
    assert settings.recordings_path == "/srv/nurby/recordings"


@pytest.mark.asyncio
async def test_reverting_to_none_restores_captured_env_default():
    """None must restore the env default even after the singleton was
    mutated — the env value is captured at import for exactly this."""
    settings.recordings_path = "/already/mutated"
    fake_get, _ = settings_stub(None)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(storage_paths, "get_setting", fake_get)
        await storage_paths.apply_storage_overrides(force=True)
    assert settings.recordings_path == storage_paths.ENV_DEFAULT


@pytest.mark.asyncio
async def test_throttle_skips_reads_until_forced_or_invalidated():
    fake_get, calls = settings_stub(None)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(storage_paths, "get_setting", fake_get)
        await storage_paths.apply_storage_overrides(force=True)
        assert calls["n"] == 1
        # Inside the throttle window: no re-read.
        await storage_paths.apply_storage_overrides()
        assert calls["n"] == 1
        # invalidate() (settings PATCH) forces the next read.
        storage_paths.invalidate()
        await storage_paths.apply_storage_overrides()
        assert calls["n"] == 2


@pytest.mark.asyncio
async def test_failed_settings_read_never_raises():
    async def boom(key, default=None):
        raise RuntimeError("db down")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(storage_paths, "get_setting", boom)
        await storage_paths.apply_storage_overrides(force=True)
    assert settings.recordings_path == storage_paths.ENV_DEFAULT


def test_docker_detection_returns_bool():
    assert isinstance(storage_paths.in_docker(), bool)


def test_settings_whitelisted_and_schema_facing():
    """The key must be PATCHable through the settings surface."""
    from services.api.routes.system import SETTINGS_WHITELIST
    from shared.schemas import SystemSettingsResponse, SystemSettingsUpdate

    assert "storage_recordings_dir" in SETTINGS_WHITELIST
    assert "storage_recordings_dir" in SystemSettingsResponse.model_fields
    assert "storage_recordings_dir" in SystemSettingsUpdate.model_fields
