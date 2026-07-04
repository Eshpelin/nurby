"""Tests for POST /api/rules/generate (NL rule creation)."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import services.api.routes.rules_nl as nl
from shared.rule_schema import build_schema

CAM = uuid.uuid4()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_system_prompt_contains_vocabulary_and_entities():
    prompt = nl.build_system_prompt(
        build_schema(),
        cameras=[(str(CAM), "Front Door")],
        persons=[("p1", "Mom")],
        channels=[],
    )
    assert "object_detected" in prompt
    assert "loitering" in prompt
    assert "telegram" in prompt
    assert f'"Front Door" = {CAM}' in prompt
    assert '"Mom" = p1' in prompt
    assert "Telegram channels: none" in prompt
    assert "ONLY a JSON object" in prompt


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def test_parse_plain_json():
    assert nl.parse_rule_json('{"name": "x"}') == {"name": "x"}


def test_parse_fenced_json():
    assert nl.parse_rule_json('```json\n{"name": "x"}\n```') == {"name": "x"}


def test_parse_json_with_prose():
    assert nl.parse_rule_json('Here you go:\n{"name": "x"}\nEnjoy!') == {"name": "x"}


def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        nl.parse_rule_json("I cannot help with that.")


# ---------------------------------------------------------------------------
# Endpoint: parse → validate → retry loop
# ---------------------------------------------------------------------------


VALID_RULE = {
    "name": "Package arrives",
    "enabled": True,
    "trigger_pattern": {"type": "object_detected", "label": "package"},
    "conditions": None,
    "actions": [{"type": "notify", "message": "Package!", "severity": "info"}],
    "cooldown_seconds": 300,
    "severity": "detection",
}


def make_db():
    db = AsyncMock()
    provider = MagicMock()
    provider.default_model = "gemma3:4b"
    result = MagicMock()
    result.scalars.return_value.first.return_value = provider
    entity_result = MagicMock()
    entity_result.all.return_value = []
    entity_result.scalars.return_value.first.return_value = provider
    db.execute = AsyncMock(return_value=entity_result)
    return db


def make_user():
    class U:
        role = "admin"

    return U()


def llm_response(text):
    resp = MagicMock()
    resp.text = text
    return resp


@pytest.mark.asyncio
async def test_generate_happy_path():
    db = make_db()
    with patch("services.agent.llm.llm_call", new=AsyncMock(return_value=llm_response(json.dumps(VALID_RULE)))), \
         patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await nl.generate_rule(nl.GenerateRuleRequest(prompt="tell me about packages"), make_user(), db)
    assert out.rule["name"] == "Package arrives"
    assert out.warnings == []


@pytest.mark.asyncio
async def test_generate_retries_once_then_succeeds():
    db = make_db()
    bad = "not json at all"
    calls = AsyncMock(side_effect=[llm_response(bad), llm_response(json.dumps(VALID_RULE))])
    with patch("services.agent.llm.llm_call", new=calls), \
         patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await nl.generate_rule(nl.GenerateRuleRequest(prompt="packages"), make_user(), db)
    assert out.rule["name"] == "Package arrives"
    assert any("retried" in n for n in out.notes)
    assert calls.await_count == 2


@pytest.mark.asyncio
async def test_generate_422_after_two_failures():
    db = make_db()
    calls = AsyncMock(side_effect=[llm_response("nope"), llm_response("still nope")])
    with patch("services.agent.llm.llm_call", new=calls):
        with pytest.raises(HTTPException) as exc:
            await nl.generate_rule(nl.GenerateRuleRequest(prompt="packages"), make_user(), db)
    assert exc.value.status_code == 422
    assert "raw" in exc.value.detail


@pytest.mark.asyncio
async def test_generate_drops_unknown_keys():
    db = make_db()
    with_extra = dict(VALID_RULE, hallucinated_field="x")
    with patch("services.agent.llm.llm_call", new=AsyncMock(return_value=llm_response(json.dumps(with_extra)))), \
         patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await nl.generate_rule(nl.GenerateRuleRequest(prompt="packages"), make_user(), db)
    assert "hallucinated_field" not in out.rule
    assert any("hallucinated_field" in n for n in out.notes)


@pytest.mark.asyncio
async def test_generate_surfaces_ref_warnings():
    db = make_db()
    with patch("services.agent.llm.llm_call", new=AsyncMock(return_value=llm_response(json.dumps(VALID_RULE)))), \
         patch(
             "services.api.routes.rules._stale_rule_refs",
             new=AsyncMock(return_value=["conditions.camera_ids[0] does not match any camera (x)"]),
         ):
        out = await nl.generate_rule(nl.GenerateRuleRequest(prompt="packages"), make_user(), db)
    assert len(out.warnings) == 1


@pytest.mark.asyncio
async def test_generate_409_without_provider():
    db = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=empty)
    with pytest.raises(HTTPException) as exc:
        await nl.generate_rule(nl.GenerateRuleRequest(prompt="packages"), make_user(), db)
    assert exc.value.status_code == 409
