"""Stable person-reference resolution before deletion (#285)."""

import asyncio
import uuid
from types import SimpleNamespace

from services.api.routes import persons
from shared.models import ExpectedActivity, Rule


def _run(coro):
    return asyncio.run(coro)


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    async def get(self, model, ident):
        return self.rows.get((model, ident))

    async def commit(self):
        self.commits += 1


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role="admin", is_active=True)


def test_reassigns_expected_activity_to_stable_target():
    source_id, target_id, expected_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source = SimpleNamespace(id=source_id, display_name="Old name")
    target = SimpleNamespace(id=target_id, display_name="New name")
    expected = SimpleNamespace(
        id=expected_id,
        subject_person_id=source_id,
        subject_key="Old name",
        name="Arrives home",
        enabled=True,
    )
    db = _DB({
        (persons.Person, source_id): source,
        (persons.Person, target_id): target,
        (ExpectedActivity, expected_id): expected,
    })

    result = _run(persons.resolve_person_reference(
        source_id,
        "expectation",
        expected_id,
        persons.ResolvePersonReferenceBody(action="reassign", target_person_id=target_id),
        _admin(),
        db,
    ))

    assert expected.subject_person_id == target_id
    assert expected.subject_key == "New name"
    assert result["action"] == "reassign"
    assert db.commits == 1


def test_disabling_rule_keeps_reference_but_stops_execution():
    source_id, rule_id = uuid.uuid4(), uuid.uuid4()
    source = SimpleNamespace(id=source_id, display_name="Simon")
    rule = SimpleNamespace(
        id=rule_id,
        name="Simon at the door",
        enabled=True,
        trigger_pattern={"person_id": str(source_id)},
        conditions=None,
        actions=[],
    )
    db = _DB({(persons.Person, source_id): source, (Rule, rule_id): rule})

    _run(persons.resolve_person_reference(
        source_id,
        "rule",
        rule_id,
        persons.ResolvePersonReferenceBody(action="disable"),
        _admin(),
        db,
    ))

    assert rule.enabled is False
    assert rule.trigger_pattern["person_id"] == str(source_id)
