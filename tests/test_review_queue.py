"""Review queue prioritization for incidents (#296)."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from services.api.routes.review import _incident_review_reason
from services.api.routes.review import _summarize_cluster_samples


def _incident(*, kind="person", count=1):
    return SimpleNamespace(id=uuid4(), signature_kind=kind, occurrence_count=count)


def test_plain_open_person_incident_is_history():
    incident = _incident()
    needs_review, reason = _incident_review_reason(incident, set())
    assert not needs_review
    assert reason == "Recorded camera activity"


def test_rule_fired_incident_needs_review():
    incident = _incident()
    needs_review, reason = _incident_review_reason(incident, {str(incident.id)})
    assert needs_review
    assert reason == "A rule fired for this incident"


def test_unknown_subject_incident_needs_review_with_reason():
    incident = _incident(kind="unknown", count=3)
    needs_review, reason = _incident_review_reason(incident, set())
    assert needs_review
    assert reason == "Unknown subject seen 3 times"


def test_assigned_workflow_can_keep_all_open_incidents_actionable():
    incident = _incident()
    incident.status = "open"
    needs_review, reason = _incident_review_reason(incident, set(), True)
    assert needs_review
    assert reason == "Open incident in the assigned-workflow mode"


def test_cluster_recurrence_uses_distinct_days_not_raw_frame_count():
    cluster_id = uuid4()
    camera_id = uuid4()
    rows = [
        SimpleNamespace(id=uuid4(), cluster_id=cluster_id, camera_id=camera_id,
                        captured_at=datetime(2026, 9, 1, 8), thumbnail_path="a.jpg"),
        SimpleNamespace(id=uuid4(), cluster_id=cluster_id, camera_id=camera_id,
                        captured_at=datetime(2026, 9, 1, 8, 0, 5), thumbnail_path="b.jpg"),
        SimpleNamespace(id=uuid4(), cluster_id=cluster_id, camera_id=camera_id,
                        captured_at=datetime(2026, 9, 3, 8), thumbnail_path="c.jpg"),
        SimpleNamespace(id=uuid4(), cluster_id=cluster_id, camera_id=camera_id,
                        captured_at=datetime(2026, 9, 5, 8), thumbnail_path="d.jpg"),
    ]
    summary = _summarize_cluster_samples(rows)[str(cluster_id)]
    assert summary["sample_count"] == 4
    assert summary["distinct_days"] == 3
    assert summary["days"] == ["2026-09-01", "2026-09-03", "2026-09-05"]
