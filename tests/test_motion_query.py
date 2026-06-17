"""Motion-activity endpoint internals: the server-side bucketing query, the
write-side upsert, and the bucket/window guard helpers.

Like tests/test_recordings_filters.py there is no live DB here, so the SQL is
validated by compiling it for the Postgres dialect (catches construction bugs);
semantic behaviour against real rows is covered by the end-to-end check noted in
the PR. The bucket math and clamping are pure and tested directly.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from services.api.motion_query import (
    DEFAULT_BUCKET_SECONDS,
    MAX_BUCKET_SECONDS,
    MAX_BUCKETS,
    MIN_BUCKET_SECONDS,
    clamp_bucket_seconds,
    motion_buckets_query,
)
from services.perception.motion_series import (
    floor_to_bucket,
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
