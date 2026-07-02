"""Tests for the agent setup tools (create_rule, test_camera_connection,
run_doctor, get_rule_schema) and the MCP write-tool exclusion."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.tools import TOOL_REGISTRY, create_rule, get_rule_schema
from services.agent.tools import test_camera_connection as camera_connection_tool
from services.mcp.server import read_tool_names


def registry_entry(name):
    return next(t for t in TOOL_REGISTRY if t["name"] == name)


def test_new_tools_registered_with_side_effects():
    assert registry_entry("create_rule")["side_effect"] == "write"
    assert registry_entry("test_camera_connection")["side_effect"] == "read"
    assert registry_entry("run_doctor")["side_effect"] == "read"
    assert registry_entry("get_rule_schema")["side_effect"] == "read"


def test_mcp_excludes_write_tools():
    names = read_tool_names()
    assert "create_rule" not in names
    assert "test_camera_connection" in names
    assert "run_doctor" in names


@pytest.mark.asyncio
async def test_get_rule_schema_shape():
    out = await get_rule_schema({})
    assert {"triggers", "actions", "conditions", "sequence"} <= set(out)


@pytest.mark.asyncio
async def test_create_rule_always_disabled():
    db = AsyncMock()
    db.add = MagicMock()
    created = {}

    async def refresh(rule):
        rule.id = uuid.uuid4()
        created["rule"] = rule

    db.refresh = AsyncMock(side_effect=refresh)
    with patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await create_rule(
            {"db": db},
            name="Package watch",
            trigger_pattern={"type": "object_detected", "label": "package"},
            actions=[{"type": "notify", "message": "Package!", "severity": "info"}],
        )
    assert out["ok"] is True
    assert out["enabled"] is False
    assert created["rule"].enabled is False
    assert out["review_url"].startswith("/rules/")


@pytest.mark.asyncio
async def test_create_rule_validation_error_returned_not_raised():
    db = AsyncMock()
    out = await create_rule(
        {"db": db},
        name="bad",
        trigger_pattern={"type": "loitering"},  # missing points + camera_id
        actions=[{"type": "notify", "message": "x"}],
    )
    assert out["ok"] is False
    assert "Validation failed" in out["error"]
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_rule_stale_refs_blocked():
    db = AsyncMock()
    db.add = MagicMock()
    with patch(
        "services.api.routes.rules._stale_rule_refs",
        new=AsyncMock(return_value=["conditions.camera_ids[0] does not match any camera (x)"]),
    ):
        out = await create_rule(
            {"db": db},
            name="ghost",
            trigger_pattern={"type": "object_detected", "label": "person"},
            conditions={"camera_ids": [str(uuid.uuid4())]},
            actions=[{"type": "notify", "message": "x"}],
        )
    assert out["ok"] is False
    assert "Broken references" in out["error"]
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_test_camera_connection_classifies():
    cam = MagicMock()
    cam.stream_type = "rtsp"
    cam.stream_url = "rtsp://cam.local/stream"
    db = AsyncMock()
    db.get = AsyncMock(return_value=cam)
    with patch(
        "services.api.camera_probe.probe_tcp",
        return_value={"ok": False, "error_code": "timeout", "detail": "No response"},
    ):
        out = await camera_connection_tool({"db": db}, camera_id=str(uuid.uuid4()))
    assert out["ok"] is False
    assert out["error_code"] == "timeout"
    assert out["hint"]


@pytest.mark.asyncio
async def test_test_camera_connection_skips_file():
    cam = MagicMock()
    cam.stream_type = "file"
    db = AsyncMock()
    db.get = AsyncMock(return_value=cam)
    out = await camera_connection_tool({"db": db}, camera_id=str(uuid.uuid4()))
    assert out["ok"] is True
    assert out["skipped"] is True
