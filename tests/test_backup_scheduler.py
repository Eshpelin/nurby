from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.backup_scheduler import BackupScheduler


def test_due_when_missing_or_old(monkeypatch):
    import services.backup_scheduler as mod

    monkeypatch.setattr(mod.settings, "backup_schedule_hours", 24)
    assert BackupScheduler._due(None)
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert BackupScheduler._due(old)
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert not BackupScheduler._due(recent)


def test_prune_keeps_newest_archives(tmp_path: Path):
    paths = [tmp_path / f"nurby-{i}.nurby" for i in range(4)]
    for i, path in enumerate(paths):
        path.write_text(str(i))
        path.touch()
        path_ts = path.stat().st_mtime
        import os
        os.utime(path, (path_ts + i, path_ts + i))
    (tmp_path / "keep.txt").write_text("not a backup")
    BackupScheduler._prune(tmp_path, 2)
    assert {p.name for p in tmp_path.glob("*.nurby")} == {"nurby-2.nurby", "nurby-3.nurby"}
    assert (tmp_path / "keep.txt").exists()


@pytest.mark.asyncio
async def test_run_once_preserves_previous_archive_on_failure(monkeypatch, tmp_path):
    import services.backup_scheduler as mod

    monkeypatch.setattr(mod.settings, "backup_schedule_hours", 24)
    monkeypatch.setattr(mod.settings, "backup_passphrase", "long-enough-secret")
    monkeypatch.setattr(mod.settings, "backup_path", str(tmp_path))
    monkeypatch.setattr(mod.settings, "backup_include_recordings", False)
    monkeypatch.setattr(mod.settings, "backup_retention_count", 7)
    previous = tmp_path / "nurby-old.nurby"
    previous.write_bytes(b"known-good")

    async def _never():
        return None

    monkeypatch.setattr(mod, "logger", SimpleNamespace(
        info=lambda *a, **k: None,
        exception=lambda *a, **k: None,
        warning=lambda *a, **k: None,
    ))
    import services.backup as backup
    monkeypatch.setattr(backup, "backup_status", lambda: {"last_success_at": None})
    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(backup, "create_backup", fail)
    assert await BackupScheduler().run_once(force=True) is None
    assert previous.read_bytes() == b"known-good"
