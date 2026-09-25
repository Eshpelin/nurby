"""S3 storage backend and the age-based archive tier (issue #270).

No network: boto3 clients are replaced with fakes, and retention runs
against an in-memory session.
"""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import shared.remote_storage as rs
from shared.archive import ArchiveTarget


def _s3_cfg(**over):
    base = {
        "bucket": "cams",
        "access_key_id": "AKIA123",
        "secret_access_key": "s3cret",
        "region": "eu-west-1",
        "storage_class": "GLACIER_IR",
    }
    base.update(over)
    return base


# ── S3 config ────────────────────────────────────────────────────────


def test_s3_config_round_trip_hides_secret():
    enc = rs.seal_s3_config(_s3_cfg())
    assert "s3cret" not in enc and "AKIA123" not in enc
    cfg = rs.parse_s3_config(enc)
    assert (cfg.bucket, cfg.region, cfg.storage_class) == ("cams", "eu-west-1", "GLACIER_IR")
    assert cfg.secret_access_key == "s3cret"
    assert "secret_access_key" not in cfg.public_dict()
    assert cfg.needs_restore is False
    assert rs.parse_s3_config(rs.seal_s3_config(_s3_cfg(storage_class="deep_archive"))).needs_restore


@pytest.mark.parametrize(
    "over, message",
    [
        ({"bucket": ""}, "bucket is required"),
        ({"bucket": "cams/old"}, "not a path"),
        ({"secret_access_key": ""}, "required"),
        ({"endpoint_url": "minio.local:9000"}, "https://"),
        ({"storage_class": "ICE"}, "storage class"),
    ],
)
def test_s3_config_validation(over, message):
    with pytest.raises(ValueError, match=message):
        rs.seal_s3_config(_s3_cfg(**over))


def test_s3_keys_and_roots():
    from services.api.routes.storage_profiles import _normalize_remote_root

    assert rs.s3_key("/nurby/cam/f.mp4") == "nurby/cam/f.mp4"
    assert _normalize_remote_root("s3", "nurby/") == "/nurby"
    assert _normalize_remote_root("s3", "") == "/"
    assert rs.remote_path_for("/nurby", "recordings/cam/f.mp4") == "/nurby/cam/f.mp4"


def test_remote_kind_dispatch_parses_both_kinds():
    ftp = rs.seal_ftp_config({"host": "nas"})
    s3 = rs.seal_s3_config(_s3_cfg())
    assert isinstance(rs.parse_remote_config("ftp", ftp), rs.FtpConfig)
    assert isinstance(rs.parse_remote_config("s3", s3), rs.S3Config)
    assert rs.parse_remote_config("local", None) is None


# ── S3 operations against a fake client ──────────────────────────────


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, storage_class="STANDARD", size=None, restore=None, get_error=None):
        self.calls = []
        self.storage_class = storage_class
        self.size = size
        self.restore = restore
        self.get_error = get_error

    def upload_file(self, local, bucket, key, ExtraArgs=None):  # noqa: N803 (boto3 names)
        self.calls.append(("upload", bucket, key, ExtraArgs))
        if self.size is None:
            self.size = os.path.getsize(local)

    def head_object(self, Bucket, Key):  # noqa: N803 (boto3 names)
        out = {"ContentLength": self.size, "StorageClass": self.storage_class}
        if self.restore:
            out["Restore"] = self.restore
        return out

    def download_file(self, bucket, key, local):
        if self.get_error:
            raise FakeClientError(self.get_error)
        with open(local, "wb") as f:
            f.write(b"video")

    def restore_object(self, Bucket, Key, RestoreRequest):  # noqa: N803 (boto3 names)
        self.calls.append(("restore", Key, RestoreRequest))

    def put_object(self, **kw):
        if self.get_error:
            raise FakeClientError(self.get_error)
        self.calls.append(("put", kw["Key"]))

    def delete_object(self, Bucket, Key):  # noqa: N803 (boto3 names)
        self.calls.append(("delete", Key))


def _cfg(**over):
    return rs.parse_s3_config(rs.seal_s3_config(_s3_cfg(**over)))


def test_s3_upload_sets_storage_class_and_verifies_size(tmp_path, monkeypatch):
    local = tmp_path / "f.mp4"
    local.write_bytes(b"x" * 42)
    fake = FakeS3()
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: fake)
    ok, _ = rs._s3_upload_sync(_cfg(), str(local), "/nurby/cam/f.mp4")
    assert ok
    _, bucket, key, extra = fake.calls[0]
    assert (bucket, key) == ("cams", "nurby/cam/f.mp4")
    assert extra["StorageClass"] == "GLACIER_IR"

    short = FakeS3(size=1)
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: short)
    ok, detail = rs._s3_upload_sync(_cfg(), str(local), "/nurby/cam/f.mp4")
    assert not ok and "size mismatch" in detail


def test_s3_standard_upload_sends_no_storage_class(tmp_path, monkeypatch):
    local = tmp_path / "f.mp4"
    local.write_bytes(b"x")
    fake = FakeS3()
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: fake)
    rs._s3_upload_sync(_cfg(storage_class="STANDARD"), str(local), "/k.mp4")
    assert "StorageClass" not in fake.calls[0][3]


def test_s3_download_of_deep_archive_requests_restore(tmp_path, monkeypatch):
    fake = FakeS3(storage_class="DEEP_ARCHIVE", get_error="InvalidObjectState")
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: fake)
    with pytest.raises(rs.RestorePendingError, match="restore has been requested"):
        rs._s3_download_sync(_cfg(storage_class="DEEP_ARCHIVE"), "/k.mp4", str(tmp_path / "c.mp4"))
    assert fake.calls[0][0] == "restore"
    assert fake.calls[0][2]["Days"] == rs.S3_RESTORE_DAYS
    assert not os.path.exists(tmp_path / "c.mp4")


def test_s3_download_reports_restore_in_progress(tmp_path, monkeypatch):
    fake = FakeS3(storage_class="GLACIER", get_error="InvalidObjectState", restore='ongoing-request="true"')
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: fake)
    with pytest.raises(rs.RestorePendingError, match="being restored"):
        rs._s3_download_sync(_cfg(), "/k.mp4", str(tmp_path / "c.mp4"))
    assert not [c for c in fake.calls if c[0] == "restore"]


def test_s3_download_of_instant_class_just_works(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: FakeS3(storage_class="GLACIER_IR"))
    ok, _ = rs._s3_download_sync(_cfg(), "/k.mp4", str(tmp_path / "sub" / "c.mp4"))
    assert ok and (tmp_path / "sub" / "c.mp4").read_bytes() == b"video"


def test_s3_probe_explains_common_failures(monkeypatch):
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: FakeS3(get_error="SignatureDoesNotMatch"))
    ok, detail = rs._s3_probe_sync(_cfg(), "/nurby")
    assert not ok and "secret access key is wrong" in detail

    fake = FakeS3()
    monkeypatch.setattr(rs, "_s3_client", lambda cfg: fake)
    ok, detail = rs._s3_probe_sync(_cfg(), "/nurby")
    assert ok and "cams" in detail
    assert [c[0] for c in fake.calls] == ["put", "delete"]


# ── upload worker: archive moves always free local disk ──────────────


@pytest.mark.asyncio
async def test_archive_upload_removes_local_even_when_profile_keeps_copies(tmp_path):
    from services.ingestion import remote_upload as ru

    local = tmp_path / "f.mp4"
    local.write_bytes(b"x")
    enc = rs.seal_ftp_config({"host": "nas", "delete_after_upload": False})
    profile = SimpleNamespace(id=uuid.uuid4(), name="NAS", kind="ftp", root="/a", config_enc=enc)
    rec = SimpleNamespace(
        id=uuid.uuid4(), camera_id=uuid.uuid4(), file_path="cam/f.mp4", remote_state="pending",
        remote_path=None, remote_profile_id=profile.id, remote_attempts=0, remote_error=None,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=profile))
    worker = ru.RemoteUploadWorker()
    with patch("services.ingestion.retention._resolve_camera_path", new=AsyncMock(return_value=str(local))), \
         patch.object(ru, "remote_upload", new=AsyncMock(return_value=(True, "uploaded"))), \
         patch.object(worker, "_is_archive", new=AsyncMock(return_value=True)):
        await worker._process_one(db, rec)
    assert rec.remote_state == "uploaded"
    assert not local.exists()


# ── retention with an archive destination ───────────────────────────


ARCHIVE = ArchiveTarget(uuid.uuid4(), "/archive", "Glacier", "s3", 0)
OLD = datetime.now(timezone.utc) - timedelta(days=60)


def _rec(**over):
    rec = SimpleNamespace(
        id=uuid.uuid4(), camera_id=uuid.uuid4(), file_path="cam/2026-01-01/f.mp4",
        thumbnail_path=None, started_at=OLD, file_size_bytes=100,
        remote_state=None, remote_path=None, remote_profile_id=None,
        remote_attempts=0, remote_error=None,
    )
    for k, v in over.items():
        setattr(rec, k, v)
    return rec


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows


def _session(*results):
    """async_session() whose execute() returns ``results`` in order."""
    deleted = []
    queue = list(results)

    class DB:
        async def execute(self, *a, **k):
            return _Result(queue.pop(0))

        async def delete(self, obj):
            deleted.append(obj)

        async def commit(self):
            pass

    @asynccontextmanager
    async def factory():
        yield DB()

    return factory, deleted


@pytest.mark.asyncio
async def test_time_retention_archives_instead_of_deleting():
    from services.ingestion import retention as ret

    fresh = _rec()
    in_archive = _rec(remote_state="uploaded", remote_profile_id=ARCHIVE.profile_id)
    failed_archive = _rec(remote_state="failed", remote_profile_id=ARCHIVE.profile_id)
    on_camera_ftp = _rec(remote_state="uploaded", remote_profile_id=uuid.uuid4(), remote_path="/x")
    factory, deleted = _session([fresh, in_archive, failed_archive, on_camera_ftp])
    cam = SimpleNamespace(id=uuid.uuid4(), name="Door")
    with patch.object(ret, "async_session", new=factory), \
         patch.object(ret, "_resolve_camera_path", new=AsyncMock(return_value=None)), \
         patch.object(ret, "_delete_remote_copy", new=AsyncMock(return_value=True)):
        await ret.RetentionManager()._enforce_time(cam, 30, ARCHIVE)

    assert fresh.remote_state == "pending" and fresh.remote_profile_id == ARCHIVE.profile_id
    assert fresh.remote_path == "/archive/cam/2026-01-01/f.mp4"
    # The archive governs what it already owns, including a failed upload
    # whose local file is the only copy. A camera's own FTP copy expires as before.
    assert deleted == [on_camera_ftp]


@pytest.mark.asyncio
async def test_time_retention_without_archive_still_deletes():
    from services.ingestion import retention as ret

    rec = _rec()
    factory, deleted = _session([rec])
    with patch.object(ret, "async_session", new=factory), \
         patch.object(ret, "_resolve_camera_path", new=AsyncMock(return_value=None)), \
         patch.object(ret, "_delete_remote_copy", new=AsyncMock(return_value=True)):
        await ret.RetentionManager()._enforce_time(SimpleNamespace(id=uuid.uuid4(), name="x"), 30, None)
    assert deleted == [rec] and rec.remote_state is None


@pytest.mark.asyncio
async def test_size_retention_moves_oldest_local_to_archive():
    from services.ingestion import retention as ret

    gb = 1024 ** 3
    queued = _rec(remote_state="pending", remote_profile_id=ARCHIVE.profile_id, file_size_bytes=gb)
    oldest = _rec(file_size_bytes=gb)
    newer = _rec(file_size_bytes=gb)
    # 3 GB local against a 1 GB budget: the queued one already counts as
    # freed, so exactly one more moves and the newest stays.
    factory, deleted = _session(3 * gb, [queued, oldest, newer])
    with patch.object(ret, "async_session", new=factory), \
         patch.object(ret, "_resolve_camera_path", new=AsyncMock(return_value=None)):
        await ret.RetentionManager()._enforce_size(SimpleNamespace(id=uuid.uuid4(), name="x"), 1, ARCHIVE)
    assert oldest.remote_state == "pending"
    assert newer.remote_state is None
    assert deleted == []


@pytest.mark.asyncio
async def test_archive_retention_only_drops_rows_whose_object_is_gone():
    from services.ingestion import retention as ret

    gone = _rec(remote_state="uploaded", remote_profile_id=ARCHIVE.profile_id, remote_path="/a")
    stuck = _rec(remote_state="uploaded", remote_profile_id=ARCHIVE.profile_id, remote_path="/b")
    factory, deleted = _session([gone, stuck])
    target = ArchiveTarget(ARCHIVE.profile_id, "/archive", "Glacier", "s3", 365)
    with patch.object(ret, "async_session", new=factory), \
         patch.object(ret, "_resolve_camera_path", new=AsyncMock(return_value=None)), \
         patch.object(ret, "_delete_remote_copy", new=AsyncMock(side_effect=[True, False])):
        await ret.RetentionManager()._enforce_archive_retention(target)
    assert deleted == [gone]


@pytest.mark.asyncio
async def test_archive_retention_zero_keeps_forever():
    from services.ingestion import retention as ret

    with patch.object(ret, "async_session") as session:
        await ret.RetentionManager()._enforce_archive_retention(ARCHIVE)
        await ret.RetentionManager()._enforce_archive_retention(None)
    session.assert_not_called()


# ── archive destination resolution ──────────────────────────────────


@pytest.mark.asyncio
async def test_archive_target_requires_enabled_remote_profile(monkeypatch):
    import shared.archive as arc

    pid = uuid.uuid4()
    settings = {arc.SETTING_PROFILE: str(pid), arc.SETTING_RETENTION: 400}

    async def fake_get(key, default=None):
        return settings.get(key, default)

    monkeypatch.setattr(arc, "get_setting", fake_get)

    def session_with(profile):
        @asynccontextmanager
        async def factory():
            yield SimpleNamespace(get=AsyncMock(return_value=profile))

        return factory

    s3 = SimpleNamespace(id=pid, root="/a", name="Glacier", kind="s3", enabled=True)
    with patch("shared.database.async_session", new=session_with(s3)):
        target = await arc.archive_target()
        assert target.retention_days == 400 and target.kind == "s3"
        assert await arc.archive_misconfigured() is False
    local = SimpleNamespace(id=pid, root="/a", name="Disk", kind="local", enabled=True)
    with patch("shared.database.async_session", new=session_with(local)):
        assert await arc.archive_target() is None
        assert await arc.archive_misconfigured() is True
    settings[arc.SETTING_PROFILE] = None
    assert await arc.archive_target() is None
    assert await arc.archive_misconfigured() is False


# ── storage overview ─────────────────────────────────────────────────


def test_low_disk_warning_fires_without_failed_uploads(tmp_path, monkeypatch):
    """Regression: the low-space check sat inside the failed-upload branch,
    so a full disk was only reported when an FTP upload had also failed."""
    import asyncio

    from services.api.routes import system
    from shared.config import settings

    for sub in ("rec", "thumb", "audio"):
        (tmp_path / sub).mkdir()

    async def fake_get(key, default=None):
        return default

    monkeypatch.setattr("shared.app_settings.get_setting", fake_get)
    monkeypatch.setattr("shared.archive.get_setting", fake_get)
    monkeypatch.setattr(settings, "recordings_path", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "thumbnails_path", str(tmp_path / "thumb"))
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path / "audio"))
    monkeypatch.setattr(system, "LOW_DISK_FREE_BYTES", 1 << 62)

    fake_db = SimpleNamespace(scalar=AsyncMock(return_value=0))
    out = asyncio.run(system.storage_location_status(_current_user=None, db=fake_db))
    assert out.low_space is True
    assert any("free at" in w for w in out.warnings)


# ── archive settings route ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_route_rejects_local_folder():
    from fastapi import HTTPException

    from services.api.routes import storage_profiles as sp

    local = SimpleNamespace(id=uuid.uuid4(), kind="local", enabled=True)
    with patch.object(sp, "_load_profile", new=AsyncMock(return_value=local)), \
         patch("shared.app_settings.set_setting", new=AsyncMock()) as set_setting:
        with pytest.raises(HTTPException) as exc:
            await sp.put_archive_settings(
                sp.ArchiveSettingsUpdate(profile_id=local.id), None, SimpleNamespace()
            )
    assert exc.value.status_code == 400
    set_setting.assert_not_called()


@pytest.mark.asyncio
async def test_archive_destination_cannot_be_deleted():
    from fastapi import HTTPException

    from services.api.routes import storage_profiles as sp

    pid = uuid.uuid4()
    profile = SimpleNamespace(id=pid, kind="s3")
    db = SimpleNamespace(delete=AsyncMock(), commit=AsyncMock())

    async def fake_get(key, default=None):
        return str(pid)

    with patch.object(sp, "_load_profile", new=AsyncMock(return_value=profile)), \
         patch("shared.app_settings.get_setting", new=fake_get):
        with pytest.raises(HTTPException) as exc:
            await sp.delete_profile(pid, None, db)
    assert exc.value.status_code == 409
    db.delete.assert_not_called()
