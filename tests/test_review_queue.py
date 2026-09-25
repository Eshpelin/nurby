"""Review queue prioritization for incidents (#296)."""

from types import SimpleNamespace
from uuid import uuid4

from services.api.routes.review import _incident_review_reason


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
