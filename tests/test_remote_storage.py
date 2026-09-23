"""Tests for the native FTP storage backend (issue #269)."""

import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from shared.remote_storage import (
    ftp_target_for,
    parse_ftp_config,
    remote_path_for,
    seal_ftp_config,
)


# ── config sealing ───────────────────────────────────────────────────


def test_seal_and_parse_round_trip_hides_password():
    enc = seal_ftp_config(
        {"host": "nas.local", "port": 2121, "username": "cam", "password": "hunter2"}
    )
    assert "hunter2" not in enc and "nas.local" not in enc
    cfg = parse_ftp_config(enc)
    assert cfg is not None
    assert (cfg.host, cfg.port, cfg.username, cfg.password) == ("nas.local", 2121, "cam", "hunter2")
    assert cfg.passive is True and cfg.tls is False and cfg.delete_after_upload is True
    # Public view strips the credential entirely.
    assert "password" not in cfg.public_dict()


def test_seal_requires_host_and_numeric_port():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        seal_ftp_config({"host": ""})
    with _pytest.raises(ValueError):
        seal_ftp_config({"host": "x", "port": "not-a-number"})
    with _pytest.raises(ValueError):
        seal_ftp_config({"host": "x", "port": 0})


def test_parse_tolerant_of_missing_or_undecryptable_config():
    assert parse_ftp_config(None) is None
    assert parse_ftp_config("") is None
    # A sealed blob that no longer decrypts degrades to "no config".
    assert parse_ftp_config("gAAAA-not-really-a-token") is None


def test_remote_path_strips_storage_prefixes():
    assert remote_path_for("/nurby", "./recordings/abc/2026-01-01/f.mp4") == "/nurby/abc/2026-01-01/f.mp4"
    assert remote_path_for("/nurby", "recordings/abc/f.mp4") == "/nurby/abc/f.mp4"
    assert remote_path_for("/", "abc/f.mp4") == "/abc/f.mp4"


# ── ftp-target resolution ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_ftp_cache():
    import shared.remote_storage as rs

    rs._ftp_targets.clear()
    rs._ftp_targets_at = 0.0
    yield
    rs._ftp_targets.clear()
    rs._ftp_targets_at = 0.0


@pytest.mark.asyncio
async def test_ftp_target_for_returns_none_without_profiles():
    async def execute(*a, **k):
        class R:
            def all(self):
                return []

        return R()

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(execute=execute)

    with patch("shared.database.async_session", new=factory):
        assert await ftp_target_for(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_profile_root_filter_excludes_ftp_kinds():
    """Only kind='local' profiles resolve as LOCAL roots — an FTP camera
    must keep buffering to the global root, not to a remote path."""
    from shared import storage_paths

    # The profile roots are cached per process with a throttle, so an earlier
    # test that warmed the cache would make this one skip the query it asserts
    # on. Force a fresh load.
    storage_paths.invalidate()

    captured = {}

    class Result:
        def all(self):
            return []

    async def execute(stmt, *a, **k):
        captured["sql"] = str(stmt)
        try:
            captured["params"] = stmt.compile().params
        except Exception:
            captured["params"] = {}
        return Result()

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(execute=execute)

    with patch("shared.database.async_session", new=factory):
        await storage_paths._load_profile_roots()
    assert "kind" in captured["sql"]
    assert "local" in str(captured.get("params", {}))


# ── upload worker state transitions ──────────────────────────────────


def _recording(**over):
    rec = SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        file_path="abc/2026-01-01/f.mp4",
        remote_state="pending",
        remote_path=None,
        remote_profile_id=uuid.uuid4(),
        remote_attempts=0,
        remote_error=None,
    )
    for k, v in over.items():
        setattr(rec, k, v)
    return rec


def _profile(config_enc=None, root="/nurby"):
    if config_enc is None:
        config_enc = seal_ftp_config({"host": "nas.local", "username": "cam", "password": "pw"})
    return SimpleNamespace(id=uuid.uuid4(), name="NAS", kind="ftp", root=root, config_enc=config_enc)


def _fake_db(profile):
    return SimpleNamespace(get=AsyncMock(return_value=profile), commit=AsyncMock())


def _fake_db_session(profile):
    """Factory-style: for code that opens its own async_session()."""

    @asynccontextmanager
    async def factory():
        yield _fake_db(profile)

    return factory


@pytest.mark.asyncio
async def test_successful_upload_marks_uploaded_and_removes_buffer(tmp_path):
    from services.ingestion import remote_upload as ru

    local = tmp_path / "f.mp4"
    local.write_bytes(b"x" * 10)
    rec = _recording()

    with patch("services.ingestion.retention._resolve_camera_path", new=AsyncMock(return_value=str(local))), \
         patch("os.path.exists", return_value=True), \
         patch.object(ru, "ftp_upload", new=AsyncMock(return_value=(True, "uploaded"))), \
         patch("os.remove") as remove:
        await ru.RemoteUploadWorker()._process_one(_fake_db(_profile()), rec)

    assert rec.remote_state == "uploaded"
    assert rec.remote_error is None
    assert rec.remote_path == f"/nurby/{rec.file_path}"
    remove.assert_called_once_with(str(local))


@pytest.mark.asyncio
async def test_failed_upload_increments_attempts_and_keeps_buffer(tmp_path):
    from services.ingestion import remote_upload as ru

    local = tmp_path / "f.mp4"
    local.write_bytes(b"x")
    rec = _recording()

    with patch("services.ingestion.retention._resolve_camera_path", new=AsyncMock(return_value=str(local))), \
         patch("os.path.exists", return_value=True), \
         patch.object(ru, "ftp_upload", new=AsyncMock(return_value=(False, "550 failed"))), \
         patch("os.remove") as remove:
        await ru.RemoteUploadWorker()._process_one(_fake_db(_profile()), rec)

    assert rec.remote_state == "pending"  # still retrying under the cap
    assert rec.remote_attempts == 1
    assert "550" in (rec.remote_error or "")
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_attempts_cap_terminals_the_recording(tmp_path):
    from services.ingestion import remote_upload as ru

    local = tmp_path / "f.mp4"
    local.write_bytes(b"x")
    rec = _recording(remote_attempts=ru.ATTEMPT_CAP - 1)

    with patch("services.ingestion.retention._resolve_camera_path", new=AsyncMock(return_value=str(local))), \
         patch("os.path.exists", return_value=True), \
         patch.object(ru, "ftp_upload", new=AsyncMock(return_value=(False, "down"))), \
         patch("os.remove") as remove:
        await ru.RemoteUploadWorker()._process_one(_fake_db(_profile()), rec)

    assert rec.remote_state == "failed"
    assert rec.remote_attempts == ru.ATTEMPT_CAP
    # The terminal failure keeps the local copy: the buffer is the only copy.
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_missing_profile_terminals_the_recording():
    from services.ingestion import remote_upload as ru

    rec = _recording()
    await ru.RemoteUploadWorker()._process_one(_fake_db(None), rec)
    assert rec.remote_state == "failed"
    assert "profile removed" in (rec.remote_error or "")


# ── playback fallback ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_to_cache_returns_none_for_local_only_recordings():
    from services.ingestion import remote_upload as ru

    rec = _recording(remote_state=None)
    assert await ru.fetch_to_cache(rec) is None


@pytest.mark.asyncio
async def test_fetch_to_cache_uses_existing_entry_without_downloading(tmp_path, monkeypatch):
    from services.ingestion import remote_upload as ru
    from shared.config import settings

    cache_file = tmp_path / ".remote_cache" / "abc" / "f.mp4"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cached")
    monkeypatch.setattr(settings, "recordings_path", str(tmp_path))

    rec = _recording(remote_state="uploaded", file_path="abc/f.mp4")
    with patch("services.ingestion.remote_upload.async_session", new=_fake_db_session(_profile())):
        out = await ru.fetch_to_cache(rec)
    assert out == str(cache_file)


@pytest.mark.asyncio
async def test_fetch_to_cache_downloads_when_cold(tmp_path, monkeypatch):
    from services.ingestion import remote_upload as ru
    from shared.config import settings

    monkeypatch.setattr(settings, "recordings_path", str(tmp_path))
    rec = _recording(
        remote_state="uploaded", file_path="abc/f.mp4", remote_path="/nurby/abc/f.mp4"
    )

    async def fake_download(cfg, remote, local):
        os.makedirs(os.path.dirname(local), exist_ok=True)  # matches _download_sync
        with open(local, "wb") as f:
            f.write(b"from-ftp")
        return True, "downloaded"

    with patch("services.ingestion.remote_upload.async_session", new=_fake_db_session(_profile())), \
         patch.object(ru, "ftp_download", new=fake_download):
        out = await ru.fetch_to_cache(rec)
    assert out and out.endswith(os.path.join(".remote_cache", "abc", "f.mp4"))
    assert open(out, "rb").read() == b"from-ftp"


# ── response masking ─────────────────────────────────────────────────


def test_profile_serializer_masks_password():
    from datetime import datetime, timezone

    from services.api.routes.storage_profiles import _serialize

    enc = seal_ftp_config({"host": "nas.local", "password": "hunter2"})
    profile = SimpleNamespace(
        id=uuid.uuid4(), name="NAS", kind="ftp", root="/nurby",
        enabled=True, config_enc=enc,
        created_at=datetime.now(timezone.utc),
    )
    out = _serialize(profile).model_dump()
    assert "hunter2" not in str(out)
    assert out["has_password"] is True
    assert out["config"]["host"] == "nas.local"
