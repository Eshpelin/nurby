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


def test_system_prompt_maps_generic_person_to_object_detection():
    prompt = nl.build_system_prompt(
        build_schema(),
        cameras=[(str(CAM), "Front Door")],
        persons=[],
        channels=[],
    )
    assert "CHOOSING THE TRIGGER" in prompt
    assert 'object_detected with label "person"' in prompt
    # The generic-person few-shot must be present.
    assert '"notify me when a person shows up at the camera"' in prompt
    # No angle-bracket placeholder hints the model could copy verbatim.
    assert "<person uuid>" not in prompt


def test_system_prompt_includes_named_person_example_only_when_people_exist():
    with_people = nl.build_system_prompt(
        build_schema(),
        cameras=[],
        persons=[("p1", "Mom")],
        channels=[],
    )
    assert '"tell me when Mom gets home"' in with_people
    assert '"person_id": "p1"' in with_people
    without = nl.build_system_prompt(build_schema(), cameras=[], persons=[], channels=[])
    assert "gets home" not in without


# ---------------------------------------------------------------------------
# Impossible face-trigger downgrade
# ---------------------------------------------------------------------------


def face_rule(person_id=None):
    tp = {"type": "face_recognized"}
    if person_id is not None:
        tp["person_id"] = person_id
    return {"trigger_pattern": tp}


def test_coerce_face_trigger_with_empty_library():
    rule = face_rule()
    notes = nl.coerce_impossible_face_trigger(rule, persons=[])
    assert rule["trigger_pattern"] == {"type": "object_detected", "label": "person"}
    assert len(notes) == 1 and "person library is empty" in notes[0]


def test_coerce_face_trigger_with_placeholder_person_id():
    rule = face_rule("<person uuid>")
    notes = nl.coerce_impossible_face_trigger(rule, persons=[("p1", "Mom")])
    assert rule["trigger_pattern"] == {"type": "object_detected", "label": "person"}
    assert len(notes) == 1 and "matches nobody" in notes[0]


def test_coerce_keeps_valid_person_id():
    rule = face_rule("p1")
    notes = nl.coerce_impossible_face_trigger(rule, persons=[("p1", "Mom")])
    assert rule["trigger_pattern"]["type"] == "face_recognized"
    assert notes == []


def test_coerce_keeps_any_known_face_when_library_nonempty():
    rule = face_rule()
    notes = nl.coerce_impossible_face_trigger(rule, persons=[("p1", "Mom")])
    assert rule["trigger_pattern"]["type"] == "face_recognized"
    assert notes == []


def test_coerce_ignores_non_face_triggers():
    rule = {"trigger_pattern": {"type": "object_detected", "label": "package"}}
    assert nl.coerce_impossible_face_trigger(rule, persons=[]) == []
    assert rule["trigger_pattern"]["label"] == "package"


@pytest.mark.asyncio
async def test_generate_downgrades_impossible_face_rule():
    db = make_db()
    impossible = dict(
        VALID_RULE,
        trigger_pattern={"type": "face_recognized", "person_id": "<person uuid>"},
    )
    with patch("services.agent.llm.llm_call", new=AsyncMock(return_value=llm_response(json.dumps(impossible)))), \
         patch("services.api.routes.rules._stale_rule_refs", new=AsyncMock(return_value=[])):
        out = await nl.generate_rule(nl.GenerateRuleRequest(prompt="a person shows up"), make_user(), db)
    assert out.rule["trigger_pattern"] == {"type": "object_detected", "label": "person"}
    assert any("Known face" in n for n in out.notes)


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
