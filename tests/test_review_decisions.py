from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import uuid4

from services.api.routes.review import RelationshipDecisionBody


def test_relationship_decision_schema_supports_reversible_confirmed_lifecycle():
    assert RelationshipDecisionBody(decision="revoke").decision == "revoke"
    assert RelationshipDecisionBody(decision="restore").decision == "restore"


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
        "revoke": ("archived", False),
        "restore": ("candidate", False),
    }
    assert set(pairs) == {"confirm", "reject", "defer", "revoke", "restore"}


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
