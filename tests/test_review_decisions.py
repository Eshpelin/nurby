from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import uuid4

from services.api.routes.review import RelationshipDecisionBody


def test_relationship_decision_schema_supports_reversible_confirmed_lifecycle():
    assert RelationshipDecisionBody(decision="revoke").decision == "revoke"
    assert RelationshipDecisionBody(decision="restore").decision == "restore"
    assert RelationshipDecisionBody(decision="ambiguous").decision == "ambiguous"
    assert RelationshipDecisionBody(decision="archive").decision == "archive"


def test_relationship_decision_payload_does_not_require_a_note():
    body = RelationshipDecisionBody(decision="defer")
    assert body.note is None


def test_association_statuses_used_by_reversible_review_are_explicit():
    association = SimpleNamespace(id=uuid4(), status="established", user_confirmed=True)
    assert association.status == "established"
    assert association.user_confirmed is True


def test_decision_names_have_stable_idempotent_terminal_pairs():
    pairs = {
        "confirm": ("established", True),
        "reject": ("rejected", False),
            "defer": ("deferred", False),
            "ambiguous": ("ambiguous", False),
            "archive": ("archived", False),
            "revoke": ("archived", False),
        "restore": ("candidate", False),
    }
    assert set(pairs) == {"confirm", "reject", "defer", "ambiguous", "archive", "revoke", "restore"}


def test_decision_payload_can_carry_review_timestamp_for_stale_tab_detection():
    reviewed_at = datetime.now(timezone.utc)
    body = RelationshipDecisionBody(
        decision="confirm", expected_reviewed_at=reviewed_at
    )
    assert body.expected_reviewed_at == reviewed_at


def test_spoken_name_decision_can_carry_an_explicit_person_link():
    person_id = uuid4()
    body = RelationshipDecisionBody(decision="confirm", link_person_id=person_id)
    assert body.link_person_id == person_id


def test_spoken_name_decision_can_carry_an_explicit_visual_cluster_link():
    cluster_id = uuid4()
    body = RelationshipDecisionBody(
        decision="confirm", link_cluster_id=cluster_id, link_cluster_kind="body"
    )
    assert body.link_cluster_id == cluster_id
    assert body.link_cluster_kind == "body"


def test_cooccurrence_decision_can_link_each_endpoint_independently():
    subject_id, object_id = uuid4(), uuid4()
    body = RelationshipDecisionBody(
        decision="confirm",
        link_subject_person_id=subject_id,
        link_object_person_id=object_id,
    )
    assert body.link_subject_person_id == subject_id
    assert body.link_object_person_id == object_id


def test_cooccurrence_decision_can_link_anonymous_cluster_endpoints():
    subject_id, object_id = uuid4(), uuid4()
    body = RelationshipDecisionBody(
        decision="confirm",
        link_subject_cluster_id=subject_id,
        link_subject_cluster_kind="face",
        link_object_cluster_id=object_id,
        link_object_cluster_kind="body",
    )
    assert body.link_subject_cluster_kind == "face"
    assert body.link_object_cluster_kind == "body"


def test_review_event_supports_structured_reconciliation_metadata():
    from shared.models import AssociationReviewEvent

    event = AssociationReviewEvent(
        association_id=uuid4(),
        action="confirm",
        old_status="candidate",
        new_status="established",
        decision_metadata={
            "link_type": "cooccurrence_endpoints",
            "before": {"subject_kind": "face_cluster", "subject_key": "cluster-1"},
            "after": {"subject_kind": "person", "subject_key": str(uuid4())},
        },
    )
    assert event.decision_metadata["link_type"] == "cooccurrence_endpoints"
