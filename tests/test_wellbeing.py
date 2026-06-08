"""Tests for the guardian wellbeing read queries and the MCP rollup tool."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.guardian import mcp_tools
from services.guardian import wellbeing as wb

NOW = datetime(2026, 6, 8, 13, 0, 0, tzinfo=timezone.utc)
PID = uuid.uuid4()


def _row(action, at, *, posture=None, conf=None, cam=None):
    return SimpleNamespace(
        observation_id=uuid.uuid4(),
        camera_id=cam,
        action=action,
        posture=posture,
        confidence=conf,
        observed_at=at,
    )


def _db_with_rows(rows, cam=None):
    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=res)
    db.get = AsyncMock(return_value=cam)
    return db


@pytest.mark.asyncio
async def test_summary_rolls_up_counts_and_today_meal():
    rows = [
        _row("eating", NOW - timedelta(minutes=5)),     # today
        _row("walking", NOW - timedelta(hours=2)),
        _row("eating", NOW - timedelta(days=2)),         # earlier, not today
        _row("fallen", NOW - timedelta(hours=1)),
    ]
    db = _db_with_rows(rows)
    s = await wb.wellbeing_summary(db, PID, cutoff=NOW)
    assert s["counts"] == {"eating": 2, "walking": 1, "fallen": 1}
    assert s["ate_today"] is True
    assert s["eating_events_today"] == 1
    assert s["last_fall_at"] == (NOW - timedelta(hours=1)).isoformat()
    # rows are newest-first, so last_action is the most recent (eating 5m ago)
    assert s["last_action"]["action"] == "eating"


@pytest.mark.asyncio
async def test_summary_no_meal_no_fall():
    rows = [_row("walking", NOW - timedelta(hours=1)), _row("sitting", NOW - timedelta(hours=3))]
    db = _db_with_rows(rows)
    s = await wb.wellbeing_summary(db, PID, cutoff=NOW)
    assert s["ate_today"] is False
    assert s["last_fall_at"] is None
    assert s["counts"] == {"walking": 1, "sitting": 1}


@pytest.mark.asyncio
async def test_recent_actions_maps_zone_from_camera():
    cam = SimpleNamespace(location_label="Room 4", name="cam-4")
    rows = [_row("eating", NOW - timedelta(minutes=10), cam=uuid.uuid4())]
    db = _db_with_rows(rows, cam=cam)
    items = await wb.recent_actions(db, PID, cutoff=NOW)
    assert len(items) == 1
    assert items[0]["action"] == "eating"
    assert items[0]["zone"] == "Room 4"


# ── MCP tool ─────────────────────────────────────────────────────────────────

def _link(owner_id, person_id, **kw):
    base = dict(
        id=uuid.uuid4(),
        guardian_user_id=owner_id,
        person_id=person_id,
        tier="full",
        revoked_at=None,
        expires_at=None,
        premium=False,
        live_presence=False,
        live_video=False,
        audio=False,
        is_primary_parent=False,
        reveal_min_confidence=None,
        last_image_served_at=None,
        alert_prefs=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_guardian_wellbeing_tool_scopes_and_rolls_up(monkeypatch):
    uid = uuid.uuid4()
    person = SimpleNamespace(id=PID, display_name="Mum", nickname=None)
    link = _link(uid, PID)

    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [link]
    db.execute = AsyncMock(return_value=res)
    db.get = AsyncMock(return_value=person)

    monkeypatch.setattr(mcp_tools, "get_setting", AsyncMock(return_value=1800))

    async def fake_summary(_db, _pid, *, cutoff):
        return {
            "counts": {"eating": 1},
            "ate_today": True,
            "eating_events_today": 1,
            "last_fall_at": None,
            "last_action": {"action": "eating", "at": NOW.isoformat()},
            "window_days": 7,
            "as_of": cutoff.isoformat(),
        }

    monkeypatch.setattr(wb, "wellbeing_summary", fake_summary)

    ctx = {"user": SimpleNamespace(id=uid), "db": db}
    out = await mcp_tools.guardian_wellbeing(ctx)
    assert out["count"] == 1
    assert out["dependants"][0]["display_name"] == "Mum"
    assert out["dependants"][0]["ate_today"] is True
    assert out["dependants"][0]["counts"] == {"eating": 1}


@pytest.mark.asyncio
async def test_guardian_wellbeing_in_tool_registry():
    assert "guardian_wellbeing" in mcp_tools.guardian_tool_names()
    assert mcp_tools.get_guardian_tool("guardian_wellbeing") is not None
