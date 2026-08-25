"""Cross-camera identity hand-off (issue #147).

A tracker_id is meaningless on the camera someone just walked onto, so a
subject arriving in the kitchen used to start from nothing and wait for a
fresh face. Their body cluster, however, is cross-camera by construction.
These tests pin the hand-off keyed on it, and the two rules that stop it
from letting a wrong identity live forever.
"""

import asyncio
import time
import uuid

from services.perception import identity_handoff
from services.perception.identity_binding import IdentityBinder, writes_for
from tests._engine_helpers import FakeRedis

P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
HALL = "cam-hall"
KITCHEN = "cam-kitchen"
BOX = [0, 0, 100, 200]


def _run(coro):
    return asyncio.run(coro)


def _track(tid, *, body=None, person_id=None, person_name=None, via=None):
    d = {"tracker_id": tid, "bbox": BOX, "label": "person"}
    if body:
        d["body_cluster_id"] = body
    if person_id:
        d["person_id"] = person_id
    if person_name:
        d["person_name"] = person_name
    if via:
        d["person_via"] = via
    return d


def _face(pid, name="Mum", dist=0.4):
    return {
        "person_id": pid,
        "person_name": name,
        "bbox": [10, 10, 30, 30],
        "match_distance": dist,
    }


# ---- the walk from one camera to the next --------------------------------


def test_identity_follows_a_subject_to_the_next_camera():
    redis = FakeRedis()
    binder = IdentityBinder()

    # Hallway: a face lands, so the track is bound and published.
    hall = binder.update(HALL, [_track(1, body="bc-1")], [_face(P1)])
    _run(identity_handoff.publish(redis, writes_for(hall)))

    # Kitchen: different camera, different tracker_id, no face at all.
    handoff = _run(identity_handoff.lookup(redis, ["bc-1"]))
    kitchen = binder.update(KITCHEN, [_track(77, body="bc-1")], [], handoff=handoff)

    assert kitchen[77]["state"] == "person"
    assert kitchen[77]["person_id"] == P1
    assert kitchen[77]["person_name"] == "Mum"
    assert kitchen[77]["bound_by"] == "handoff"


def test_without_the_handoff_the_next_camera_knows_nothing():
    """The regression this fixes, stated directly."""
    binder = IdentityBinder()
    binder.update(HALL, [_track(1, body="bc-1")], [_face(P1)])

    kitchen = binder.update(KITCHEN, [_track(77, body="bc-1")], [])

    assert kitchen[77]["state"] == "body"
    assert kitchen[77]["person_id"] is None


def test_handoff_survives_a_binder_restart():
    """Redis holds it, so a perception restart does not blank the house."""
    redis = FakeRedis()
    before = IdentityBinder()
    hall = before.update(HALL, [_track(1, body="bc-1")], [_face(P1)])
    _run(identity_handoff.publish(redis, writes_for(hall)))

    after = IdentityBinder()  # fresh process, empty in-memory state
    handoff = _run(identity_handoff.lookup(redis, ["bc-1"]))
    out = after.update(HALL, [_track(1, body="bc-1")], [], handoff=handoff)

    assert out[1]["person_id"] == P1
    assert out[1]["bound_by"] == "handoff"


# ---- a recovered identity must not refresh itself ------------------------


def test_a_handoff_binding_is_never_republished():
    """If a lookup could write itself back, the TTL would never fire and a
    wrong identity would become permanent."""
    redis = FakeRedis()
    binder = IdentityBinder()

    handoff = {"bc-1": {"person_id": P1, "person_name": "Mum"}}
    out = binder.update(KITCHEN, [_track(5, body="bc-1")], [], handoff=handoff)

    assert out[5]["bound_by"] == "handoff"
    assert writes_for(out) == {}
    assert _run(identity_handoff.publish(redis, writes_for(out))) == 0


def test_body_derived_bindings_are_not_published_either():
    binder = IdentityBinder()
    out = binder.update(
        KITCHEN,
        [_track(5, body="bc-1", person_id=P1, person_name="Mum", via="body")],
        [],
    )
    assert out[5]["bound_by"] == "body"
    assert writes_for(out) == {}


def test_face_and_held_bindings_are_published():
    binder = IdentityBinder()
    fresh = binder.update(HALL, [_track(1, body="bc-1")], [_face(P1)])
    held = binder.update(HALL, [_track(1, body="bc-1")], [])

    assert writes_for(fresh) == {"bc-1": {"person_id": P1, "person_name": "Mum"}}
    assert writes_for(held) == {"bc-1": {"person_id": P1, "person_name": "Mum"}}


def test_a_face_binding_without_a_body_cluster_publishes_nothing():
    """There is no cross-camera key to publish under."""
    binder = IdentityBinder()
    out = binder.update(HALL, [_track(1)], [_face(P1)])
    assert out[1]["person_id"] == P1
    assert writes_for(out) == {}


# ---- precedence ----------------------------------------------------------


def test_local_face_binding_beats_a_conflicting_handoff():
    binder = IdentityBinder()
    handoff = {"bc-1": {"person_id": P2, "person_name": "Dad"}}
    out = binder.update(
        HALL, [_track(1, body="bc-1")], [_face(P1, name="Mum")], handoff=handoff
    )

    assert out[1]["person_id"] == P1
    assert out[1]["bound_by"] == "face"


def test_reid_confirmed_identity_beats_a_conflicting_handoff():
    """reid's cluster link is a deliberate face-confirmed record; the
    hand-off is a recent binding still inside its TTL."""
    binder = IdentityBinder()
    handoff = {"bc-1": {"person_id": P2, "person_name": "Dad"}}
    out = binder.update(
        KITCHEN,
        [_track(1, body="bc-1", person_id=P1, person_name="Mum", via="body")],
        [],
        handoff=handoff,
    )

    assert out[1]["person_id"] == P1
    assert out[1]["bound_by"] == "body"


def test_handoff_for_a_different_cluster_is_ignored():
    binder = IdentityBinder()
    handoff = {"bc-other": {"person_id": P1, "person_name": "Mum"}}
    out = binder.update(KITCHEN, [_track(1, body="bc-1")], [], handoff=handoff)

    assert out[1]["state"] == "body"
    assert out[1]["person_id"] is None


def test_a_track_with_no_body_cluster_cannot_be_handed_off():
    binder = IdentityBinder()
    handoff = {"bc-1": {"person_id": P1, "person_name": "Mum"}}
    out = binder.update(KITCHEN, [_track(1)], [], handoff=handoff)

    assert out[1]["state"] == "unknown"


# ---- expiry --------------------------------------------------------------


def test_the_entry_expires_so_a_stale_identity_cannot_be_inherited():
    redis = FakeRedis()
    _run(identity_handoff.publish(
        redis, {"bc-1": {"person_id": P1, "person_name": "Mum"}}, ttl=60
    ))
    assert _run(identity_handoff.lookup(redis, ["bc-1"]))

    # Fast-forward past the TTL.
    redis._expires[identity_handoff._key("bc-1")] = time.time() - 1

    assert _run(identity_handoff.lookup(redis, ["bc-1"])) == {}


def test_ttl_matches_the_journey_idle_window():
    """A hand-off older than the gap that would have ended the journey is
    not the same visit and must not be carried onto a new one."""
    from services.perception.journey_tracker import JOURNEY_IDLE_SECONDS_DEFAULT

    assert identity_handoff.DEFAULT_TTL_SECONDS == JOURNEY_IDLE_SECONDS_DEFAULT


# ---- redis failures never cost a keyframe --------------------------------


def test_lookup_failure_is_swallowed():
    assert _run(identity_handoff.lookup(FakeRedis(fail_mode="get"), ["bc-1"])) == {}


def test_publish_failure_is_swallowed():
    written = _run(identity_handoff.publish(
        FakeRedis(fail_mode="set"), {"bc-1": {"person_id": P1}}
    ))
    assert written == 0


def test_no_redis_at_all_is_survivable():
    assert _run(identity_handoff.lookup(None, ["bc-1"])) == {}
    assert _run(identity_handoff.publish(None, {"bc-1": {"person_id": P1}})) == 0


def test_empty_inputs():
    redis = FakeRedis()
    assert _run(identity_handoff.lookup(redis, [])) == {}
    assert _run(identity_handoff.lookup(redis, None)) == {}
    assert _run(identity_handoff.publish(redis, {})) == 0


def test_entries_without_a_person_are_not_written():
    redis = FakeRedis()
    assert _run(identity_handoff.publish(redis, {"bc-1": {"person_name": "Mum"}})) == 0
    assert _run(identity_handoff.lookup(redis, ["bc-1"])) == {}
