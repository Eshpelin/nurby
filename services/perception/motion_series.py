"""Persist the downsampled per-camera motion-score series.

Writes one row per camera-second into motion_samples from the EXISTING motion
pipeline (called from the perception keyframe path), keeping the peak score in
each second. This is deliberately not a second motion detector: it consumes the
motion_score the ingestion stream already computed (services.ingestion.stream
._detect_motion) and forwarded on the keyframe.

The write is an idempotent upsert on (camera_id, bucket) that keeps the larger
score, so any number of sub-second frames in the same second collapse to a
single row without read-modify-write races. The read endpoint
(GET /cameras/{id}/motion) re-aggregates these into coarser buckets.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.database import async_session
from shared.models import MotionSample

logger = logging.getLogger(__name__)

# Must match shared.models.MotionSample / motion_query.WRITE_BUCKET_SECONDS.
WRITE_BUCKET_SECONDS = 1


def floor_to_bucket(ts: datetime) -> datetime:
    """Truncate a timestamp to the 1-second write bucket, normalized to UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.replace(microsecond=0)


def upsert_motion_sample_stmt(camera_id: uuid.UUID, bucket: datetime, score: float) -> Insert:
    """Build the max-score upsert for one camera-second.

    Pure builder so it can be compiled/asserted in tests without a DB (cf.
    tests/test_recordings_filters.py). On conflict the stored score is replaced
    only when the incoming score is larger (GREATEST), so the row always holds
    the peak motion for that second regardless of write order.
    """
    stmt = pg_insert(MotionSample).values(
        id=uuid.uuid4(),
        camera_id=camera_id,
        bucket=bucket,
        score=float(score),
    )
    return stmt.on_conflict_do_update(
        constraint="uq_motion_samples_camera_bucket",
        set_={"score": func_greatest(MotionSample.score, stmt.excluded.score)},
    )


def func_greatest(a, b):
    # Local import keeps the pure builder importable without pulling func at
    # module top; GREATEST is the standard SQL max-of-two-scalars.
    from sqlalchemy import func

    return func.greatest(a, b)


async def record_motion_sample(camera_id: str | uuid.UUID, timestamp: datetime, score: float) -> None:
    """Persist one motion observation. Best-effort: never raise into the
    keyframe path. Coalesces to a 1-second bucket keeping the peak score."""
    try:
        cam_uuid = camera_id if isinstance(camera_id, uuid.UUID) else uuid.UUID(str(camera_id))
    except (ValueError, AttributeError):
        return
    if score is None:
        return
    bucket = floor_to_bucket(timestamp)
    try:
        async with async_session() as db:
            await db.execute(upsert_motion_sample_stmt(cam_uuid, bucket, score))
            await db.commit()
    except Exception:
        # Motion-series persistence is auxiliary telemetry. A failure here must
        # never break detection/recording, so we log and move on.
        logger.debug("motion sample upsert failed for camera %s", camera_id, exc_info=True)
