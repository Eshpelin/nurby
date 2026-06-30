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


def test_correlation_keys_person_and_journey():
    data = {"person_detections": {
        "faces": [{"person_id": "sam"}, {"person_id": "sam"}],  # de-duped
        "bodies": [{"body_cluster_id": "b1"}],
        "tracks": [{"person_id": "bob"}, {"body_cluster_id": "b2"}]}}
    assert seqmod.correlation_keys(data, "person") == ["person:sam", "person:bob"]
    assert seqmod.correlation_keys(data, "journey") == ["journey:b1", "journey:b2"]
    # singular helper returns the first
    assert seqmod.correlation_key(data, "person") == "person:sam"
    assert seqmod.correlation_key({"person_detections": {"faces": []}}, "person") is None


def test_is_locate_check():
    assert seqmod.is_locate_check({"check": {"type": "locate"}}) is True
    assert seqmod.is_locate_check({"check": {"type": "verify"}}) is True
    assert seqmod.is_locate_check({"check": {"type": "object_detected"}}) is False


def test_snapshot_compact():
    snap = seqmod._snapshot({"camera_id": "c1", "timestamp": "t", "junk": "x", "motion_score": 5})
    assert snap == {"camera_id": "c1", "timestamp": "t"}  # only known fields kept


def test_reconstruct_obs():
    iv = {"trigger": {"camera_id": "c1", "timestamp": "t0"}, "steps": [{"camera_id": "c1"}]}
    data = seqmod._reconstruct_obs(iv)
    assert data["camera_id"] == "c1"
    assert data["event_kind"] == "sequence_timeout"
    assert data["vars"]["trigger"] == iv["trigger"]
    assert data["vars"]["steps"] == iv["steps"]


def test_reconstruct_obs_empty():
    data = seqmod._reconstruct_obs(None)
    assert data["event_kind"] == "sequence_timeout"
    assert data["vars"] == {"trigger": {}, "steps": []}


# ── orchestration (DB ops faked) ───────────────────────────────────────────

@pytest.fixture
def store(monkeypatch):
    state = {"active": [], "create": [], "advance": [], "status": [], "restart": [], "bump": [], "fire": 0}

    async def find_active(rule_id, key):
        return [seqmod._Active(a["id"], a["step_index"], a["deadline"], a.get("vars"))
                for a in state["active"] if a["key"] == key and a["status"] == "active"]

    async def count_active(rule_id):
        return len([a for a in state["active"] if a["status"] == "active"])

    async def create(rule_id, key, step_index, deadline, vars=None):
        state["create"].append((key, step_index, deadline, vars))

    async def advance(iid, step_index, deadline, step_snapshot=None):
        state["advance"].append((iid, step_index, deadline, step_snapshot))

    async def set_status(iid, status):
        state["status"].append((iid, status))

    async def restart(iid, deadline, trigger_snapshot=None):
        state["restart"].append((iid, deadline, trigger_snapshot))

    async def bump_hits(iid, hits):
        state["bump"].append((iid, hits))
        for a in state["active"]:
            if a["id"] == iid:
                a["vars"] = {**(a.get("vars") or {}), "_hits": hits}

    monkeypatch.setattr(seqmod, "_find_active_for_key", find_active)
    monkeypatch.setattr(seqmod, "_count_active", count_active)
    monkeypatch.setattr(seqmod, "_create", create)
    monkeypatch.setattr(seqmod, "_advance", advance)
    monkeypatch.setattr(seqmod, "_set_status", set_status)
    monkeypatch.setattr(seqmod, "_restart", restart)
    monkeypatch.setattr(seqmod, "_bump_hits", bump_hits)
    return state


def _add_active(store, key, step_index, deadline, status="active", vars=None):
    store["active"].append({"id": uuid.uuid4(), "key": key, "step_index": step_index,
                            "deadline": deadline, "status": status, "vars": vars})
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
    key, idx, deadline, vars = store["create"][0]
    assert key == "cam:c1" and idx == 0
    assert deadline == _now() + timedelta(seconds=30)  # step 0 within_seconds
    assert vars == {"trigger": {"camera_id": "c1"}, "steps": []}  # trigger snapshot


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
    _iid, idx, _deadline, snap = store["advance"][0]
    assert idx == 1
    assert snap == {"camera_id": "c1"}  # step snapshot recorded
    assert store["fire"] == 0  # not the last step


@pytest.mark.asyncio
async def test_complete_fires_on_last_step(store):
    _add_active(store, "cam:c1", 1, _now() + timedelta(seconds=20),  # at last step (len 2)
                vars={"trigger": {"camera_id": "c1", "timestamp": "t0"}, "steps": [{"camera_id": "c1"}]})
    data = {"camera_id": "c1"}
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(n=2), data,
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["fire"] == 1
    assert "completed" in [s for _i, s in store["status"]]
    # on_complete sees the full journey via vars.
    assert data["vars"]["trigger"] == {"camera_id": "c1", "timestamp": "t0"}
    assert len(data["vars"]["steps"]) == 2  # prior step + final completing snapshot
    assert data["event_kind"] == "sequence_complete"


@pytest.mark.asyncio
async def test_confirm_frames_needs_k_agreeing(store):
    # confirm_frames=2: first matching frame bumps the counter (no advance),
    # the second confirms and advances.
    iid = _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=60),
                      vars={"trigger": {}, "steps": [], "_hits": 0})
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "object_detected"}, "within_seconds": 60, "confirm_frames": 2},
        {"check": {"type": "object_detected"}, "within_seconds": 60},
    ]}
    async def fire():
        store["fire"] += 1
    # frame 1 → bump to 1, no advance
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["advance"] == []
    assert store["bump"] == [(iid, 1)]
    # frame 2 → reaches 2, advances (the bump wrote _hits=1 back to the instance)
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert len(store["advance"]) == 1


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
async def test_locate_step_skipped_without_grounding(store):
    # No locate_check_fn wired -> locate steps never match (e.g. pure unit run).
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
    assert store["advance"] == []


@pytest.mark.asyncio
async def test_locate_step_runs_with_grounding(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "key"}, "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    calls = []
    async def locate_fn(check, data):
        calls.append(check["prompt"])
        return True
    async def fire():
        store["fire"] += 1
    # step_match_fn returns False, so any advance must come from the locate path.
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: False,
        fire_cb=fire, locate_check_fn=locate_fn, now=_now(),
    )
    assert calls == ["key"]            # grounding invoked
    assert len(store["advance"]) == 1  # advanced past the locate step


@pytest.mark.asyncio
async def test_locate_pre_gate_blocks_grounding(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "key"},
         "pre_gate": {"type": "object_detected", "label": "person"},
         "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    calls = []
    async def locate_fn(check, data):
        calls.append(1)
        return True
    async def fire():
        store["fire"] += 1
    # pre_gate predicate returns False -> grounding must NOT run.
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: False,
        fire_cb=fire, locate_check_fn=locate_fn, now=_now(),
    )
    assert calls == []             # GPU skipped by the cheap gate
    assert store["advance"] == []


@pytest.mark.asyncio
async def test_locate_pre_gate_allows_grounding(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "key"},
         "pre_gate": {"type": "object_detected", "label": "person"},
         "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    calls = []
    async def locate_fn(check, data):
        calls.append(1)
        return True
    async def fire():
        store["fire"] += 1
    # pre_gate passes (step_match_fn True) -> grounding runs and advances.
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True,
        fire_cb=fire, locate_check_fn=locate_fn, now=_now(),
    )
    assert calls == [1]
    assert len(store["advance"]) == 1


@pytest.mark.asyncio
async def test_negate_locate_matches_on_absence(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "key in box"}, "negate": True, "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    async def locate_absent(check, data):
        return False  # the thing is NOT there
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True,
        fire_cb=fire, locate_check_fn=locate_absent, now=_now(),
    )
    assert len(store["advance"]) == 1  # absence satisfied the negated step


@pytest.mark.asyncio
async def test_negate_locate_no_match_when_present(store):
    _add_active(store, "cam:c1", 0, _now() + timedelta(seconds=20))
    seq = {"correlate_by": "camera", "steps": [
        {"check": {"type": "locate", "prompt": "key in box"}, "negate": True, "within_seconds": 30},
        {"check": {"type": "object_detected"}, "within_seconds": 30},
    ]}
    async def locate_present(check, data):
        return True  # it IS there → negated step must not match
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), seq, {"camera_id": "c1"},
        start_matched=False, step_match_fn=lambda p: True,
        fire_cb=fire, locate_check_fn=locate_present, now=_now(),
    )
    assert store["advance"] == []


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
async def test_person_correlation_starts_per_subject(store):
    data = {"camera_id": "c1", "person_detections": {"faces": [
        {"person_id": "sam"}, {"person_id": "bob"}]}}
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(correlate="person"), data,
        start_matched=True, step_match_fn=lambda p: False, fire_cb=fire, now=_now(),
    )
    keys = sorted(k for k, *_ in store["create"])
    assert keys == ["person:bob", "person:sam"]  # one instance per recognized subject


@pytest.mark.asyncio
async def test_person_advance_matches_only_that_subject(store):
    _add_active(store, "person:sam", 0, _now() + timedelta(seconds=20))
    data = {"camera_id": "c1", "person_detections": {"faces": [
        {"person_id": "sam"}, {"person_id": "bob"}]}}
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(correlate="person"), data,
        start_matched=False, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert len(store["advance"]) == 1  # only Sam's in-flight instance advanced


@pytest.mark.asyncio
async def test_no_subject_is_noop(store):
    # person mode but no recognized faces -> nothing to bind.
    async def fire():
        store["fire"] += 1
    await seqmod.evaluate_sequence(
        _Rule(), _seq(correlate="person"), {"camera_id": "c1"},
        start_matched=True, step_match_fn=lambda p: True, fire_cb=fire, now=_now(),
    )
    assert store["create"] == [] and store["advance"] == []


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


def test_schema_on_timeout_can_reference_trigger_and_step_vars():
    # The absence-alert chain references the start observation and step journey.
    _validate_sequence({
        "steps": [{"check": {"type": "object_detected"}, "within_seconds": 5}],
        "on_timeout": [
            {"type": "notify", "message": "{{vars.trigger.camera_name}}: nobody put it away"},
            {"type": "telegram", "message": "first seen {{vars.steps.0.timestamp}}"},
        ],
    })


def test_schema_unknown_var_still_rejected():
    # trigger/steps are allowed, but a genuinely undeclared var is not.
    from shared.schemas import _validate_action_chain
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "notify", "message": "{{vars.nope.x}}"}])


def test_schema_valid_pre_gate():
    _validate_sequence({"steps": [
        {"check": {"type": "locate", "prompt": "key"}, "within_seconds": 5,
         "pre_gate": {"type": "object_detected", "label": "person"}},
    ]})


def test_schema_bad_pre_gate():
    with pytest.raises(ValueError):
        _validate_sequence({"steps": [
            {"check": {"type": "object_detected"}, "within_seconds": 5, "pre_gate": "person"},
        ]})


def test_schema_confirm_frames():
    _validate_sequence({"steps": [
        {"check": {"type": "object_detected"}, "within_seconds": 5, "confirm_frames": 3},
    ]})
    with pytest.raises(ValueError):
        _validate_sequence({"steps": [
            {"check": {"type": "object_detected"}, "within_seconds": 5, "confirm_frames": 0},
        ]})


def test_schema_verify_step():
    _validate_sequence({"steps": [
        {"check": {"type": "verify", "question": "is the door open?"}, "within_seconds": 5},
    ]})
    with pytest.raises(ValueError):  # verify needs a question
        _validate_sequence({"steps": [
            {"check": {"type": "verify"}, "within_seconds": 5},
        ]})
