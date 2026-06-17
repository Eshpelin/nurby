"""Motion-activity endpoint internals: the server-side bucketing query, the
write-side upsert, and the bucket/window guard helpers.

Like tests/test_recordings_filters.py there is no live DB here, so the SQL is
validated by compiling it for the Postgres dialect (catches construction bugs);
semantic behaviour against real rows is covered by the end-to-end check noted in
the PR. The bucket math and clamping are pure and tested directly.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

import shared.app_settings as app_settings
from services.api.motion_query import (
    DEFAULT_BUCKET_SECONDS,
    MAX_BUCKET_SECONDS,
    MAX_BUCKETS,
    MIN_BUCKET_SECONDS,
    clamp_bucket_seconds,
    motion_buckets_query,
)
from services.perception import motion_series
from services.perception.motion_series import (
    floor_to_bucket,
    record_motion_sample_if_enabled,
    upsert_motion_sample_stmt,
)


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


# --- read side: bucketing query ---------------------------------------------


def test_bucket_query_aggregates_server_side():
    cid = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, 1, tzinfo=timezone.utc)
    sql = _sql(motion_buckets_query(cid, t0, t1, 60))
    # Aggregation happens in SQL, not python.
    assert "from motion_samples" in sql
    assert "date_bin" in sql           # fixed-grid bucketing
    assert "max(motion_samples.score)" in sql  # peak intensity per bucket
    assert "count(" in sql             # sample count per bucket
    assert "group by" in sql
    assert "order by" in sql


def test_bucket_query_scopes_to_camera_and_half_open_window():
    cid = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 2, tzinfo=timezone.utc)
    sql = _sql(motion_buckets_query(cid, t0, t1, 300))
    assert "camera_id =" in sql
    assert "bucket >=" in sql          # inclusive lower bound
    assert "bucket <" in sql           # exclusive upper bound (no double-count)
    assert "bucket <=" not in sql      # half-open, not closed


def test_bucket_query_width_reflects_requested_seconds():
    cid = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, 6, tzinfo=timezone.utc)
    # The requested width is passed as the seconds arg of make_interval, which
    # is the last positional (years, months, weeks, days, hours, mins, secs).
    sql900 = _sql(motion_buckets_query(cid, t0, t1, 900))
    assert "make_interval" in sql900
    assert "900" in sql900
    assert "15" in _sql(motion_buckets_query(cid, t0, t1, 15))


# --- bucket clamping --------------------------------------------------------


def test_clamp_within_range_is_identity():
    assert clamp_bucket_seconds(DEFAULT_BUCKET_SECONDS) == DEFAULT_BUCKET_SECONDS
    assert clamp_bucket_seconds(300) == 300


def test_clamp_floor_to_min():
    assert clamp_bucket_seconds(0) == MIN_BUCKET_SECONDS
    assert clamp_bucket_seconds(-5) == MIN_BUCKET_SECONDS


def test_clamp_ceiling_to_max():
    assert clamp_bucket_seconds(10_000) == MAX_BUCKET_SECONDS
    assert clamp_bucket_seconds(MAX_BUCKET_SECONDS + 1) == MAX_BUCKET_SECONDS


def test_bucket_cap_constants_sane():
    assert MIN_BUCKET_SECONDS == 1
    assert MAX_BUCKET_SECONDS == 3600
    assert MAX_BUCKETS >= 1000


# --- write side: max-score upsert -------------------------------------------


def test_upsert_targets_unique_constraint_and_keeps_peak():
    cid = uuid.uuid4()
    bucket = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    sql = _sql(upsert_motion_sample_stmt(cid, bucket, 0.42))
    assert "insert into motion_samples" in sql
    # Upsert on the (camera_id, bucket) unique constraint.
    assert "on conflict on constraint uq_motion_samples_camera_bucket" in sql
    assert "do update" in sql
    # Coalesce keeps the larger score so the row holds the second's peak.
    assert "greatest" in sql


# --- write-side bucketing math ----------------------------------------------


def test_floor_to_bucket_drops_subsecond():
    ts = datetime(2026, 6, 1, 12, 30, 45, 678901, tzinfo=timezone.utc)
    assert floor_to_bucket(ts) == datetime(2026, 6, 1, 12, 30, 45, tzinfo=timezone.utc)


def test_floor_to_bucket_normalizes_naive_to_utc():
    naive = datetime(2026, 6, 1, 12, 0, 0, 500000)
    out = floor_to_bucket(naive)
    assert out.tzinfo == timezone.utc
    assert out.microsecond == 0


def test_floor_to_bucket_converts_other_tz_to_utc():
    tz = timezone(timedelta(hours=5))
    ts = datetime(2026, 6, 1, 17, 0, 30, tzinfo=tz)  # 12:00:30 UTC
    out = floor_to_bucket(ts)
    assert out == datetime(2026, 6, 1, 12, 0, 30, tzinfo=timezone.utc)


def test_two_subsecond_frames_share_one_bucket():
    a = datetime(2026, 6, 1, 12, 0, 0, 100000, tzinfo=timezone.utc)
    b = datetime(2026, 6, 1, 12, 0, 0, 900000, tzinfo=timezone.utc)
    assert floor_to_bucket(a) == floor_to_bucket(b)


# --- endpoint window guard (matches camera_motion_activity) -----------------


def _window_buckets(from_, to, bucket_seconds):
    return (to - from_).total_seconds() / bucket_seconds


def test_window_guard_rejects_unbounded_series():
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # 1 year at 1s buckets is far past the cap.
    t1 = t0 + timedelta(days=365)
    assert _window_buckets(t0, t1, 1) > MAX_BUCKETS


def test_window_guard_allows_reasonable_zoom():
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=24)
    # 24h at 60s buckets = 1440 buckets, under the cap.
    assert _window_buckets(t0, t1, 60) <= MAX_BUCKETS


@pytest.mark.parametrize("bucket_seconds", [1, 15, 60, 300, 3600])
def test_supported_buckets_compile(bucket_seconds):
    cid = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)
    # Must compile for every supported width without error.
    assert "date_bin" in _sql(motion_buckets_query(cid, t0, t1, bucket_seconds))


# --- writer gate: default-OFF feature flag ----------------------------------
#
# The pipeline calls record_motion_sample_if_enabled, which must be a COMPLETE
# no-op (never touch the DB) until an admin flips motion_series_enabled on. The
# gate reads the flag via shared.app_settings.get_setting (resolved lazily), so
# we patch it there. record_motion_sample is stubbed so the test needs no DB.


def test_motion_series_enabled_defaults_off():
    # Existing deployments must see zero new writes until an admin opts in.
    assert app_settings.DEFAULTS["motion_series_enabled"] is False


@pytest.mark.asyncio
async def test_writer_is_noop_when_flag_off(monkeypatch):
    async def _flag_off(key, default=None):
        assert key == "motion_series_enabled"
        return False

    calls: list = []

    async def _spy(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(app_settings, "get_setting", _flag_off)
    monkeypatch.setattr(motion_series, "record_motion_sample", _spy)

    wrote = await record_motion_sample_if_enabled(
        uuid.uuid4(), datetime(2026, 6, 1, tzinfo=timezone.utc), 0.5
    )
    assert wrote is False
    assert calls == []  # writer never invoked


@pytest.mark.asyncio
async def test_writer_runs_when_flag_on(monkeypatch):
    async def _flag_on(key, default=None):
        return True

    calls: list = []

    async def _spy(camera_id, ts, score):
        calls.append((camera_id, ts, score))

    monkeypatch.setattr(app_settings, "get_setting", _flag_on)
    monkeypatch.setattr(motion_series, "record_motion_sample", _spy)

    cid = uuid.uuid4()
    ts = datetime(2026, 6, 1, tzinfo=timezone.utc)
    wrote = await record_motion_sample_if_enabled(cid, ts, 0.5)
    assert wrote is True
    assert calls == [(cid, ts, 0.5)]


# --- endpoint ACL scoping (issue #40) ---------------------------------------
#
# GET /cameras/{id}/motion must 404 for a camera outside the caller's allowlist,
# exactly like the other single-camera reads PR #83 added. Drives the real
# handler-internal scoping seam (_require_camera_in_scope) so the check is the
# same one production runs. Mirrors test_camera_access.py's FakeDB style.


def _user(role: str = "viewer") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Stub AsyncSession: ``execute`` returns canned grant rows; ``get`` would
    only be reached if scoping passed (it must not, for a foreign camera)."""

    def __init__(self, responder):
        self._responder = responder

    async def execute(self, stmt):
        return _FakeResult(self._responder(str(stmt)))

    async def get(self, model, ident):  # pragma: no cover - must not be reached
        raise AssertionError("scoping should reject before any camera lookup")


@pytest.mark.asyncio
async def test_motion_endpoint_404s_for_cross_user_camera():
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()
    foreign = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    # Restricted user granted only `owned`; asking for `foreign` -> 404.
    db = _FakeDB(lambda stmt: [(owned,)])
    with pytest.raises(HTTPException) as exc:
        await cameras_mod.camera_motion_activity(
            camera_id=foreign,
            from_=t0,
            to=t1,
            bucket_seconds=DEFAULT_BUCKET_SECONDS,
            current_user=_user("viewer"),
            db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_motion_endpoint_scope_passes_for_owned_camera(monkeypatch):
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    # The owned camera clears scoping; stub the camera lookup + aggregation so
    # the test needs no DB and asserts scoping does NOT block an allowed camera.
    class _OwnedDB(_FakeDB):
        async def get(self, model, ident):
            return SimpleNamespace(id=owned)

        async def execute(self, stmt):
            s = str(stmt)
            if "user_camera_access" in s.lower():
                return _FakeResult([(owned,)])
            return _FakeResult([])  # no motion rows

    got = await cameras_mod.camera_motion_activity(
        camera_id=owned,
        from_=t0,
        to=t1,
        bucket_seconds=DEFAULT_BUCKET_SECONDS,
        current_user=_user("viewer"),
        db=_OwnedDB(lambda stmt: [(owned,)]),
    )
    assert got["camera_id"] == str(owned)
    assert got["buckets"] == []
    assert got["count"] == 0
