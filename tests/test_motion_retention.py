"""Motion-samples retention (#37).

The hourly ingestion retention loop prunes motion_samples older than
``motion_series_retention_days``. Like tests/test_motion_query.py there is no
live DB here, so the bulk DELETE is validated by compiling it for the Postgres
dialect (catches construction bugs) and the loop seam is driven with a stubbed
AsyncSession (mirrors the FakeDB style used elsewhere). The sweep must be a
single set-based DELETE (not row-by-row), must skip work when the window is
disabled, and must be a harmless no-op against an empty table.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

import shared.app_settings as app_settings
from services.ingestion import retention
from services.ingestion.retention import (
    RetentionManager,
    prune_motion_samples_stmt,
)


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


# --- setting / default ------------------------------------------------------


def test_retention_setting_defaults_to_7_days():
    assert app_settings.DEFAULTS["motion_series_retention_days"] == 7


# --- bulk DELETE shape ------------------------------------------------------


def test_prune_is_a_single_bulk_delete_on_bucket():
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    sql = _sql(prune_motion_samples_stmt(cutoff))
    assert "delete from motion_samples" in sql
    # Timestamp predicate on the write bucket. Strictly-older, not row-by-row.
    assert "bucket <" in sql
    assert "bucket <=" not in sql
    # Set-based DELETE: no SELECT-then-delete round trip.
    assert "select" not in sql


def test_prune_predicate_carries_the_cutoff():
    cutoff = datetime(2026, 3, 14, 9, 26, 53, tzinfo=timezone.utc)
    sql = _sql(prune_motion_samples_stmt(cutoff))
    assert "2026-03-14 09:26:53" in sql


# --- loop seam: window resolution + empty-table no-op -----------------------


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeDB:
    """Stub AsyncSession capturing the executed statement + commit count."""

    def __init__(self, rowcount=0):
        self._rowcount = rowcount
        self.executed = []
        self.commits = 0

    async def execute(self, stmt):
        self.executed.append(stmt)
        return _FakeResult(self._rowcount)

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, db):
    monkeypatch.setattr(retention, "async_session", lambda: db)


def _patch_setting(monkeypatch, value):
    async def _get(key, default=None):
        assert key == "motion_series_retention_days"
        return value

    monkeypatch.setattr(app_settings, "get_setting", _get)


@pytest.mark.asyncio
async def test_prune_runs_bulk_delete_when_window_set(monkeypatch):
    db = _FakeDB(rowcount=5)
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 7)

    before = datetime.now(timezone.utc)
    await RetentionManager()._enforce_motion_sample_retention()
    after = datetime.now(timezone.utc)

    # Exactly one set-based DELETE issued, then committed.
    assert len(db.executed) == 1
    assert "delete from motion_samples" in _sql(db.executed[0])
    assert db.commits == 1
    # Cutoff is now - window; check it landed roughly 7 days back.
    expected_low = before - timedelta(days=7)
    expected_high = after - timedelta(days=7)
    whereclause = _sql(db.executed[0])
    # The literal-bound cutoff date is 7 days before "now".
    assert str((expected_low).date()) in whereclause or str((expected_high).date()) in whereclause


@pytest.mark.asyncio
async def test_prune_is_noop_on_empty_table(monkeypatch):
    # rowcount 0 == empty table (or nothing old enough). Must not raise and must
    # still be a clean single-DELETE-then-commit with nothing logged as deleted.
    db = _FakeDB(rowcount=0)
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 7)

    await RetentionManager()._enforce_motion_sample_retention()

    assert len(db.executed) == 1
    assert db.commits == 1


@pytest.mark.asyncio
async def test_prune_skipped_when_window_disabled(monkeypatch):
    # Window 0 disables pruning entirely: no DB work at all.
    db = _FakeDB(rowcount=999)
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 0)

    await RetentionManager()._enforce_motion_sample_retention()

    assert db.executed == []
    assert db.commits == 0
