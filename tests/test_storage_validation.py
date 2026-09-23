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
