"""Observation retention (#213).

The hourly ingestion retention loop prunes observations (with their
thumbnail files and cascade-owned child rows) older than
``observation_retention_days``. Like tests/test_motion_retention.py there
is no live DB here: the bulk DELETE is validated by compiling it for the
Postgres dialect and the sweep seam is driven with a stubbed AsyncSession.
The sweep must delete in bounded batches, remove thumbnail files
best-effort, stop cleanly when the backlog is drained, and be a no-op
when the window is disabled.
"""

import uuid

import pytest
from sqlalchemy.dialects import postgresql

import shared.app_settings as app_settings
from services.ingestion import retention
from services.ingestion.retention import (
    OBSERVATION_PRUNE_BATCH,
    OBSERVATION_PRUNE_MAX_BATCHES,
    RetentionManager,
    _resolve_thumbnail_path,
    prune_observations_stmt,
)


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


# --- setting / default ------------------------------------------------------


def test_retention_setting_defaults_to_90_days():
    assert app_settings.DEFAULTS["observation_retention_days"] == 90


# --- bulk DELETE shape ------------------------------------------------------


def test_prune_is_a_single_bulk_delete_on_ids():
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    sql = _sql(prune_observations_stmt(ids))
    assert "delete from observations" in sql
    # Set-based DELETE by id list: no SELECT-then-delete round trip.
    assert " in (" in sql
    assert "select" not in sql


# --- thumbnail path resolution ----------------------------------------------


def test_resolve_thumbnail_path_strips_base_prefix(monkeypatch):
    monkeypatch.setattr(retention.settings, "thumbnails_path", "./thumbnails")
    resolved = _resolve_thumbnail_path("thumbnails/observations/cam_20260101_120000.jpg")
    # No doubled "thumbnails/thumbnails": the prefix is stripped before
    # joining onto the (cwd-resolved) base.
    assert not resolved.count("thumbnails/thumbnails")
    assert resolved.endswith("thumbnails/observations/cam_20260101_120000.jpg")


def test_resolve_thumbnail_path_absolute_passthrough(monkeypatch):
    monkeypatch.setattr(retention.settings, "thumbnails_path", "/mnt/nas/thumbs")
    assert _resolve_thumbnail_path("/elsewhere/x.jpg") == "/elsewhere/x.jpg"
    assert _resolve_thumbnail_path(None) is None


# --- loop seam ---------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return self._rows


class _FakeDB:
    """Stub AsyncSession. ``select_results`` are returned from execute() in
    order (one per SELECT); DELETEs return a fixed rowcount."""

    def __init__(self, select_results):
        self.select_results = list(select_results)
        self.executed = []
        self.commits = 0

    async def execute(self, stmt):
        self.executed.append(stmt)
        if self.select_results:
            return _FakeResult(rows=self.select_results.pop(0))
        return _FakeResult(rowcount=1)

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, db):
    monkeypatch.setattr(retention, "async_session", lambda: db)


def _patch_setting(monkeypatch, value):
    import shared.app_settings as app_settings_mod

    async def _get(key, default=None):
        assert key == "observation_retention_days"
        return value

    monkeypatch.setattr(app_settings_mod, "get_setting", _get)


def _row():
    thumb = f"thumbnails/observations/{uuid.uuid4().hex}.jpg"
    return (uuid.uuid4(), thumb, None)


@pytest.mark.asyncio
async def test_sweep_is_noop_when_window_disabled(monkeypatch):
    db = _FakeDB(select_results=[])
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 0)

    await RetentionManager()._enforce_observation_retention()

    assert db.executed == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_sweep_deletes_batch_and_removes_thumbnails(monkeypatch):
    # r1 has a distinct clean frame (both files removed); r2's clean fell
    # back to the annotated path (single removal, no duplicate).
    r1 = (
        uuid.uuid4(),
        f"thumbnails/observations/{uuid.uuid4().hex}.jpg",
        f"thumbnails/observations/{uuid.uuid4().hex}_clean.jpg",
    )
    r2 = (uuid.uuid4(), f"thumbnails/observations/{uuid.uuid4().hex}.jpg", None)
    r2 = (r2[0], r2[1], r2[1])
    db = _FakeDB(select_results=[[r1, r2]])
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 90)
    removed: list[str] = []

    def _fake_remove(path):
        if path:
            removed.append(path)
        return 0, True

    monkeypatch.setattr(retention, "_remove_file", _fake_remove)

    await RetentionManager()._enforce_observation_retention()

    # One SELECT (returned fewer rows than the batch size → drained) and
    # one DELETE for exactly those ids, then one commit.
    assert len(db.executed) == 2
    assert db.executed[0].is_select
    sql = str(db.executed[1].compile(compile_kwargs={"literal_binds": True})).lower()
    assert "delete from observations" in sql
    # The dialect renders UUID literals without dashes.
    compact = sql.replace("-", "")
    assert str(r1[0]).replace("-", "") in compact
    assert str(r2[0]).replace("-", "") in compact
    assert db.commits == 1
    # Paths arrive at _remove_file resolved; thumb + clean for r1, only the
    # thumb for r2 (clean == thumb).
    assert removed == [
        _resolve_thumbnail_path(r1[1]),
        _resolve_thumbnail_path(r1[2]),
        _resolve_thumbnail_path(r2[1]),
    ]


@pytest.mark.asyncio
async def test_sweep_caps_batches_per_run(monkeypatch):
    db = _FakeDB(select_results=[[_row() for _ in range(OBSERVATION_PRUNE_BATCH)]] * 50)
    _patch_session(monkeypatch, db)
    _patch_setting(monkeypatch, 90)
    monkeypatch.setattr(retention, "_remove_file", lambda p: (0, True))

    await RetentionManager()._enforce_observation_retention()

    deletes = [s for s in db.executed if not s.is_select]
    assert len(deletes) == OBSERVATION_PRUNE_MAX_BATCHES
    assert db.commits == OBSERVATION_PRUNE_MAX_BATCHES
