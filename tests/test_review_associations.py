from types import SimpleNamespace
from uuid import uuid4

from services.api.routes.review import _scoped_evidence


def _evidence(*, cameras, observations=None):
    return SimpleNamespace(
        id=uuid4(),
        episode_key="visit-1",
        evidence_kind="person_vehicle",
        role="supporting",
        journey_id=uuid4(),
        observation_ids=observations or [str(uuid4())],
        camera_ids=cameras,
        observed_at=None,
        score=0.8,
        explanation="Observed together",
        evidence_metadata={"transcript_id": str(uuid4()), "plate": "ABCDXYZ"},
    )


def test_scoped_evidence_keeps_source_pointers_when_all_cameras_are_visible():
    row = _evidence(cameras=["camera-a"])

    result = _scoped_evidence(row, {"camera-a"})

    assert result["fully_visible"] is True
    assert result["camera_ids"] == ["camera-a"]
    assert result["observation_ids"] == row.observation_ids
    assert result["transcript_id"] is not None


def test_scoped_evidence_redacts_mixed_episode_source_pointers():
    row = _evidence(cameras=["camera-a", "camera-b"])

    result = _scoped_evidence(row, {"camera-a"})

    assert result["fully_visible"] is False
    assert result["camera_ids"] == ["camera-a"]
    assert result["observation_ids"] == []
    assert result["journey_id"] is None
    assert result["transcript_id"] is None
    assert "transcript_id" not in result["metadata"]


def test_scoped_evidence_hides_episode_with_no_allowed_camera():
    row = _evidence(cameras=["camera-b"])

    assert _scoped_evidence(row, {"camera-a"}) is None
