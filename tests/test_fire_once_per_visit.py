"""fire_once_per: "visit" dedup. A rule alerts once per continuous
presence of a subject (object track), not on every keyframe.
"""

import asyncio

from tests._engine_helpers import FakeRule, install_engine


def _obs(track_ids, label="person"):
    return {
        "camera_id": "cam-1",
        "object_detections": {
            "objects": [
                {"label": label, "confidence": 0.9, "bbox": [0, 0, 10, 10], "tracker_id": t}
                for t in track_ids
            ],
            "count": len(track_ids),
        },
        "tracks": [
            {"track_id": t, "label": label, "bbox": [0, 0, 10, 10],
             "prev_bbox": None, "state": "moving"}
            for t in track_ids
        ],
    }


def _run(eng, data):
    asyncio.run(eng.evaluate(data))


def test_visit_fires_once_while_subject_present(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "fire_once_per": "visit"},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _run(eng, _obs([1]))  # arrives -> fire
    _run(eng, _obs([1]))  # still here -> no fire
    _run(eng, _obs([1]))  # still here -> no fire
    assert rec.call_count == 1


def test_visit_refires_for_new_subject(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "fire_once_per": "visit"},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _run(eng, _obs([1]))           # person 1 -> fire
    _run(eng, _obs([1]))           # still -> no fire
    _run(eng, _obs([1, 2]))        # person 2 joins -> fire (new subject)
    assert rec.call_count == 2


def test_visit_refires_after_subject_leaves_and_returns(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "fire_once_per": "visit"},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _run(eng, _obs([1]))   # fire
    _run(eng, _obs([]))    # left (no tracks) -> dedup state pruned, no fire
    _run(eng, _obs([1]))   # returns as a fresh visit -> fire
    assert rec.call_count == 2


def test_without_visit_fires_every_frame(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person"},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _run(eng, _obs([1]))
    _run(eng, _obs([1]))
    _run(eng, _obs([1]))
    assert rec.call_count == 3


def test_visit_falls_back_to_fire_when_no_tracks(monkeypatch):
    # Audio trigger: no tracks to key on, so visit dedup is a no-op and
    # cooldown remains the right tool.
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "audio_event", "label": "baby_cry", "fire_once_per": "visit"},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    ev = {"camera_id": "cam-1", "audio_event": {"label": "baby_cry", "score": 0.8}}
    _run(eng, ev)
    _run(eng, ev)
    assert rec.call_count == 2
