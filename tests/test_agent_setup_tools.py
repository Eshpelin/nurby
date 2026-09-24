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


def test_the_agent_cannot_mutate_household_configuration():
    # The chat agent must not be able to change how the household is set
    # up. Rule creation deliberately lives on the Rules page, not in
    # chat (UX F35/F38).
    assert "create_rule" not in {t["name"] for t in TOOL_REGISTRY}
    # Nothing writes to the database through a tool.
    assert not [t for t in TOOL_REGISTRY if t["side_effect"] == "write"]


def test_speaking_is_the_only_tool_that_leaves_the_database():
    # This assertion used to be "every tool is read-only", and it was
    # loosened deliberately for speak_on_camera (issue #158), which acts
    # on a room rather than on stored state. It is narrowed rather than
    # deleted so a second physical tool cannot be added without someone
    # reading this and deciding it is acceptable.
    physical = [t["name"] for t in TOOL_REGISTRY if t["side_effect"] != "read"]
    assert physical == ["speak_on_camera"]


def test_the_physical_tool_is_never_exposed_over_mcp():
    # MCP is a remote surface. Reading household data over it is the
    # point; making a speaker talk in someone's house is not.
    assert "speak_on_camera" not in read_tool_names()


def test_the_physical_tool_ships_disabled():
    from shared.app_settings import DEFAULTS

    assert DEFAULTS["voice_agent_tool_enabled"] is False


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


@pytest.mark.asyncio
async def test_test_camera_connection_resolves_camera_name(monkeypatch):
    camera_id = uuid.uuid4()
    cam = MagicMock()
    cam.id = camera_id
    cam.name = "Demo Camera"
    cam.stream_type = "file"
    db = AsyncMock()
    db.get = AsyncMock(return_value=cam)
    row = MagicMock()
    row.scalars.return_value.all.return_value = [cam]
    db.execute.return_value = row
    user = MagicMock()

    async def allowed(*_args):
        return {camera_id}

    monkeypatch.setattr("services.agent.access.accessible_camera_ids", allowed)
    out = await camera_connection_tool(
        {"db": db, "user": user}, camera_id="demo camera"
    )

    assert out["ok"] is True
    assert out["skipped"] is True
