"""Unit tests for the face-recognition robustness fixes.

All pure, DB-free logic: centroid renormalization, quality gating, per-track
embedding pooling, face->track assignment, and the merge union-find.
"""

import numpy as np

from services.perception.faces import (
    CLUSTER_MAX_YAW_RATIO,
    MIN_DET_SCORE,
    MIN_FACE_PIXELS,
    FaceTrackPooler,
    _renorm,
    _viable_for_cluster,
    _viable_for_match,
    _yaw_ratio,
)
from services.perception.face_merger import _UnionFind
from services.perception.identity_binding import assign_tracker_ids


def _unit(vec):
    v = np.asarray(vec, dtype=float)
    return v / np.linalg.norm(v)


# --- _renorm -------------------------------------------------------------

def test_renorm_returns_unit_vector():
    out = _renorm(np.array([3.0, 4.0, 0.0]))
    assert np.isclose(np.linalg.norm(out), 1.0)


def test_renorm_handles_zero_vector():
    out = _renorm(np.zeros(4))
    assert np.allclose(out, 0.0)  # no divide-by-zero, returned as-is


def test_mean_of_unit_vectors_is_not_unit_without_renorm():
    # The bug this guards: averaging unit vectors shrinks the norm, distorting
    # L2 distance to the centroid.
    a, b = _unit([1, 0, 0]), _unit([0.8, 0.6, 0])
    raw_mean = (a + b) / 2
    assert np.linalg.norm(raw_mean) < 1.0
    assert np.isclose(np.linalg.norm(_renorm(raw_mean)), 1.0)


# --- _yaw_ratio ----------------------------------------------------------

def test_yaw_ratio_frontal_is_small():
    # eyes at x=0 and x=10, nose centered at x=5 -> offset 0.
    kps = [(0, 0), (10, 0), (5, 5), (2, 9), (8, 9)]
    assert _yaw_ratio(kps) == 0.0


def test_yaw_ratio_profile_is_large():
    # nose pushed toward the right eye -> large offset fraction.
    kps = [(0, 0), (10, 0), (9, 5), (2, 9), (8, 9)]
    assert _yaw_ratio(kps) > 0.3


def test_yaw_ratio_degenerate_eyes_returns_none():
    kps = [(5, 0), (5, 0), (5, 5), (2, 9), (8, 9)]  # eyes coincide
    assert _yaw_ratio(kps) is None


def test_yaw_ratio_missing_kps_returns_none():
    assert _yaw_ratio(None) is None


# --- quality gates -------------------------------------------------------

def test_viable_for_match_accepts_good_face():
    assert _viable_for_match({"detect_score": 0.9, "face_px": 120})


def test_viable_for_match_rejects_low_confidence():
    assert not _viable_for_match({"detect_score": MIN_DET_SCORE - 0.01, "face_px": 120})


def test_viable_for_match_rejects_tiny_face():
    assert not _viable_for_match({"detect_score": 0.9, "face_px": MIN_FACE_PIXELS - 1})


def test_viable_for_cluster_is_stricter_than_match():
    # A mediocre face that is matchable but not clean enough to seed a cluster.
    face = {"detect_score": 0.55, "face_px": 50, "yaw_ratio": 0.1}
    assert _viable_for_match(face)
    assert not _viable_for_cluster(face)


def test_viable_for_cluster_rejects_profile():
    face = {"detect_score": 0.9, "face_px": 120, "yaw_ratio": CLUSTER_MAX_YAW_RATIO + 0.1}
    assert not _viable_for_cluster(face)


def test_viable_for_cluster_accepts_clean_frontal():
    assert _viable_for_cluster({"detect_score": 0.9, "face_px": 120, "yaw_ratio": 0.05})


# --- FaceTrackPooler -----------------------------------------------------

def test_pool_returns_unit_embedding():
    pooler = FaceTrackPooler()
    out = pooler.pool(1, _unit([1, 2, 3]), now=0.0)
    assert np.isclose(np.linalg.norm(out), 1.0)


def test_pool_averages_same_track():
    pooler = FaceTrackPooler()
    a, b = _unit([1, 0, 0]), _unit([0, 1, 0])
    pooler.pool(7, a, now=0.0)
    pooled = np.asarray(pooler.pool(7, b, now=1.0))
    expected = _renorm((a + b) / 2)
    assert np.allclose(pooled, expected)


def test_pool_noisy_frame_barely_moves_established_track():
    pooler = FaceTrackPooler()
    base = _unit([1, 0, 0])
    for t in range(8):
        pooler.pool(3, base, now=float(t))
    noisy = _unit([0, 1, 0])
    pooled = np.asarray(pooler.pool(3, noisy, now=8.0))
    # One outlier frame should not flip a well-established track.
    assert float(np.dot(pooled, base)) > 0.9


def test_pool_expires_stale_track():
    pooler = FaceTrackPooler(ttl=10.0)
    pooler.pool(5, _unit([1, 0, 0]), now=0.0)
    assert 5 in pooler._state
    # A later pool for a different track past the ttl evicts the stale one.
    pooler.pool(6, _unit([0, 1, 0]), now=100.0)
    assert 5 not in pooler._state


def test_pool_caps_track_influence():
    pooler = FaceTrackPooler(max_samples=4)
    for t in range(50):
        pooler.pool(2, _unit([1, 0, 0]), now=float(t))
    assert pooler._state[2]["n"] <= 4


# --- assign_tracker_ids --------------------------------------------------

def test_assign_tracker_ids_stamps_containing_track():
    tracks = [{"tracker_id": 11, "bbox": [0, 0, 100, 200]}]
    faces = [{"bbox": [40, 20, 60, 50]}]  # centre inside the track box
    assign_tracker_ids(tracks, faces)
    assert faces[0]["tracker_id"] == 11


def test_assign_tracker_ids_picks_tightest_box():
    tracks = [
        {"tracker_id": 1, "bbox": [0, 0, 200, 400]},   # big
        {"tracker_id": 2, "bbox": [30, 10, 80, 90]},   # small, also contains face
    ]
    faces = [{"bbox": [40, 20, 60, 50]}]
    assign_tracker_ids(tracks, faces)
    assert faces[0]["tracker_id"] == 2


def test_assign_tracker_ids_leaves_unset_when_no_containment():
    tracks = [{"tracker_id": 9, "bbox": [0, 0, 10, 10]}]
    faces = [{"bbox": [500, 500, 520, 540]}]
    assign_tracker_ids(tracks, faces)
    assert "tracker_id" not in faces[0]


# --- merge union-find ----------------------------------------------------

def test_unionfind_groups_transitively():
    uf = _UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")
    groups = uf.groups()
    assert len(groups) == 1
    assert set(groups[0]) == {"a", "b", "c"}


def test_unionfind_no_groups_when_disjoint():
    uf = _UnionFind(["a", "b", "c"])
    assert uf.groups() == []
