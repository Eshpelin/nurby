from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.perception.package_lifecycle import (
    PackageEvidence,
    PackageLifecycle,
    PackageState,
    RemovalKind,
    advance,
)
from services.perception.package_lifecycle_store import _known_person_id, _package_present


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
