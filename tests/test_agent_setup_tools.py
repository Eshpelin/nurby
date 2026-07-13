"""Tests for the agent setup tools (suggest_rule, test_camera_connection,
run_doctor, get_rule_schema) and the MCP write-tool exclusion."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.driver import SYSTEM_PROMPT_TEMPLATE
from services.agent.tools import TOOL_REGISTRY, get_rule_schema, suggest_rule
from services.agent.tools import test_camera_connection as camera_connection_tool
from services.mcp.server import read_tool_names


def registry_entry(name):
    return next(t for t in TOOL_REGISTRY if t["name"] == name)


def test_new_tools_registered_with_side_effects():
    assert registry_entry("suggest_rule")["side_effect"] == "read"
    assert registry_entry("test_camera_connection")["side_effect"] == "read"
    assert registry_entry("run_doctor")["side_effect"] == "read"
    assert registry_entry("get_rule_schema")["side_effect"] == "read"


def test_no_write_tools_in_registry():
    # The chat agent must not be able to mutate anything. Rule creation
    # deliberately lives on the Rules page, not in chat (UX F35/F38).
    assert all(t["side_effect"] == "read" for t in TOOL_REGISTRY)
    assert "create_rule" not in {t["name"] for t in TOOL_REGISTRY}


def test_mcp_excludes_write_tools():
    names = read_tool_names()
    assert "create_rule" not in names
    assert "test_camera_connection" in names
    assert "run_doctor" in names


def test_prompt_says_agent_cannot_create_rules():
    assert "CANNOT" in SYSTEM_PROMPT_TEMPLATE
    assert "suggest_rule" in SYSTEM_PROMPT_TEMPLATE
    assert "Rules page" in SYSTEM_PROMPT_TEMPLATE
    # The old write tool must not be referenced anywhere the model sees.
    assert "create_rule" not in SYSTEM_PROMPT_TEMPLATE


@pytest.mark.asyncio
async def test_get_rule_schema_shape():
    out = await get_rule_schema({})
    assert {"triggers", "actions", "conditions", "sequence"} <= set(out)


@pytest.mark.asyncio
async def test_suggest_rule_builds_prefilled_link():
    out = await suggest_rule(
        {}, description="notify me when a package is left at the front door"
    )
    assert out["ok"] is True
    assert out["link"].startswith("/rules/new?describe=")
    assert "package%20is%20left" in out["link"]
    # The model gets a ready-made user-facing message carrying the link.
    assert out["link"] in out["message_for_user"]
    assert "create_rule" not in out["message_for_user"]


@pytest.mark.asyncio
async def test_suggest_rule_rejects_empty_description():
    out = await suggest_rule({}, description="   ")
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_suggest_rule_truncates_and_encodes():
    out = await suggest_rule({}, description="a b" * 600)
    assert out["ok"] is True
    # 500-char cap, then URL-encoded (spaces expand to %20).
    from urllib.parse import unquote

    decoded = unquote(out["link"].split("describe=", 1)[1])
    assert len(decoded) == 500


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
