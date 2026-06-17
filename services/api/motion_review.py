"""Motion-only review items: contiguous spans of significant motion with no
detected object/Observation (or Event) overlapping them (#37).

Frigate lets an operator review spans where *motion* occurred even though the
detector found nothing, catching things the object detector missed. This module
computes those spans ON THE FLY from the already-persisted per-camera 1-second
motion series (shared.models.MotionSample) plus the existing Observation/Event
rows. Nothing new is stored: a span is derived at read time and discarded.

Why on-the-fly rather than a new table:
  * The inputs (motion_samples, observations, events) already exist and are
    already indexed by (camera_id, time). The span set is a cheap derivation of
    them, and it changes whenever an observation lands, so persisting it would
    just be a cache to invalidate. Computing per request keeps it always correct
    and adds no migration.
  * The motion series only populates when ``motion_series_enabled`` is on, so
    when the flag is off (the default) there are simply no rows and the result
    degrades to an empty list. We never error on an empty/disabled series.

The pure helpers here (the SQL builders and ``build_motion_only_spans``) take no
DB so they can be unit-tested by compiling to the Postgres dialect / called with
plain rows, the same way services.api.motion_query is tested.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, or_, select

from shared.models import Event, MotionSample, Observation

# --- span-detection thresholds (documented defaults) ------------------------
#
# A "significant motion" second is one whose peak score (0..1) is at or above
# this. The motion series stores the per-second peak (MotionSample.score), so
# this is compared against that peak directly. 0.5 keeps idle camera noise
# (lighting flicker, compression shimmer) out while still catching real motion.
MOTION_REVIEW_THRESHOLD = 0.5

# Two above-threshold seconds separated by a quiet gap no longer than this are
# treated as one span. Real activity dips below threshold for a second or two
# (a person pausing, turning); bridging short gaps yields one reviewable span
# per event instead of a shower of one-second fragments.
MERGE_GAP_SECONDS = 5

# A merged span shorter than this is dropped as noise (a single flicker, a bird,
# a brief reflection). Five seconds is long enough to be worth a human glance.
MIN_SPAN_SECONDS = 5

# Hard cap on the number of spans returned for one request, so a pathological
# window can never produce an unbounded payload. The window guard on the
# endpoint already bounds the sample scan; this bounds the derived spans.
MAX_REVIEW_SPANS = 500

# The per-second write resolution of the motion series (MotionSample.bucket is
# floored to the second). Used to size the contiguity/merge gap in seconds.
WRITE_BUCKET_SECONDS = 1


def motion_seconds_query(
    camera_id: uuid.UUID,
    from_: datetime,
    to: datetime,
    threshold: float = MOTION_REVIEW_THRESHOLD,
) -> Select:
    """SELECT the above-threshold 1-second motion buckets for one camera over
    the half-open window [from_, to), ordered by time.

    Returns rows of (bucket, score). The threshold filter is applied in SQL so
    only candidate seconds cross the wire; span assembly happens in Python on
    this already-small, ordered set.
    """
    return (
        select(MotionSample.bucket, MotionSample.score)
        .where(MotionSample.camera_id == camera_id)
        .where(MotionSample.bucket >= from_)
        .where(MotionSample.bucket < to)
        .where(MotionSample.score >= threshold)
        .order_by(MotionSample.bucket)
    )


def overlapping_observations_query(
    camera_id: uuid.UUID,
    from_: datetime,
    to: datetime,
) -> Select:
    """SELECT (started_at, ended_at) for observations on one camera that could
    overlap the window [from_, to).

    An observation overlaps the window when it starts before ``to`` and ends
    after ``from_``. ``ended_at`` is nullable (a still-open / instantaneous
    observation); a NULL end is treated as a zero-length interval at
    ``started_at`` (handled by the caller), so here we only require it to start
    before the window ends and, when it has an end, to end after the window
    starts.
    """
    return (
        select(Observation.started_at, Observation.ended_at)
        .where(Observation.camera_id == camera_id)
        .where(Observation.started_at < to)
        .where(
            or_(
                Observation.ended_at.is_(None),
                Observation.ended_at > from_,
            )
        )
        .order_by(Observation.started_at)
    )


def overlapping_events_query(
    camera_id: uuid.UUID,
    from_: datetime,
    to: datetime,
) -> Select:
    """SELECT fired_at for events on one camera within the window [from_, to).

    Events are point-in-time (``fired_at``), so an event "overlaps" a span when
    its instant falls inside the span. We pull events in the window and treat
    each as a zero-length interval at ``fired_at``.
    """
    return (
        select(Event.fired_at)
        .where(Event.camera_id == camera_id)
        .where(Event.fired_at >= from_)
        .where(Event.fired_at < to)
        .order_by(Event.fired_at)
    )


@dataclass(frozen=True)
class MotionSpan:
    """A contiguous run of significant motion. Half-open [start, end)."""

    start: datetime
    end: datetime
    peak: float
    samples: int

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def assemble_spans(
    rows: list[tuple[datetime, float]],
    *,
    merge_gap_seconds: int = MERGE_GAP_SECONDS,
    min_span_seconds: int = MIN_SPAN_SECONDS,
) -> list[MotionSpan]:
    """Group ordered above-threshold (bucket, score) seconds into spans.

    Contiguous or near-contiguous seconds (gap <= ``merge_gap_seconds``) merge
    into one span. Each span is half-open: its ``end`` is one write-bucket past
    the last contributing second, so a single matched second yields a span of
    ``WRITE_BUCKET_SECONDS`` length rather than zero. Spans shorter than
    ``min_span_seconds`` are dropped as noise.

    Pure: no DB, no clock. Rows must already be time-ordered ascending.
    """
    if not rows:
        return []

    bucket = timedelta(seconds=WRITE_BUCKET_SECONDS)
    gap = timedelta(seconds=merge_gap_seconds)

    spans: list[MotionSpan] = []
    run_start = rows[0][0]
    last = rows[0][0]
    peak = rows[0][1]
    count = 1

    def _flush(start: datetime, last_second: datetime, pk: float, n: int) -> None:
        end = last_second + bucket
        span = MotionSpan(start=start, end=end, peak=float(pk), samples=n)
        if span.duration_seconds >= min_span_seconds:
            spans.append(span)

    for ts, score in rows[1:]:
        # ts and last are floored to the second; bridge a gap only when the
        # quiet stretch between them is within the merge window.
        if ts - last <= gap:
            last = ts
            peak = max(peak, score)
            count += 1
        else:
            _flush(run_start, last, peak, count)
            run_start = ts
            last = ts
            peak = score
            count = 1
    _flush(run_start, last, peak, count)
    return spans


def _intervals_from_observations(
    obs_rows: list[tuple[datetime, datetime | None]],
) -> list[tuple[datetime, datetime]]:
    """Normalize observation (started_at, ended_at) rows into closed intervals.

    A NULL ``ended_at`` is treated as a zero-length interval at ``started_at``
    (an instantaneous / still-open observation): it still suppresses a span that
    contains that instant.
    """
    intervals: list[tuple[datetime, datetime]] = []
    for started_at, ended_at in obs_rows:
        end = ended_at if ended_at is not None else started_at
        if end < started_at:
            end = started_at
        intervals.append((started_at, end))
    return intervals


def span_is_motion_only(
    span: MotionSpan,
    detection_intervals: list[tuple[datetime, datetime]],
) -> bool:
    """True iff no detection interval overlaps the span.

    Overlap test for half-open span [start, end) against a (possibly
    zero-length) detection interval [d_start, d_end]: they overlap when
    ``d_start < span.end`` and ``d_end >= span.start``. A zero-length detection
    at instant ``t`` (d_start == d_end == t) overlaps when ``span.start <= t <
    span.end``.
    """
    for d_start, d_end in detection_intervals:
        if d_start < span.end and d_end >= span.start:
            return False
    return True


def build_motion_only_spans(
    motion_rows: list[tuple[datetime, float]],
    obs_rows: list[tuple[datetime, datetime | None]],
    event_instants: list[datetime],
    *,
    merge_gap_seconds: int = MERGE_GAP_SECONDS,
    min_span_seconds: int = MIN_SPAN_SECONDS,
    max_spans: int = MAX_REVIEW_SPANS,
) -> list[MotionSpan]:
    """End-to-end pure assembler: motion seconds + detections -> motion-only spans.

    1. Assemble above-threshold seconds into merged spans.
    2. Drop any span overlapped by an observation interval or an event instant.
    3. Cap the count at ``max_spans``.

    Returns spans in time order. ``motion_rows`` empty (flag off / empty table)
    yields ``[]`` with no error.
    """
    spans = assemble_spans(
        motion_rows,
        merge_gap_seconds=merge_gap_seconds,
        min_span_seconds=min_span_seconds,
    )
    if not spans:
        return []

    intervals = _intervals_from_observations(obs_rows)
    intervals.extend((t, t) for t in event_instants)

    motion_only = [s for s in spans if span_is_motion_only(s, intervals)]
    return motion_only[:max_spans]
