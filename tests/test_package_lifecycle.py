from datetime import datetime, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace

import pytest

from services.perception.package_lifecycle import (
    PackageEvidence,
    PackageLifecycle,
    PackageState,
    RemovalKind,
    advance,
)
from services.perception.package_lifecycle_store import _known_person_id, _package_present
from services.perception.package_lifecycle_store import apply_package_check


BASE = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def test_observation_payload_helpers_are_conservative():
    assert _package_present({"objects": [{"label": "package"}]}) is True
    assert _package_present({"objects": [{"label": "person"}]}) is False
    person_id = uuid4()
    assert _known_person_id({"faces": [{"person_id": str(person_id)}]}) == person_id
    assert _known_person_id({"faces": [{"person_id": "not-a-uuid"}]}) is None


def test_delivery_becomes_waiting_and_resets_noise():
    state = advance(PackageLifecycle(), PackageEvidence(BASE, present=True))
    state = advance(state, PackageEvidence(BASE + timedelta(minutes=1), present=False))
    state = advance(state, PackageEvidence(BASE + timedelta(minutes=2), present=True))
    assert state.state == PackageState.WAITING
    assert state.absent_checks == 0


def test_one_absent_check_does_not_mark_package_gone():
    state = advance(PackageLifecycle(last_present_at=BASE), PackageEvidence(
        BASE + timedelta(minutes=5), present=False,
    ))
    assert state.state == PackageState.DELIVERED
    assert state.absent_checks == 1


def test_gone_requires_consecutive_checks_and_elapsed_time():
    state = PackageLifecycle(state=PackageState.WAITING, last_present_at=BASE)
    state = advance(state, PackageEvidence(BASE + timedelta(minutes=3), present=False))
    state = advance(state, PackageEvidence(BASE + timedelta(minutes=4), present=False))
    assert state.state == PackageState.GONE
    assert state.removal_kind == RemovalKind.REMOVED_UNOBSERVED


def test_known_remover_is_possible_pickup_evidence():
    person_id = uuid4()
    state = PackageLifecycle(state=PackageState.WAITING, last_present_at=BASE)
    state = advance(state, PackageEvidence(BASE + timedelta(minutes=3), present=False))
    state = advance(state, PackageEvidence(
        BASE + timedelta(minutes=4), present=False, remover_person_id=person_id,
    ))
    assert state.removal_kind == RemovalKind.PICKED_UP_BY_PERSON
    assert state.remover_person_id == person_id


def test_gone_state_is_terminal_and_does_not_reappear():
    state = PackageLifecycle(state=PackageState.GONE, gone_at=BASE)
    next_state = advance(state, PackageEvidence(BASE + timedelta(minutes=1), present=True))
    assert next_state == state


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        advance(PackageLifecycle(), PackageEvidence(datetime(2026, 9, 28), present=True))


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    async def flush(self):
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid4()

    def add(self, row):
        self.added.append(row)


@pytest.mark.asyncio
async def test_first_package_emits_one_info_notification():
    db = _Db(None, None)
    camera_id = uuid4()
    observation_id = uuid4()
    row = await apply_package_check(
        db,
        camera_id=camera_id,
        evidence=PackageEvidence(BASE, present=True, observation_id=observation_id),
    )
    notifications = [item for item in db.added if item.__class__.__name__ == "Notification"]
    assert row.state == PackageState.DELIVERED.value
    assert len(notifications) == 1
    assert notifications[0].severity == "info"
    assert notifications[0].observation_id == observation_id


@pytest.mark.asyncio
async def test_unobserved_removal_emits_warning_once():
    row = SimpleNamespace(
        id=uuid4(), camera_id=uuid4(), tracking_key="camera-default",
        state=PackageState.WAITING.value, started_at=BASE,
        last_present_at=BASE, absent_checks=1, gone_at=None,
        removal_kind=None, remover_person_id=None, last_observation_id=None,
        evidence=None, updated_at=BASE,
    )
    db = _Db(row, None)
    next_row = await apply_package_check(
        db,
        camera_id=row.camera_id,
        evidence=PackageEvidence(BASE + timedelta(minutes=4), present=False),
    )
    notifications = [item for item in db.added if item.__class__.__name__ == "Notification"]
    assert next_row.state == PackageState.GONE.value
    assert next_row.removal_kind == RemovalKind.REMOVED_UNOBSERVED.value
    assert len(notifications) == 1
    assert notifications[0].severity == "warning"


@pytest.mark.asyncio
async def test_removal_retains_before_and_after_observation_evidence():
    first = uuid4()
    second = uuid4()
    row = SimpleNamespace(
        id=uuid4(), camera_id=uuid4(), tracking_key="camera-default",
        state=PackageState.WAITING.value, started_at=BASE,
        last_present_at=BASE, absent_checks=1, gone_at=None,
        removal_kind=None, remover_person_id=None, last_observation_id=first,
        evidence={"present": True, "observation_id": str(first)}, updated_at=BASE,
    )
    db = _Db(row, None)
    next_row = await apply_package_check(
        db,
        camera_id=row.camera_id,
        evidence=PackageEvidence(BASE + timedelta(minutes=4), present=False, observation_id=second),
    )

    assert next_row.state == PackageState.GONE.value
    assert next_row.evidence["last_present_observation_id"] == str(first)
    assert next_row.evidence["observation_id"] == str(second)
