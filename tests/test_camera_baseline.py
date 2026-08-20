"""Unit tests for the per-camera activity baseline (G2, issue #129).

The baseline answers "what does this camera normally see at this time of day"
so the anomaly lens has something to compare a frame against. These cover the
pure shaping; the query path is exercised against postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.perception import baseline as bl


def _sig(labels=None, known=None, unknown=0):
    objects = {"objects": [{"label": lab} for lab, n in (labels or {}).items() for _ in range(n)]}
    faces = {"faces": [{"person_name": n} for n in (known or [])] + [{} for _ in range(unknown)]}
    return objects, faces


# ---- signature extraction ----------------------------------------------


def test_signature_counts_labels_and_splits_faces():
    objects, faces = _sig({"person": 2, "car": 1}, known=["Mom"], unknown=2)
    sig = bl.observation_signature(objects, faces)
    assert sig["labels"] == {"person": 2, "car": 1}
    assert sig["known_faces"] == ["Mom"]
    assert sig["unknown_faces"] == 2


def test_signature_tolerates_missing_and_malformed_blobs():
    assert bl.observation_signature(None, None) == {
        "labels": {}, "known_faces": [], "unknown_faces": 0
    }
    assert bl.observation_signature({"objects": None}, {"faces": None})["labels"] == {}
    # An object with no label contributes nothing rather than raising.
    assert bl.observation_signature({"objects": [{}]}, {})["labels"] == {}


# ---- aggregation -------------------------------------------------------


def test_too_few_samples_produce_no_baseline():
    sigs = [bl.observation_signature(*_sig({"person": 1})) for _ in range(bl.MIN_SAMPLES - 1)]
    assert bl.summarize_baseline(sigs) is None


def test_baseline_reports_presence_rate_and_typical_count():
    # 20 frames: person in all of them (2 each), car in 5 of them (1 each).
    sigs = [bl.observation_signature(*_sig({"person": 2})) for _ in range(15)]
    sigs += [bl.observation_signature(*_sig({"person": 2, "car": 1})) for _ in range(5)]
    out = bl.summarize_baseline(sigs)
    assert out["samples"] == 20
    by_label = {e["label"]: e for e in out["labels"]}
    assert by_label["person"]["presence_rate"] == 1.0
    assert by_label["person"]["typical_count"] == 2
    assert by_label["car"]["presence_rate"] == 0.25
    # Most-present label leads.
    assert out["labels"][0]["label"] == "person"


def test_baseline_ranks_faces_and_measures_the_unknown_rate():
    sigs = [bl.observation_signature(*_sig({"person": 1}, known=["Mom"])) for _ in range(10)]
    sigs += [bl.observation_signature(*_sig({"person": 1}, known=["Dad"])) for _ in range(3)]
    sigs += [bl.observation_signature(*_sig({"person": 1}, unknown=1)) for _ in range(2)]
    out = bl.summarize_baseline(sigs)
    assert out["known_faces"][:2] == ["Mom", "Dad"]
    assert round(out["unknown_face_rate"], 3) == round(2 / 15, 3)


def test_baseline_caps_the_labels_it_shows():
    many = {f"label{i}": 1 for i in range(10)}
    sigs = [bl.observation_signature(*_sig(many)) for _ in range(bl.MIN_SAMPLES)]
    assert len(bl.summarize_baseline(sigs)["labels"]) == bl.MAX_LABELS_SHOWN


# ---- rendering ---------------------------------------------------------


def test_no_baseline_renders_no_context_at_all():
    current = bl.observation_signature(*_sig({"person": 1}))
    assert bl.format_baseline_context(None, current) is None


def test_context_states_normal_then_this_frame():
    sigs = [bl.observation_signature(*_sig({"person": 2}, known=["Mom"])) for _ in range(20)]
    baseline = bl.summarize_baseline(sigs)
    current = bl.observation_signature(*_sig({"person": 1}, unknown=1))
    text = bl.format_baseline_context(baseline, current)
    assert "NORMAL FOR THIS CAMERA" in text
    assert "person (typically 2, present in 100% of frames)" in text
    assert "Faces normally seen here: Mom" in text
    assert "Unrecognized faces appear in 0% of frames here." in text
    assert "This frame: person 1." in text
    assert "1 unrecognized face." in text


def test_context_describes_an_empty_frame_honestly():
    sigs = [bl.observation_signature(*_sig({"car": 1})) for _ in range(20)]
    baseline = bl.summarize_baseline(sigs)
    text = bl.format_baseline_context(baseline, bl.observation_signature(None, None))
    assert "This frame: nothing detected." in text


def test_context_names_recognized_people_in_the_current_frame():
    sigs = [bl.observation_signature(*_sig({"person": 1})) for _ in range(20)]
    baseline = bl.summarize_baseline(sigs)
    current = bl.observation_signature(*_sig({"person": 1}, known=["Dad", "Dad"]))
    text = bl.format_baseline_context(baseline, current)
    assert "Recognized: Dad." in text


# ---- bucketing ---------------------------------------------------------


def _at(day: str, hour: int) -> datetime:
    # 2026-08-17 is a Monday, 2026-08-22 a Saturday.
    base = {"mon": 17, "sat": 22}[day]
    return datetime(2026, 8, base, hour, 30, tzinfo=timezone.utc)


def test_bucket_matches_neighbouring_hours_on_the_same_kind_of_day():
    assert bl._in_bucket(_at("mon", 14), 14, is_weekend=False)
    assert bl._in_bucket(_at("mon", 15), 14, is_weekend=False)
    assert bl._in_bucket(_at("mon", 13), 14, is_weekend=False)
    assert not bl._in_bucket(_at("mon", 16), 14, is_weekend=False)


def test_bucket_separates_weekdays_from_weekends():
    assert not bl._in_bucket(_at("sat", 14), 14, is_weekend=False)
    assert bl._in_bucket(_at("sat", 14), 14, is_weekend=True)


def test_bucket_hour_distance_wraps_around_midnight():
    assert bl._in_bucket(_at("mon", 23), 0, is_weekend=False)
    assert bl._in_bucket(_at("mon", 1), 0, is_weekend=False)
    assert not bl._in_bucket(_at("mon", 22), 0, is_weekend=False)


def test_bucket_key_is_stable_across_equivalent_timestamps():
    utc = datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)
    other_tz = utc.astimezone(timezone(timedelta(hours=5)))
    assert bl._bucket_key("cam", utc) == bl._bucket_key("cam", other_tz)


# ---- query path --------------------------------------------------------


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    async def execute(self, stmt):
        self.queries += 1

        class _R:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return list(self._rows)

        return _R(self.rows)


def _row(obs_id, when, labels=None, known=None, unknown=0):
    objects, faces = _sig(labels or {"person": 1}, known, unknown)
    return (obs_id, when, objects, faces)


@pytest.mark.asyncio
async def test_camera_baseline_filters_to_the_bucket_and_caches():
    bl.clear_cache()
    ts = _at("mon", 14)
    rows = [_row(i, _at("mon", 14)) for i in range(20)]
    rows += [_row(100 + i, _at("mon", 20)) for i in range(20)]  # wrong hour
    rows += [_row(200 + i, _at("sat", 14)) for i in range(20)]  # wrong day kind
    db = _FakeDB(rows)

    out = await bl.camera_baseline(db, "cam-1", ts)
    assert out["samples"] == 20
    assert db.queries == 1

    # Second lookup in the same bucket is served from cache.
    await bl.camera_baseline(db, "cam-1", ts)
    assert db.queries == 1


@pytest.mark.asyncio
async def test_camera_baseline_excludes_the_observation_being_judged():
    bl.clear_cache()
    ts = _at("mon", 14)
    rows = [_row(i, _at("mon", 14)) for i in range(bl.MIN_SAMPLES)]
    db = _FakeDB(rows)
    # Dropping one sample takes it below the floor, which proves exclusion.
    assert await bl.camera_baseline(db, "cam-x", ts, exclude_id=0) is None


@pytest.mark.asyncio
async def test_anomaly_context_returns_none_on_a_thin_camera():
    bl.clear_cache()
    db = _FakeDB([_row(1, _at("mon", 14))])
    out = await bl.anomaly_context(db, "cam-2", _at("mon", 14), None, None)
    assert out is None


@pytest.mark.asyncio
async def test_anomaly_context_never_raises():
    class _Boom:
        async def execute(self, stmt):
            raise RuntimeError("db is down")

    bl.clear_cache()
    assert await bl.anomaly_context(_Boom(), "cam-3", _at("mon", 14), None, None) is None
