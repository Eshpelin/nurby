"""Coverage for services/digest/scheduler.py.

The scheduling gate (when is a camera's next digest due) lives inlined in
``run_digest_loop``; we test the equivalent arithmetic directly against
``PERIOD_HOURS`` plus ``_last_digest_time``, and we exercise the real
summary/highlights/stats shaping inside ``_generate_camera_digest`` with a
recording FakeDB. No real DB or network.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.digest import scheduler as digest_scheduler

# ── FakeDB modelling the queue of executes _generate_camera_digest issues ──
#
# _generate_camera_digest runs, in order:
#   1. count of observations in window           -> scalar()
#   2. person_detections rows                     -> iterated tuples
#   3. object_detections rows                     -> iterated tuples
#   4. (only if person ids) person name rows      -> iterated tuples
# then db.add(digest) + db.commit().


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _RowsResult:
    """Iterable of 1-tuples, matching ``for (col,) in result``."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.added = []
        self.committed = False

    async def execute(self, stmt):
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def _camera(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        name="Front Door",
        digest_period="24h",
        digest_enabled=True,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ── PERIOD_HOURS window mapping ────────────────────────────────────


def test_period_hours_table_is_complete():
    assert digest_scheduler.PERIOD_HOURS == {
        "1h": 1,
        "6h": 6,
        "12h": 12,
        "24h": 24,
        "48h": 48,
        "7d": 168,
    }


def test_period_hours_default_for_unknown_label():
    # run_digest_loop uses .get(period, 24); confirm the default behaviour.
    assert digest_scheduler.PERIOD_HOURS.get("nonsense", 24) == 24
    assert digest_scheduler.PERIOD_HOURS.get("7d", 24) == 168


# ── due-time gating arithmetic (mirrors run_digest_loop) ───────────


def _next_due(last_digest, period):
    hours = digest_scheduler.PERIOD_HOURS.get(period, 24)
    return last_digest + timedelta(hours=hours)


def test_not_due_before_interval_elapses():
    last = datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 11, 23, 0, tzinfo=timezone.utc)  # 23h < 24h
    assert now < _next_due(last, "24h")


def test_due_once_interval_elapses():
    last = datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 12, 0, 1, tzinfo=timezone.utc)  # 24h + 1m
    assert now >= _next_due(last, "24h")


def test_shorter_period_fires_sooner():
    last = datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 11, 1, 30, tzinfo=timezone.utc)
    assert now >= _next_due(last, "1h")  # 1h period already elapsed
    assert now < _next_due(last, "6h")  # 6h period not yet


@pytest.mark.asyncio
async def test_last_digest_time_returns_scalar():
    when = datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)
    db = _FakeDB([_ScalarResult(when)])
    got = await digest_scheduler._last_digest_time(db, uuid.uuid4())
    assert got == when


@pytest.mark.asyncio
async def test_last_digest_time_none_when_never_generated():
    db = _FakeDB([_ScalarResult(None)])
    assert await digest_scheduler._last_digest_time(db, uuid.uuid4()) is None


# ── _generate_camera_digest: empty window is a no-op ───────────────


@pytest.mark.asyncio
async def test_generate_skips_when_no_observations():
    cam = _camera()
    db = _FakeDB([_ScalarResult(0)])  # zero observations
    since = datetime(2026, 6, 11, tzinfo=timezone.utc)
    await digest_scheduler._generate_camera_digest(db, cam, since)
    # No digest row added, no commit, because there was nothing to digest.
    assert db.added == []
    assert db.committed is False


# ── _generate_camera_digest: full summary shaping ──────────────────


@pytest.mark.asyncio
async def test_generate_builds_summary_highlights_and_stats():
    cam = _camera(name="Driveway", digest_period="24h")
    pid1, pid2 = str(uuid.uuid4()), str(uuid.uuid4())

    person_rows = _RowsResult(
        [
            ({"persons": [{"person_id": pid1}, {"person_id": pid2}]},),
            ({"persons": [{"person_id": pid1}]},),  # repeat -> deduped to 2
        ]
    )
    object_rows = _RowsResult(
        [
            ({"detections": [{"label": "car"}, {"label": "car"}, {"label": "dog"}]},),
            ({"detections": [{"label": "truck"}, {"label": "person"}]},),
        ]
    )
    # Only pid1 resolves to a known person; pid2 has no row -> unknown face.
    name_rows = _RowsResult([("Salma Bekom", "Mommy")])

    db = _FakeDB(
        [
            _ScalarResult(42),  # total obs
            person_rows,
            object_rows,
            name_rows,
        ]
    )
    since = datetime(2026, 6, 11, tzinfo=timezone.utc)
    await digest_scheduler._generate_camera_digest(db, cam, since)

    assert db.committed is True
    assert len(db.added) == 1
    digest = db.added[0]

    assert digest.total_observations == 42
    assert digest.period == "24h"
    # Summary text mentions the count and the period.
    assert "42 observations in the last 24h" in digest.summary
    # Nickname is preferred over the canonical display_name.
    assert "Mommy" in digest.summary
    # 2 unique person ids, 1 named -> 1 unknown face reported.
    assert "1 unknown face(s)" in digest.summary
    # Top detections sorted by count: car (2) leads.
    assert "car (2)" in digest.summary

    # Highlights: recognized-people line + vehicle line (car+truck = 3).
    assert any("Recognized 1 known person" in h for h in digest.highlights)
    assert any("3 vehicle detection(s)" in h for h in digest.highlights)

    # Stats payload.
    assert digest.stats["total_observations"] == 42
    assert digest.stats["unique_persons"] == 2
    assert digest.stats["object_counts"]["car"] == 2
    assert digest.stats["object_counts"]["truck"] == 1


@pytest.mark.asyncio
async def test_generate_no_people_no_vehicle_highlights():
    """Objects with no car/truck and no persons -> highlights stays None."""
    cam = _camera(digest_period="6h")
    db = _FakeDB(
        [
            _ScalarResult(5),
            _RowsResult([]),  # no person_detections rows
            _RowsResult([({"detections": [{"label": "cat"}]},)]),
            # No name query because there are zero person ids.
        ]
    )
    since = datetime(2026, 6, 11, tzinfo=timezone.utc)
    await digest_scheduler._generate_camera_digest(db, cam, since)
    digest = db.added[0]
    assert digest.highlights is None
    assert "cat (1)" in digest.summary
    assert digest.stats["unique_persons"] == 0


@pytest.mark.asyncio
async def test_generate_ignores_malformed_detection_payloads():
    """Rows whose JSON isn't the expected dict shape are skipped, not crashed."""
    cam = _camera()
    db = _FakeDB(
        [
            _ScalarResult(3),
            _RowsResult(
                [
                    ("not a dict",),  # bad person payload
                    ({"no_persons_key": True},),
                    ({"persons": [{"person_id": None}]},),  # missing id -> skipped
                ]
            ),
            _RowsResult(
                [
                    (None,),  # bad object payload
                    ({"detections": [{}]},),  # label defaults to "unknown"
                ]
            ),
            # No name query: zero valid person ids.
        ]
    )
    since = datetime(2026, 6, 11, tzinfo=timezone.utc)
    await digest_scheduler._generate_camera_digest(db, cam, since)
    digest = db.added[0]
    assert digest.stats["unique_persons"] == 0
    assert digest.stats["object_counts"] == {"unknown": 1}
