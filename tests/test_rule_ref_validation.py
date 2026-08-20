"""Tests for rule reference validation and the /rules/health aggregate."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.api.routes.rules import (
    _collect_rule_refs,
    _stale_rule_refs,
    create_rule,
)
from shared.schemas import RuleCreate

CAM = uuid.uuid4()
PERSON = uuid.uuid4()
CHANNEL = uuid.uuid4()


# ---------------------------------------------------------------------------
# _collect_rule_refs
# ---------------------------------------------------------------------------


def test_collect_refs_full_shape():
    refs, malformed = _collect_rule_refs(
        {
            "type": "face_recognized",
            "person_id": str(PERSON),
            "camera_id": str(CAM),
            "sequence": {
                "cameras": [str(CAM)],
                "steps": [
                    {"check": {"type": "object_detected", "camera_id": str(CAM)}, "within_seconds": 60},
                ],
            },
        },
        {"camera_ids": [str(CAM)], "camera_id": str(CAM)},
        [{"type": "telegram", "channel_id": str(CHANNEL)}, {"type": "notify", "message": "x"}],
    )
    assert len(refs["camera"]) == 5
    assert refs["person"] == [("trigger_pattern.person_id", PERSON)]
    assert refs["telegram_channel"] == [("actions[0].channel_id", CHANNEL)]
    assert malformed == []


def test_collect_refs_flags_non_uuid():
    # A name in a ref position (classic small-LLM failure mode) is no
    # longer skipped silently; it becomes an actionable message.
    refs, malformed = _collect_rule_refs(
        {"camera_id": "front-door"}, {"camera_ids": ["Living Room"]}, []
    )
    assert refs["camera"] == []
    assert len(malformed) == 2
    assert "Living Room" in malformed[1]


def test_collect_refs_empty_rule():
    refs, malformed = _collect_rule_refs({}, None, [])
    assert all(not v for v in refs.values())
    assert malformed == []


# ---------------------------------------------------------------------------
# _stale_rule_refs
# ---------------------------------------------------------------------------


def make_db(existing_ids):
    """AsyncMock db whose execute() returns rows for ids in existing_ids."""
    db = AsyncMock()

    async def execute(query):
        result = MagicMock()
        # The IN-clause values are embedded in the query; simplest fake is
        # to report every id in existing_ids as present.
        result.all.return_value = [(i,) for i in existing_ids]
        return result

    db.execute = AsyncMock(side_effect=execute)
    return db


@pytest.mark.asyncio
async def test_stale_refs_flags_missing_camera():
    db = make_db(set())  # nothing exists
    msgs = await _stale_rule_refs(db, {"camera_id": str(CAM)}, None, [])
    assert len(msgs) == 1
    assert "trigger_pattern.camera_id" in msgs[0]
    assert str(CAM) in msgs[0]


@pytest.mark.asyncio
async def test_stale_refs_ok_when_present():
    db = make_db({CAM, PERSON})
    msgs = await _stale_rule_refs(
        db, {"camera_id": str(CAM), "person_id": str(PERSON)}, None, []
    )
    assert msgs == []


@pytest.mark.asyncio
async def test_stale_refs_no_refs_no_queries():
    db = make_db(set())
    msgs = await _stale_rule_refs(db, {"type": "motion"}, None, [{"type": "notify", "message": "x"}])
    assert msgs == []
    db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# create_rule 422 on stale refs
# ---------------------------------------------------------------------------


def make_user():
    class U:
        role = "admin"

    return U()


@pytest.mark.asyncio
async def test_create_rule_422_on_stale_camera():
    db = make_db(set())
    body = RuleCreate(
        name="ghost camera rule",
        trigger_pattern={"type": "object_detected", "label": "person"},
        conditions={"camera_ids": [str(CAM)]},
        actions=[{"type": "notify", "message": "hi"}],
    )
    with pytest.raises(HTTPException) as exc:
        await create_rule(body, make_user(), db)
    assert exc.value.status_code == 422
    assert "conditions.camera_ids[0]" in exc.value.detail


# ---------------------------------------------------------------------------
# /rules/health "completed work" counts
# ---------------------------------------------------------------------------


def _rows(pairs):
    """A db.execute() result whose .all() yields (rule_id, count) rows."""
    res = MagicMock()
    res.all.return_value = list(pairs)
    return res


@pytest.mark.asyncio
async def test_health_reports_completed_work_counts():
    from unittest.mock import patch

    from services.api.routes.rules import rules_health

    rule = MagicMock()
    rule.id = uuid.uuid4()
    rule.trigger_pattern = {"type": "motion"}
    rule.conditions = None
    rule.actions = []

    fired_at = MagicMock()
    fired_at.isoformat.return_value = "2026-08-19T10:00:00+00:00"

    rules_res = MagicMock()
    rules_res.scalars.return_value.all.return_value = [rule]

    db = AsyncMock()
    # Query order in rules_health: rules, last_fired, fires_7d, acted_7d,
    # clips_7d, indexed_7d, latest-per-rule.
    db.execute.side_effect = [
        rules_res,
        _rows([(rule.id, fired_at)]),
        _rows([(rule.id, 9)]),
        _rows([(rule.id, 7)]),
        _rows([(rule.id, 5)]),
        _rows([(rule.id, 8)]),
        _rows([(rule.id, "success", None)]),
    ]

    with patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await rules_health(make_user(), db)

    entry = out[str(rule.id)]
    assert entry["fires_7d"] == 9
    assert entry["acted_7d"] == 7
    assert entry["clips_7d"] == 5
    assert entry["indexed_7d"] == 8
    assert entry["last_action_status"] == "success"


@pytest.mark.asyncio
async def test_health_completed_work_defaults_to_zero():
    from unittest.mock import patch

    from services.api.routes.rules import rules_health

    rule = MagicMock()
    rule.id = uuid.uuid4()
    rule.trigger_pattern = {"type": "motion"}
    rule.conditions = None
    rule.actions = []

    rules_res = MagicMock()
    rules_res.scalars.return_value.all.return_value = [rule]

    db = AsyncMock()
    db.execute.side_effect = [rules_res] + [_rows([]) for _ in range(6)]

    with patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await rules_health(make_user(), db)

    entry = out[str(rule.id)]
    assert (entry["acted_7d"], entry["clips_7d"], entry["indexed_7d"]) == (0, 0, 0)
    assert entry["last_fired_at"] is None
