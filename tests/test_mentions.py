"""Tests for @-mentions: the mentionables route, verification, prompt blocks."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.api.routes.mentions import list_mentionables, verify_mentions
from services.api.routes.rules_nl import build_system_prompt
from services.agent.driver import _format_mentions_line
from shared.rule_schema import build_schema
from shared.schemas import MentionRef

CAM = uuid.uuid4()
PERSON = uuid.uuid4()
DEVICE = uuid.uuid4()


def make_user():
    class U:
        role = "admin"

    return U()


@pytest.mark.asyncio
async def test_list_mentionables_all_kinds():
    db = AsyncMock()
    results = [
        [(CAM, "Front Porch")],                       # cameras
        [(PERSON, "Arman", "Ari")],                   # persons
        [(uuid.uuid4(), "Family alerts")],            # telegram channels
        [(DEVICE, "FrontPorchAlarm", "esp32-buzzer-alarm")],  # devices
    ]
    mocks = []
    for rows in results:
        m = MagicMock()
        m.all.return_value = rows
        mocks.append(m)
    db.execute = AsyncMock(side_effect=mocks)

    out = await list_mentionables(make_user(), db)
    kinds = {m["kind"] for m in out}
    assert kinds == {"camera", "person", "telegram_channel", "device"}
    person = next(m for m in out if m["kind"] == "person")
    assert person["hint"] == "Ari"
    device = next(m for m in out if m["kind"] == "device")
    assert device["hint"] == "ESP32 Buzzer Alarm"  # preset name resolved


@pytest.mark.asyncio
async def test_verify_mentions_drops_ghosts():
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(CAM,)]
    db.execute = AsyncMock(return_value=result)
    ghost = uuid.uuid4()
    out = await verify_mentions(
        db,
        [
            MentionRef(kind="camera", id=CAM, name="Front Porch"),
            MentionRef(kind="camera", id=ghost, name="Ghost Cam"),
        ],
    )
    assert len(out) == 1
    assert out[0]["id"] == str(CAM)


@pytest.mark.asyncio
async def test_verify_mentions_empty():
    db = AsyncMock()
    assert await verify_mentions(db, []) == []
    db.execute.assert_not_awaited()


def test_nl_prompt_includes_devices_and_tagged_block():
    prompt = build_system_prompt(
        build_schema(),
        cameras=[(str(CAM), "Front Porch")],
        persons=[(str(PERSON), "Arman")],
        channels=[],
        devices=[(str(DEVICE), "FrontPorchAlarm")],
        mentions=[
            {"kind": "person", "id": str(PERSON), "name": "arman"},
            {"kind": "device", "id": str(DEVICE), "name": "FrontPorchAlarm"},
        ],
    )
    assert f'"FrontPorchAlarm" = {DEVICE}' in prompt
    assert "USER-TAGGED ENTITIES" in prompt
    assert f'"arman" = person {PERSON}' in prompt
    # The device action vocab made it into the prompt too.
    assert "- device:" in prompt


def test_driver_mentions_line_format():
    line = _format_mentions_line(
        [{"kind": "camera", "id": str(CAM), "name": "Front Porch"}]
    )
    assert "pre-resolved" in line
    assert f"'Front Porch' = camera {CAM}" in line
