"""fire_once_per: "incident" dedup. A rule fires at most once for the
lifetime of a given incident, keyed by incident id.

The perception pipeline assigns the incident in the same observation-insert
pass that runs before rule evaluation, and threads the incident id into
rule_data["incident_id"]. The engine keys its dedup on (rule_id, incident_id)
so a long cluster of repeat sightings of the same subject fires the rule once,
while a NEW incident id is a fresh subject/cluster and fires again. An
observation with no incident id (tracking off / motion-only) is not deduped,
leaving cooldown as the right tool there.
"""

import asyncio

from tests._engine_helpers import FakeRule, install_engine


def _obs(incident_id, track_ids=(1,), label="person"):
    """An object_detected observation carrying an incident id. track_ids
    default to a single subject so the trigger matches every call (the
    per-incident dedup, not the per-visit one, is what we are exercising)."""
    return {
        "camera_id": "cam-1",
        "incident_id": incident_id,
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


def _incident_rule():
    return FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected",
            "label": "person",
            "fire_once_per": "incident",
        },
        cooldown_seconds=0,
    )


def test_fires_once_within_one_incident(monkeypatch):
    # Condition is met on every keyframe of the same incident, but the rule
    # must fire exactly once for that incident.
    eng, rec = install_engine(monkeypatch, [_incident_rule()])
    _run(eng, _obs("inc-A"))  # first sighting -> fire
    _run(eng, _obs("inc-A"))  # same incident -> no fire
    _run(eng, _obs("inc-A"))  # same incident -> no fire
    assert rec.call_count == 1


def test_new_incident_fires_again(monkeypatch):
    # A new incident id is a fresh subject/cluster and re-arms the rule.
    eng, rec = install_engine(monkeypatch, [_incident_rule()])
    _run(eng, _obs("inc-A"))  # incident A -> fire
    _run(eng, _obs("inc-A"))  # still A -> no fire
    _run(eng, _obs("inc-B"))  # incident B -> fire again
    _run(eng, _obs("inc-B"))  # still B -> no fire
    assert rec.call_count == 2


def test_no_incident_id_falls_back_to_firing(monkeypatch):
    # Tracking off / motion-only: no incident id to key on, so per-incident
    # dedup is a no-op and the rule fires every matching frame (cooldown is
    # the right tool there instead).
    eng, rec = install_engine(monkeypatch, [_incident_rule()])
    _run(eng, _obs(None))
    _run(eng, _obs(None))
    assert rec.call_count == 2


def test_incident_dedup_is_per_rule(monkeypatch):
    # Two rules both set to fire-once-per-incident must each fire once for
    # the same incident; one rule firing does not suppress the other.
    r1 = _incident_rule()
    r2 = _incident_rule()
    eng, rec = install_engine(monkeypatch, [r1, r2])
    _run(eng, _obs("inc-A"))  # both fire
    _run(eng, _obs("inc-A"))  # neither fires
    assert rec.call_count == 2
