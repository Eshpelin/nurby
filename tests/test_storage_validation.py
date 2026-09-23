"""Tests for the storage-location validation endpoint logic (issue #251).

Calls the route helpers directly — no broker, no DB."""

import pytest

from services.api.routes.system import validate_storage_dir


def test_relative_path_rejected():
    out = validate_storage_dir("recordings/elsewhere")
    assert out.ok is False
    assert "absolute" in out.detail.lower()


def test_empty_path_rejected():
    out = validate_storage_dir("   ")
    assert out.ok is False


def test_valid_new_directory_is_created_and_reported(tmp_path):
    target = tmp_path / "recordings"
    out = validate_storage_dir(str(target))
    assert out.ok is True
    assert out.created is True and out.exists is True
    assert out.writable is True
    assert out.free_bytes is not None and out.free_bytes > 0
    assert target.is_dir()


def test_existing_directory_not_reported_as_created(tmp_path):
    target = tmp_path / "already"
    target.mkdir()
    out = validate_storage_dir(str(target))
    assert out.ok is True
    assert out.created is False


def test_quotes_are_stripped_from_pasted_paths(tmp_path):
    target = tmp_path / "quoted"
    out = validate_storage_dir(f'"{target}"')
    assert out.ok is True
    assert out.path == str(target)


def test_unwritable_directory_rejected(tmp_path):
    d = tmp_path / "readonly"
    d.mkdir()
    d.chmod(0o500)
    try:
        out = validate_storage_dir(str(d))
    finally:
        d.chmod(0o700)  # let pytest clean up
    assert out.ok is False
    assert "not writable" in out.detail.lower()


def test_windows_drive_path_inside_docker_rejected(monkeypatch):
    from shared import storage_paths

    monkeypatch.setattr(storage_paths, "in_docker", lambda: True)
    out = validate_storage_dir("D:\\Nurby\\recordings")
    assert out.ok is False
    assert "Docker" in out.detail or "NURBY_RECORDINGS_VOLUME" in out.detail


def test_windows_drive_path_is_absolute_when_native(monkeypatch):
    """Not inside Docker the drive path is treated as absolute and probed
    (creating a literal folder here is fine for the test's tmp cwd)."""
    from shared import storage_paths

    monkeypatch.setattr(storage_paths, "in_docker", lambda: False)
    out = validate_storage_dir("Q:\\Nurby\\recordings")
    assert out.ok is True


# ── Low-disk capacity warning (issue #266) ───────────────────────────


def test_validate_warns_when_free_space_is_low(tmp_path, monkeypatch):
    import services.api.routes.system as sysmod

    target = tmp_path / "low"
    target.mkdir()

    class Usage:
        free = 2 * 1024**3  # 2 GB — below the 10 GB threshold
        total = 500 * 1024**3

    monkeypatch.setattr(sysmod.shutil, "disk_usage", lambda p: Usage())
    out = sysmod.validate_storage_dir(str(target))
    assert out.ok is True
    assert "Warning" in out.detail and "2.0 GB free" in out.detail


def test_validate_no_warning_with_ample_space(tmp_path, monkeypatch):
    import services.api.routes.system as sysmod

    target = tmp_path / "ample"
    target.mkdir()

    class Usage:
        free = 200 * 1024**3
        total = 500 * 1024**3

    monkeypatch.setattr(sysmod.shutil, "disk_usage", lambda p: Usage())
    out = sysmod.validate_storage_dir(str(target))
    assert out.ok is True
    assert "Warning" not in out.detail


def test_low_disk_threshold_is_ten_gb():
    import services.api.routes.system as sysmod

    assert sysmod.LOW_DISK_FREE_BYTES == 10 * 1024**3


# ── Non-admin access is rejected server-side (issue #266) ────────────


def _fake_user(role: str):
    from types import SimpleNamespace

    return SimpleNamespace(id="u", role=role, is_active=True)


def test_storage_endpoints_require_admin():
    """require_admin is the FastAPI dependency for every storage surface;
    exercised directly to pin the contract (mirrors the settings test)."""
    import asyncio

    import pytest as _pytest
    from shared.auth import require_admin

    for role in ("viewer", "user"):
        with _pytest.raises(Exception) as exc:
            asyncio.run(require_admin(current_user=_fake_user(role)))
        assert getattr(exc.value, "status_code", None) == 403


# ── Storage overview endpoint (issue #266) ───────────────────────────


def test_storage_overview_reports_three_roots_and_warnings(tmp_path, monkeypatch):
    import asyncio

    from shared import storage_paths
    from shared.config import settings

    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / ".nurby_write_test").touch()  # writable root

    async def fake_get(key, default=None):
        return "/custom/recordings"  # configured (custom) override

    monkeypatch.setattr("shared.app_settings.get_setting", fake_get)
    monkeypatch.setattr(settings, "recordings_path", str(recordings))
    monkeypatch.setattr(settings, "thumbnails_path", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path / "audio"))

    from services.api.routes.system import storage_location_status

    out = asyncio.run(storage_location_status(_current_user=None))
    keys = [loc.key for loc in out.locations]
    assert keys == ["recordings", "thumbnails", "audio"]
    rec = out.locations[0]
    assert rec.path == str(recordings) and rec.source == "custom"
    assert rec.writable is True and rec.exists is True
    # thumbnails/audio dirs don't exist -> surfaced as warnings, not crashes
    assert out.warnings and "does not exist" in out.warnings[-1]
    assert storage_paths.in_docker() in (True, False)
