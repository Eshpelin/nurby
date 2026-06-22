"""Tests for temporal sequence rules — engine core (slice 1).

Pure helpers + the evaluate_sequence orchestration with the DB ops faked
in-memory (no DB), plus schema validation. See docs/sequence-rules-design.md.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.events import sequences as seqmod
from shared.schemas import _validate_sequence

UTC = timezone.utc


def _now():
    return datetime(2026, 6, 21, 12, 0, 0, tzinfo=UTC)


class _Rule:
    id = uuid.uuid4()
    name = "seq-rule"


def _seq(correlate="camera", n=2, cameras=None):
    steps = [{"check": {"type": "object_detected"}, "within_seconds": 30 + i} for i in range(n)]
    s = {"correlate_by": correlate, "steps": steps}
    if cameras is not None:
        s["cameras"] = cameras
    return s


# ── pure helpers ──────────────────────────────────────────────────────────

def test_get_sequence():
    assert seqmod.get_sequence({"type": "x", "sequence": {"steps": [{"a": 1}]}})["steps"]
    assert seqmod.get_sequence({"type": "x", "sequence": {"steps": []}}) is None
    assert seqmod.get_sequence({"type": "x"}) is None
    assert seqmod.get_sequence(None) is None


def test_correlation_key_modes():
    assert seqmod.correlation_key({"camera_id": "c1"}, "camera") == "cam:c1"
    assert seqmod.correlation_key({"camera_id": "c1", "incident_id": "i9"}, "incident") == "inc:i9"
    assert seqmod.correlation_key({"camera_id": "c1"}, "incident") is None  # no incident
    assert seqmod.correlation_key({"camera_id": "c1"}, "none") == "all"
    assert seqmod.correlation_key({"camera_id": "c1"}, "person") is None  # slice 4


def test_correlation_key_camera_scope():
    assert seqmod.correlation_key({"camera_id": "c2"}, "camera", cameras=["c1"]) is None
    assert seqmod.correlation_key({"camera_id": "c1"}, "camera", cameras=["c1"]) == "cam:c1"


def test_is_locate_check():
    assert seqmod.is_locate_check({"check": {"type": "locate"}}) is True
    assert seqmod.is_locate_check({"check": {"type": "verify"}}) is True
    assert seqmod.is_locate_check({"check": {"type": "object_detected"}}) is False


# ── orchestration (DB ops faked) ───────────────────────────────────────────

@pytest.fixture
def store(monkeypatch):
    state = {"active": [], "create": [], "advance": [], "status": [], "restart": [], "fire": 0}

    async def find_active(rule_id, key):
        return [seqmod._Active(a["id"], a["step_index"], a["deadline"])
                for a in state["active"] if a["key"] == key and a["status"] == "active"]

    async def count_active(rule_id):
        return len([a for a in state["active"] if a["status"] == "active"])

    async def create(rule_id, key, step_index, deadline):
        state["create"].append((key, step_index, deadline))

    async def advance(iid, step_index, deadline):
        state["advance"].append((iid, step_index, deadline))

    async def set_status(iid, status):
        state["status"].append((iid, status))

    async def restart(iid, deadline):
        state["restart"].append((iid, deadline))

    monkeypatch.setattr(seqmod, "_find_active_for_key", find_active)
    monkeypatch.setattr(seqmod, "_count_active", count_active)
    monkeypatch.setattr(seqmod, "_create", create)
    monkeypatch.setattr(seqmod, "_advance", advance)
    monkeypatch.setattr(seqmod, "_set_status", set_status)
    monkeypatch.setattr(seqmod, "_restart", restart)
    return state


def _add_active(store, key, step_index, deadline, status="active"):
    store["active"].append({"id": uuid.uuid4(), "key": key, "step_index": step_index,
                            "deadline": deadline, "status": status})
    return store["active"][-1]["id"]


async def _fire_cb_factory(store):
    async def cb():
        store["fire"] += 1
    return cb


@pytest.mark.asyncio
async def test_start_creates_instance(store):
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(), {"camera_id": "c1"},
        start_matched=True, step_match_fn=lambda p: False, fire_cb=fire, now=_now(),
    )
    assert len(store["create"]) == 1
    key, idx, deadline = store["create"][0]
    assert key == "cam:c1" and idx == 0
    assert deadline == _now() + timedelta(seconds=30)  # step 0 within_seconds


@pytest.mark.asyncio
async def test_advance_to_next_step(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(n=2), {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert len(store["advance"]) == 1
    _iid, idx, _deadline = store["advance"][0]
    assert idx == 1
    assert store["fire"] == 0  # not the last step


@pytest.mark.asyncio
async def test_complete_fires_on_last_step(store):
    _add_active(store, "cam:c1", 1, _now() + timedelta(seconds=20))  # at last step (len 2)
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(n=2), {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["fire"] == 1
    assert ("completed" in [s for _i, s in store["status"]])


@pytest.mark.asyncio
async def test_overdue_instance_not_advanced(store):
    _add_active(store, "cam:c1", 0, _now() - timedelta(seconds=5))  # already lapsed
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(), {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["advance"] == []
    assert store["fire"] == 0


@pytest.mark.asyncio
async def test_locate_step_skipped_in_slice1(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "x"}, "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["advance"] == []  # locate step not evaluated in slice 1


@pytest.mark.asyncio
async def test_refire_ignore_does_not_duplicate(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = _seq()
    seq["on_refire"] = "ignore"
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=True, step_match_fn=lambda p: False, fire_cb=fire, now=_now(),
    )
    assert store["create"] == []
    assert store["restart"] == []


@pytest.mark.asyncio
async def test_refire_restart(store):
    _add_active(store, "cam:c1", 1, _now() + timedelta(seconds=20))
    seq = _seq()
    seq["on_refire"] = "restart"
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=True, step_match_fn=lambda p: False, fire_cb=fire, now=_now(),
    )
    assert len(store["restart"]) == 1
    assert store["create"] == []


@pytest.mark.asyncio
async def test_max_active_caps_starts(store):
    # 2 active instances under OTHER keys, max_active=2 -> no new start.
    _add_active(store, "cam:cA", 0, _now() + timedelta(seconds=20))
    _add_active(store, "cam:cB", 0, _now() + timedelta(seconds=20))
    seq = _seq()
    seq["max_active"] = 2
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=True, step_match_fn=lambda p: False, fire_cb=fire, now=_now(),
    )
    assert store["create"] == []  # at cap


@pytest.mark.asyncio
async def test_unsupported_correlation_is_noop(store):
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(correlate="person"), {"camera_id": "c1", "person_id": "p1"},
        start_matched=True, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["create"] == [] and store["advance"] == []  # person = slice 4


# ── schema validation ──────────────────────────────────────────────────────

def test_schema_valid_sequence():
    _validate_sequence({"correlate_by": "incident", "on_refire": "ignore", "max_active": 5,
                        "steps": [{"check": {"type": "object_detected"}, "within_seconds": 30}]})


def test_schema_requires_steps():
    with pytest.raises(ValueError):
        _validate_sequence({"steps": []})
    with pytest.raises(ValueError):
        _validate_sequence({"correlate_by": "camera"})


def test_schema_step_needs_check_and_window():
    with pytest.raises(ValueError):
        _validate_sequence({"steps": [{"within_seconds": 30}]})
    with pytest.raises(ValueError):
        _validate_sequence({"steps": [{"check": {"type": "x"}, "within_seconds": 0}]})


def test_schema_bad_correlate_and_refire():
    with pytest.raises(ValueError):
        _validate_sequence({"correlate_by": "nope", "steps": [{"check": {"type": "x"}, "within_seconds": 5}]})
    with pytest.raises(ValueError):
        _validate_sequence({"on_refire": "maybe", "steps": [{"check": {"type": "x"}, "within_seconds": 5}]})


def test_schema_locate_step_validated():
    # a locate step with no prompt is rejected via _validate_locate_action
    with pytest.raises(ValueError):
        _validate_sequence({"steps": [{"check": {"type": "locate"}, "within_seconds": 5}]})
