"""Server-side bucketing for the per-camera motion-activity series.

The motion_samples table stores at most one row per camera-second (the peak
score in that second; see shared.models.MotionSample). The motion endpoint
re-aggregates those 1-second rows into coarser, caller-chosen buckets entirely
in SQL so the wire payload is compact regardless of window length. This mirrors
Frigate's optimized motion-activity endpoint (#23383): aggregate server-side,
return compact buckets, never ship raw per-second rows.

The query builder is split out (and pure) so it can be unit-tested by compiling
to the Postgres dialect without a live DB, the same way recordings filters are
tested (tests/test_recordings_filters.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, Select, cast, func, select

from shared.models import MotionSample

# Write-side resolution: motion_samples holds one row per camera-second.
# Read buckets are clamped to multiples of this; finer is meaningless.
WRITE_BUCKET_SECONDS = 1

# Guard rails for the caller-chosen read bucket. Min one second (the write
# resolution); max one hour so a huge window still returns a bounded series.
MIN_BUCKET_SECONDS = WRITE_BUCKET_SECONDS
MAX_BUCKET_SECONDS = 3600

# Default read bucket when the caller does not specify one.
DEFAULT_BUCKET_SECONDS = 60

# Hard cap on the number of buckets returned, independent of window/bucket
# choice, so a pathological from/to can never produce an unbounded result set.
MAX_BUCKETS = 2000


def clamp_bucket_seconds(bucket_seconds: int) -> int:
    """Clamp a requested read-bucket width into the supported range."""
    return max(MIN_BUCKET_SECONDS, min(MAX_BUCKET_SECONDS, int(bucket_seconds)))


def motion_buckets_query(
    camera_id: uuid.UUID,
    from_: datetime,
    to: datetime,
    bucket_seconds: int,
) -> Select:
    """Build the SELECT that aggregates 1-second motion rows into ``bucket_seconds``
    buckets for one camera over [from_, to].

    Aggregation is server-side: PostgreSQL ``date_bin`` snaps each 1s row onto a
    fixed grid anchored at ``from_``, and per bucket we return the peak intensity
    (max score) and the sample count. Empty buckets are simply absent from the
    result. the caller (or UI) treats a missing bucket as zero motion, so we do
    not synthesize zero rows here.

    Returns rows of (bucket_start, intensity, samples) ordered by time.
    """
    # make_interval(years, months, weeks, days, hours, mins, secs). Build the
    # bucket width from seconds (matches recordings.py's interval construction).
    width = func.make_interval(0, 0, 0, 0, 0, 0, int(bucket_seconds))
    bucket_start = func.date_bin(width, MotionSample.bucket, from_).label("bucket_start")

    return (
        select(
            bucket_start,
            cast(func.max(MotionSample.score), Float).label("intensity"),
            func.count().label("samples"),
        )
        .where(MotionSample.camera_id == camera_id)
        .where(MotionSample.bucket >= from_)
        .where(MotionSample.bucket < to)
        .group_by(bucket_start)
        .order_by(bucket_start)
    )
