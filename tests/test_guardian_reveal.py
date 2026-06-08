"""Tests for guardian dependant face reveal selection."""

import uuid

from services.guardian.reveal import (
    DEFAULT_REVEAL_REF_DISTANCE,
    confidence_to_max_distance,
    reveal_box_for,
)

DEP = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def _det(faces):
    return {"faces": faces, "count": len(faces)}


def test_confidence_maps_monotonically():
    # confidence 0 -> reveal any positive match (ref distance), 1 -> nothing.
    assert confidence_to_max_distance(0.0) == DEFAULT_REVEAL_REF_DISTANCE
    assert confidence_to_max_distance(1.0) == 0.0
    mid = confidence_to_max_distance(0.5)
    assert 0.0 < mid < DEFAULT_REVEAL_REF_DISTANCE
    # clamps out-of-range floors
    assert confidence_to_max_distance(-1.0) == DEFAULT_REVEAL_REF_DISTANCE
    assert confidence_to_max_distance(2.0) == 0.0


def test_reveals_dependant_face_under_distance():
    det = _det([{"person_id": DEP, "bbox": [10, 20, 50, 80], "match_distance": 0.4}])
    assert reveal_box_for(det, DEP, max_distance=0.9) == (10, 20, 50, 80)


def test_does_not_reveal_when_distance_too_large():
    det = _det([{"person_id": DEP, "bbox": [10, 20, 50, 80], "match_distance": 1.0}])
    assert reveal_box_for(det, DEP, max_distance=0.9) is None


def test_never_reveals_other_person():
    det = _det([{"person_id": OTHER, "bbox": [10, 20, 50, 80], "match_distance": 0.1}])
    assert reveal_box_for(det, DEP, max_distance=0.9) is None


def test_picks_closest_match_among_multiple_dependant_faces():
    det = _det(
        [
            {"person_id": DEP, "bbox": [0, 0, 10, 10], "match_distance": 0.8},
            {"person_id": DEP, "bbox": [90, 90, 99, 99], "match_distance": 0.3},
        ]
    )
    assert reveal_box_for(det, DEP, max_distance=0.9) == (90, 90, 99, 99)


def test_fails_safe_on_missing_or_malformed():
    assert reveal_box_for(None, DEP, 0.9) is None
    assert reveal_box_for({}, DEP, 0.9) is None
    assert reveal_box_for(_det([]), DEP, 0.9) is None
    # unmatched (person_id None) face is never revealed
    assert reveal_box_for(_det([{"person_id": None, "bbox": [1, 2, 3, 4], "match_distance": 0.1}]), DEP, 0.9) is None
    # missing distance is not a match
    assert reveal_box_for(_det([{"person_id": DEP, "bbox": [1, 2, 3, 4]}]), DEP, 0.9) is None
    # degenerate bbox rejected
    assert reveal_box_for(_det([{"person_id": DEP, "bbox": [5, 5, 5, 5], "match_distance": 0.1}]), DEP, 0.9) is None
