"""Motion-only review items (#37): the span assembler, the overlap test, and
the endpoint's gating / ACL behaviour.

Like tests/test_motion_query.py there is no live DB here. The SQL builders are
validated by compiling them for the Postgres dialect; the span math and overlap
logic are pure and exercised directly with plain rows; the endpoint is driven
through its real handler with a stub session (mirrors the ACL test there).
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from services.api.motion_review import (
    MAX_REVIEW_SPANS,
    MERGE_GAP_SECONDS,
    MIN_SPAN_SECONDS,
    MOTION_REVIEW_THRESHOLD,
    WRITE_BUCKET_SECONDS,
    MotionSpan,
    assemble_spans,
    build_motion_only_spans,
    motion_seconds_query,
    overlapping_events_query,
    overlapping_observations_query,
    span_is_motion_only,
)

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


def _sec(n: int) -> datetime:
    """The bucket timestamp n seconds after T0."""
    return T0 + timedelta(seconds=n)


def _run(start: int, length: int, score: float = 0.9):
    """A contiguous run of one-second rows [start, start+length) at ``score``."""
    return [(_sec(start + i), score) for i in range(length)]


# --- threshold constants ----------------------------------------------------


def test_thresholds_are_sane():
    assert 0.0 < MOTION_REVIEW_THRESHOLD <= 1.0
    assert MIN_SPAN_SECONDS >= 1
    assert MERGE_GAP_SECONDS >= 0
    assert WRITE_BUCKET_SECONDS == 1
    assert MAX_REVIEW_SPANS >= 100


# --- read-side SQL builders compile and scope correctly ---------------------


def test_motion_seconds_query_filters_threshold_and_window():
    cid = uuid.uuid4()
    sql = _sql(motion_seconds_query(cid, T0, _sec(3600), MOTION_REVIEW_THRESHOLD))
    assert "from motion_samples" in sql
    assert "camera_id =" in sql
    assert "bucket >=" in sql        # inclusive lower bound
    assert "bucket <" in sql         # exclusive upper bound
    assert "bucket <=" not in sql    # half-open
    assert "score >=" in sql         # threshold applied in SQL
    assert "order by" in sql


def test_observation_overlap_query_handles_null_end():
    cid = uuid.uuid4()
    sql = _sql(overlapping_observations_query(cid, T0, _sec(3600)))
    assert "from observations" in sql
    assert "camera_id =" in sql
    # An observation overlaps when it starts before `to` and (ends after `from`
    # OR has no end). The null-end branch must be present.
    assert "ended_at is null" in sql
    assert "started_at <" in sql


def test_event_overlap_query_scopes_window():
    cid = uuid.uuid4()
    sql = _sql(overlapping_events_query(cid, T0, _sec(3600)))
    assert "from events" in sql
    assert "fired_at >=" in sql
    assert "fired_at <" in sql


# --- span assembly ----------------------------------------------------------


def test_empty_rows_yield_no_spans():
    assert assemble_spans([]) == []


def test_single_long_run_is_one_span():
    spans = assemble_spans(_run(0, 10, score=0.7))
    assert len(spans) == 1
    s = spans[0]
    assert s.start == _sec(0)
    # Half-open: end is one bucket past the last contributing second.
    assert s.end == _sec(10)
    assert s.duration_seconds == 10
    assert s.peak == 0.7
    assert s.samples == 10


def test_short_run_below_min_is_dropped():
    # MIN_SPAN_SECONDS default is 5; a 3-second run is noise.
    spans = assemble_spans(_run(0, 3))
    assert spans == []


def test_gap_within_merge_window_joins_runs():
    # Two 5s runs separated by a 3s quiet gap (<= MERGE_GAP_SECONDS) -> one span.
    rows = _run(0, 5) + _run(8, 5)  # gap of 3s between last (sec 4) and next (sec 8)
    spans = assemble_spans(rows, merge_gap_seconds=5, min_span_seconds=5)
    assert len(spans) == 1
    assert spans[0].start == _sec(0)
    assert spans[0].end == _sec(13)


def test_gap_beyond_merge_window_splits_runs():
    # Same two runs but a 20s gap -> two separate spans.
    rows = _run(0, 5) + _run(25, 5)
    spans = assemble_spans(rows, merge_gap_seconds=5, min_span_seconds=5)
    assert len(spans) == 2
    assert spans[0].start == _sec(0)
    assert spans[1].start == _sec(25)


def test_peak_is_max_score_across_the_span():
    rows = [(_sec(0), 0.6), (_sec(1), 0.95), (_sec(2), 0.7), (_sec(3), 0.8), (_sec(4), 0.65)]
    spans = assemble_spans(rows, min_span_seconds=5)
    assert len(spans) == 1
    assert spans[0].peak == 0.95


# --- overlap test -----------------------------------------------------------


def _span(start: int, end: int) -> MotionSpan:
    return MotionSpan(start=_sec(start), end=_sec(end), peak=0.9, samples=end - start)


def test_span_with_no_detection_is_motion_only():
    assert span_is_motion_only(_span(0, 10), []) is True


def test_span_fully_covered_by_observation_is_not_motion_only():
    # Observation [2, 8] sits inside span [0, 10).
    assert span_is_motion_only(_span(0, 10), [(_sec(2), _sec(8))]) is False


def test_span_partially_overlapped_is_not_motion_only():
    # Observation [8, 12] starts inside span [0, 10).
    assert span_is_motion_only(_span(0, 10), [(_sec(8), _sec(12))]) is False


def test_detection_entirely_outside_span_does_not_suppress():
    # Observation [20, 30] is well after span [0, 10).
    assert span_is_motion_only(_span(0, 10), [(_sec(20), _sec(30))]) is True


def test_zero_length_event_inside_span_suppresses():
    # An instantaneous event at second 5 falls inside span [0, 10).
    assert span_is_motion_only(_span(0, 10), [(_sec(5), _sec(5))]) is False


def test_zero_length_event_at_span_end_does_not_suppress():
    # Span is half-open [0, 10); an instant exactly at the end is outside.
    assert span_is_motion_only(_span(0, 10), [(_sec(10), _sec(10))]) is True


# --- end-to-end pure assembler ----------------------------------------------


def test_motion_span_with_no_overlapping_observation_is_returned():
    motion = _run(0, 10)
    spans = build_motion_only_spans(motion, obs_rows=[], event_instants=[])
    assert len(spans) == 1
    assert spans[0].start == _sec(0)


def test_motion_span_covered_by_observation_is_excluded():
    motion = _run(0, 10)
    # An observation overlapping the span removes it from the motion-only set.
    spans = build_motion_only_spans(
        motion, obs_rows=[(_sec(3), _sec(6))], event_instants=[]
    )
    assert spans == []


def test_motion_span_covered_by_event_instant_is_excluded():
    motion = _run(0, 10)
    spans = build_motion_only_spans(motion, obs_rows=[], event_instants=[_sec(4)])
    assert spans == []


def test_open_ended_observation_suppresses_overlapping_span():
    # ended_at = None is treated as an instant at started_at; if that instant is
    # inside the span, the span is suppressed.
    motion = _run(0, 10)
    spans = build_motion_only_spans(motion, obs_rows=[(_sec(5), None)], event_instants=[])
    assert spans == []


def test_only_uncovered_spans_survive_among_several():
    # Span A [0,10) is covered by an observation; span B [60,70) is not.
    motion = _run(0, 10) + _run(60, 10)
    spans = build_motion_only_spans(
        motion, obs_rows=[(_sec(2), _sec(8))], event_instants=[]
    )
    assert len(spans) == 1
    assert spans[0].start == _sec(60)


def test_no_samples_yields_empty():
    assert build_motion_only_spans([], obs_rows=[], event_instants=[]) == []


def test_max_spans_cap_is_enforced():
    # Build many well-separated 5s spans, then ensure the cap truncates.
    motion = []
    for i in range(MAX_REVIEW_SPANS + 5):
        motion += _run(i * 100, 5)
    spans = build_motion_only_spans(motion, obs_rows=[], event_instants=[], max_spans=10)
    assert len(spans) == 10


# --- endpoint: gating, ACL, empty-degradation -------------------------------
#
# Drive the real handler with a stub session, mirroring the ACL test in
# tests/test_motion_query.py so the same production seams run.


def _user(role: str = "viewer") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


@pytest.mark.asyncio
async def test_review_items_404s_for_cross_user_camera():
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()
    foreign = uuid.uuid4()

    class _DB:
        async def execute(self, stmt):
            return _FakeResult([(owned,)])  # grant rows: only `owned`

        async def get(self, model, ident):  # pragma: no cover - must not run
            raise AssertionError("scoping must reject before camera lookup")

    with pytest.raises(HTTPException) as exc:
        await cameras_mod.camera_motion_review_items(
            camera_id=foreign,
            from_=T0,
            to=_sec(3600),
            current_user=_user(),
            db=_DB(),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_review_items_empty_when_no_motion_samples():
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()

    class _DB:
        async def get(self, model, ident):
            return SimpleNamespace(id=owned, exclude_from_review=False)

        async def execute(self, stmt):
            s = str(stmt).lower()
            if "user_camera_access" in s:
                return _FakeResult([(owned,)])
            return _FakeResult([])  # no motion rows, no observations, no events

    got = await cameras_mod.camera_motion_review_items(
        camera_id=owned, from_=T0, to=_sec(3600), current_user=_user(), db=_DB()
    )
    assert got["items"] == []
    assert got["count"] == 0
    # The thresholds the spans were computed under are echoed for the UI.
    assert got["threshold"] == MOTION_REVIEW_THRESHOLD


@pytest.mark.asyncio
async def test_review_items_empty_when_camera_excluded_from_review():
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()

    class _DB:
        async def get(self, model, ident):
            # Camera hidden from the review feed.
            return SimpleNamespace(id=owned, exclude_from_review=True)

        async def execute(self, stmt):
            s = str(stmt).lower()
            if "user_camera_access" in s:
                return _FakeResult([(owned,)])
            # If motion rows were ever queried it'd be a bug: exclusion short-
            # circuits before any motion read.
            raise AssertionError("excluded camera must not query motion samples")

    got = await cameras_mod.camera_motion_review_items(
        camera_id=owned, from_=T0, to=_sec(3600), current_user=_user(), db=_DB()
    )
    assert got["items"] == []
    assert got["count"] == 0


@pytest.mark.asyncio
async def test_review_items_rejects_inverted_window():
    import services.api.routes.cameras as cameras_mod

    owned = uuid.uuid4()

    class _DB:
        async def get(self, model, ident):
            return SimpleNamespace(id=owned, exclude_from_review=False)

        async def execute(self, stmt):
            return _FakeResult([(owned,)])

    with pytest.raises(HTTPException) as exc:
        await cameras_mod.camera_motion_review_items(
            camera_id=owned, from_=_sec(3600), to=T0, current_user=_user(), db=_DB()
        )
    assert exc.value.status_code == 422
