from types import SimpleNamespace
from uuid import uuid4

from services.api.routes.review import _scoped_evidence
from services.api.routes.review import _association_visible
from services.api.routes.review import _scoped_camera_histogram
from services.api.routes.review import _evidence_availability, _supporting_evidence_count
from services.api.routes.review import _scoped_observation_source_query
from sqlalchemy.dialects import postgresql


def test_evidence_availability_distinguishes_expired_and_partial_sources():
    assert _evidence_availability([]) == "none"
    assert _evidence_availability([{"source_status": "source_expired"}]) == "expired"
    assert _evidence_availability([{"source_status": "available"}, {"source_status": "source_changed"}]) == "partial"
    assert _evidence_availability([{"source_status": "available"}]) == "available"
from services.api.routes.review import _reconcile_observation_sources
from services.api.routes.review import _visible_cluster_camera_id
from shared.camera_access import ALL


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


def test_scoped_evidence_hides_episode_without_camera_provenance():
    row = _evidence(cameras=[])

    assert _scoped_evidence(row, {"camera-a"}) is None
    assert _scoped_evidence(row, None) is not None


def test_association_visibility_is_camera_scoped_before_queue_pagination():
    row = SimpleNamespace(camera_histogram={"camera-a": 2, "camera-b": 1})

    assert _association_visible(row, {"camera-a"}) is True
    assert _association_visible(row, {"camera-c"}) is False
    assert _association_visible(row, ALL) is True


def test_association_histogram_does_not_leak_restricted_cameras():
    row = SimpleNamespace(camera_histogram={"camera-a": 2, "camera-b": 7})

    assert _scoped_camera_histogram(row, {"camera-a"}) == {"camera-a": 2}
    assert _scoped_camera_histogram(row, ALL) == {"camera-a": 2, "camera-b": 7}


def test_review_cluster_camera_uses_visible_sample_not_first_camera():
    first_camera = uuid4()
    visible_camera = uuid4()
    cluster = SimpleNamespace(first_camera_id=first_camera)

    assert _visible_cluster_camera_id(
        cluster, {"camera_ids": [str(visible_camera)]}, {str(visible_camera)}
    ) == visible_camera
    assert _visible_cluster_camera_id(
        cluster, {"camera_ids": []}, {str(visible_camera)}
    ) is None
    assert _visible_cluster_camera_id(cluster, {"camera_ids": []}, ALL) == first_camera


def test_legacy_association_support_falls_back_to_evidence_count():
    row = SimpleNamespace(
        evidence_count=4,
        supporting_evidence_count=0,
        contradictory_evidence_count=0,
    )
    assert _supporting_evidence_count(row) == 4


def test_split_counters_remain_authoritative_when_contradictions_exist():
    row = SimpleNamespace(
        evidence_count=4,
        supporting_evidence_count=0,
        contradictory_evidence_count=2,
    )
    assert _supporting_evidence_count(row) == 0


def test_deleted_observation_sources_are_removed_from_review_evidence():
    row = _evidence(cameras=["camera-a"], observations=["keep", "deleted"])

    result = _reconcile_observation_sources(
        _scoped_evidence(row, {"camera-a"}), {"keep"}
    )

    assert result["observation_ids"] == ["keep"]
    assert result["observation_sources_available"] is True


def test_review_evidence_marks_all_deleted_observation_sources_unavailable():
    row = _evidence(cameras=["camera-a"], observations=["deleted"])

    result = _reconcile_observation_sources(
        _scoped_evidence(row, {"camera-a"}), set()
    )

    assert result["observation_ids"] == []
    assert result["observation_sources_available"] is False


def test_observation_source_lookup_rechecks_camera_scope_before_returning_ids():
    camera_id = str(uuid4())
    query = _scoped_observation_source_query({uuid4()}, {camera_id})
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()

    assert "observations.camera_id in" in sql
    assert "observations.id in" in sql


def test_unrestricted_observation_source_lookup_keeps_existing_behavior():
    query = _scoped_observation_source_query({uuid4()}, None)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()

    assert "observations.id in" in sql
    assert "observations.camera_id in" not in sql
