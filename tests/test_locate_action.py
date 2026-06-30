"""Tests for the FindAnything `locate` rule action (P3).

A deterministic, user-authored, post-trigger grounding condition (design
§3.7): a cheap trigger fires, then locate runs and the chain branches on
{{vars.<output>.found}}, gated by §6 corroboration. No GPU, no DB, no files.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from services.events import actions
from shared.schemas import _validate_action_chain

# ── schema validation ─────────────────────────────────────────────────────

def test_schema_locate_valid_with_var_ref():
    _validate_action_chain([
        {"type": "locate", "prompt": "chicken", "output": "loc"},
        {"type": "notify", "message": "Chicken: {{vars.loc.found}}"},
    ])


def test_schema_locate_requires_prompt():
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "locate"}])
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "locate", "prompt": "   "}])


def test_schema_locate_bad_on_fail():
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "locate", "prompt": "x", "on_fail": "maybe"}])


def test_schema_locate_bad_min_overlap():
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "locate", "prompt": "x", "min_overlap": 2}])


def test_schema_locate_unknown_var_ref_rejected():
    with pytest.raises(ValueError):
        _validate_action_chain([{"type": "notify", "message": "{{vars.loc.found}}"}])


# ── IoU + corroboration ───────────────────────────────────────────────────

def test_iou():
    assert actions._iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    assert actions._iou((0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1)) == 0.0


class _Box:
    def __init__(self, n):
        self.bbox_norm = n


def test_corroborates_overlap():
    obs = {
        "frame_width": 1000, "frame_height": 1000,
        "object_detections": {"objects": [{"label": "bird", "bbox": [100, 100, 300, 300]}]},
    }
    assert actions._corroborates([_Box((0.1, 0.1, 0.3, 0.3))], obs, 0.1) is True
    assert actions._corroborates([_Box((0.8, 0.8, 0.9, 0.9))], obs, 0.1) is False


def test_corroborates_no_dims_or_no_dets_is_false():
    assert actions._corroborates([_Box((0.1, 0.1, 0.3, 0.3))],
                                 {"object_detections": {"objects": []}}, 0.1) is False
    assert actions._corroborates([_Box((0.1, 0.1, 0.3, 0.3))],
                                 {"frame_width": 1000, "frame_height": 1000,
                                  "object_detections": {"objects": []}}, 0.1) is False


# ── _execute_locate ────────────────────────────────────────────────────────

class _Rule:
    id = uuid.uuid4()
    name = "find-chicken"


class _Result:
    def __init__(self, boxes=(), error=None):
        self.boxes = list(boxes)
        self.error = error


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(actions, "_update_event_status", AsyncMock())
    monkeypatch.setattr(actions, "_record_locate_on_event", AsyncMock())
    monkeypatch.setattr(actions, "_load_locate_frame", lambda od: object())
    # Keep the persistent grounding cache out of the way (no DB in unit tests);
    # default to a miss + a no-op write so the live-grounding path runs.
    monkeypatch.setattr("services.grounding.cache.get_cached_grounding", AsyncMock(return_value=None))
    monkeypatch.setattr("services.grounding.cache.store_grounding", AsyncMock())


def _obs_with_det():
    return {
        "observation_id": str(uuid.uuid4()),
        "frame_width": 1000, "frame_height": 1000,
        "object_detections": {"objects": [{"label": "bird", "bbox": [100, 100, 300, 300]}]},
        "vars": {},
    }


@pytest.mark.asyncio
async def test_locate_found_and_corroborated(monkeypatch, patched):
    async def fake_ground(frame, prompt):
        return _Result(boxes=[_Box((0.1, 0.1, 0.3, 0.3))])

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = _obs_with_det()
    await actions._execute_locate(
        {"type": "locate", "prompt": "chicken", "output": "loc"},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is True
    assert obs["vars"]["loc"]["count"] == 1
    assert obs["vars"]["loc"]["corroborated"] is True


@pytest.mark.asyncio
async def test_locate_box_without_corroboration_stops_chain(monkeypatch, patched):
    # With require_corroboration explicitly ON, a box that overlaps no detection
    # vetoes the chain (the precision-gate path).
    async def fake_ground(frame, prompt):
        return _Result(boxes=[_Box((0.8, 0.8, 0.9, 0.9))])  # nowhere near the bird

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = _obs_with_det()
    with pytest.raises(RuntimeError):
        await actions._execute_locate(
            {"type": "locate", "prompt": "chicken", "output": "loc",
             "on_fail": "stop", "require_corroboration": True},
            obs, _Rule(), uuid.uuid4(), {},
        )
    assert obs["vars"]["loc"]["found"] is False


@pytest.mark.asyncio
async def test_locate_default_trusts_box_for_open_vocab(monkeypatch, patched):
    # The trap fix: by DEFAULT (no require_corroboration), a located box counts
    # even when it overlaps no YOLO detection — the open-vocabulary case. The
    # corroboration signal is still surfaced (here: False).
    async def fake_ground(frame, prompt):
        return _Result(boxes=[_Box((0.8, 0.8, 0.9, 0.9))])  # a chicken YOLO can't see

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = _obs_with_det()
    await actions._execute_locate(
        {"type": "locate", "prompt": "chicken", "output": "loc"},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is True
    assert obs["vars"]["loc"]["corroborated"] is False


@pytest.mark.asyncio
async def test_locate_cache_hit_skips_grounding(monkeypatch, patched):
    # On a persistent-cache hit, the boxes come from the cache: no GPU call.
    monkeypatch.setattr(
        "services.grounding.cache.get_cached_grounding",
        AsyncMock(return_value={"boxes": [[0.1, 0.1, 0.3, 0.3]],
                                "found": True, "corroborated": True, "count": 1}),
    )
    called = {"ground": 0}

    async def fake_ground(frame, prompt):
        called["ground"] += 1
        return _Result(boxes=[_Box((0.1, 0.1, 0.3, 0.3))])

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = _obs_with_det()
    await actions._execute_locate(
        {"type": "locate", "prompt": "chicken", "output": "loc"},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is True
    assert obs["vars"]["loc"]["count"] == 1
    assert called["ground"] == 0  # served from cache, no inference


@pytest.mark.asyncio
async def test_locate_not_found_continue_does_not_raise(monkeypatch, patched):
    async def fake_ground(frame, prompt):
        return _Result(boxes=[])

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = {"vars": {}}
    await actions._execute_locate(
        {"type": "locate", "prompt": "x", "output": "loc", "on_fail": "continue"},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is False


@pytest.mark.asyncio
async def test_locate_corroboration_disabled_trusts_box(monkeypatch, patched):
    async def fake_ground(frame, prompt):
        return _Result(boxes=[_Box((0.8, 0.8, 0.9, 0.9))])

    monkeypatch.setattr(actions, "_ground_locate", fake_ground)
    obs = {"frame_width": 1000, "frame_height": 1000,
           "object_detections": {"objects": []}, "vars": {}}
    await actions._execute_locate(
        {"type": "locate", "prompt": "x", "output": "loc", "require_corroboration": False},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is True


@pytest.mark.asyncio
async def test_locate_no_frame_fails(monkeypatch, patched):
    monkeypatch.setattr(actions, "_load_locate_frame", lambda od: None)
    obs = {"vars": {}}
    await actions._execute_locate(
        {"type": "locate", "prompt": "x", "output": "loc", "on_fail": "continue"},
        obs, _Rule(), uuid.uuid4(), {},
    )
    assert obs["vars"]["loc"]["found"] is False
