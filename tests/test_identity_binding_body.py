"""Body-derived identity reaching the binder (issue #146).

Body re-identification confirms a cluster against a Person and stamps
person_id onto the detection. The binder used to ignore that and report
state="body", person_id=None: the system decided who this was, on
evidence, and then declined to use its own conclusion.

These tests pin both halves of the fix. The identity is used, and it stays
distinguishable from a face match rather than being flattened into one.
"""

import uuid

from services.perception.identity_binding import IdentityBinder

P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
CAM = "cam-1"
BOX = [0, 0, 100, 200]


def _track(tid, bbox=None, *, body=None, person_id=None, person_name=None, via=None):
    d = {"tracker_id": tid, "bbox": bbox or BOX, "label": "person"}
    if body:
        d["body_cluster_id"] = body
    if person_id:
        d["person_id"] = person_id
    if person_name:
        d["person_name"] = person_name
    if via:
        d["person_via"] = via
    return d


def _face(pid, bbox=None, name="Mum", dist=0.4):
    return {
        "person_id": pid,
        "person_name": name,
        "bbox": bbox or [10, 10, 30, 30],
        "match_distance": dist,
    }


# ---- the core regression -------------------------------------------------


def test_body_resolved_person_is_used():
    b = IdentityBinder()
    out = b.update(CAM, [
        _track(1, body="bc-1", person_id=P1, person_name="Mum", via="body")
    ], [])

    assert out[1]["state"] == "person"
    assert out[1]["person_id"] == P1
    assert out[1]["person_name"] == "Mum"
    assert out[1]["bound_by"] == "body"
    # The cluster is still reported: the identity claim and the appearance
    # match it rests on are both useful downstream.
    assert out[1]["body_cluster_id"] == "bc-1"


def test_body_cluster_without_a_person_is_still_only_a_body():
    """An unconfirmed cluster must not be promoted into an identity."""
    b = IdentityBinder()
    out = b.update(CAM, [_track(1, body="bc-2")], [])

    assert out[1]["state"] == "body"
    assert out[1]["person_id"] is None
    assert out[1]["bound_by"] == "body"


def test_person_via_face_on_the_detection_is_not_treated_as_body_derived():
    """reid stamps person_via="face" when a face drove the match. That is
    a face claim and must not be relabelled."""
    b = IdentityBinder()
    out = b.update(CAM, [
        _track(1, body="bc-1", person_id=P1, person_name="Mum", via="face")
    ], [])

    # No face was passed to the binder this frame, so there is no binding
    # to hold; the track is a body match with no identity of its own.
    assert out[1]["state"] == "body"
    assert out[1]["person_id"] is None


# ---- face stays authoritative -------------------------------------------


def test_face_binding_wins_over_a_conflicting_body_identity():
    b = IdentityBinder()
    out = b.update(
        CAM,
        [_track(1, body="bc-1", person_id=P2, person_name="Dad", via="body")],
        [_face(P1, name="Mum")],
    )

    assert out[1]["person_id"] == P1
    assert out[1]["person_name"] == "Mum"
    assert out[1]["bound_by"] == "face"


def test_body_identity_is_not_held_after_the_appearance_match_stops():
    """A face binding persists through occlusion. A body-derived one is
    recomputed every frame, so it disappears with the evidence instead of
    outliving it."""
    b = IdentityBinder()
    b.update(CAM, [
        _track(1, body="bc-1", person_id=P1, person_name="Mum", via="body")
    ], [])

    # Same track, no body match this frame.
    out = b.update(CAM, [_track(1)], [])

    assert out[1]["state"] == "unknown"
    assert out[1]["person_id"] is None
    assert b.identity_for(CAM, 1) is None


def test_held_face_binding_survives_a_frame_with_only_a_body_match():
    b = IdentityBinder()
    b.update(CAM, [_track(1, body="bc-1")], [_face(P1, name="Mum")])
    out = b.update(CAM, [_track(1, body="bc-1")], [])

    assert out[1]["person_id"] == P1
    assert out[1]["bound_by"] == "held"


# ---- bound_by vocabulary -------------------------------------------------


def test_bound_by_distinguishes_face_from_held():
    b = IdentityBinder()
    first = b.update(CAM, [_track(1)], [_face(P1)])
    second = b.update(CAM, [_track(1)], [])

    assert first[1]["bound_by"] == "face"
    assert second[1]["bound_by"] == "held"


def test_unknown_track_reports_no_rung():
    b = IdentityBinder()
    out = b.update(CAM, [_track(1)], [])
    assert out[1]["state"] == "unknown"
    assert out[1]["bound_by"] is None


def test_identity_for_reports_only_face_derived_bindings():
    b = IdentityBinder()
    b.update(CAM, [
        _track(1, body="bc-1", person_id=P1, person_name="Mum", via="body")
    ], [])
    assert b.identity_for(CAM, 1) is None

    b.update(CAM, [_track(2, bbox=[0, 0, 50, 50])], [_face(P2, bbox=[5, 5, 15, 15])])
    held = b.identity_for(CAM, 2)
    assert held is not None and held["bound_by"] == "held"


# ---- downstream: the signature sees the rung -----------------------------


def test_signature_carries_the_body_rung():
    """A body-derived person must reach the incident signature as that
    person, tagged with how we know it."""
    from services.perception.incident_tracker import compute_signature_detail

    pd = {
        "faces": [],
        "bodies": [{"bbox": BOX, "body_cluster_id": "bc-1"}],
        "tracks": [{
            "tracker_id": 1,
            "bbox": BOX,
            "person_id": P1,
            "person_name": "Mum",
            "body_cluster_id": "bc-1",
            "state": "person",
            "bound_by": "body",
        }],
    }
    assert compute_signature_detail(pd, None) == ("person", "Mum", "body")
