"""Agentic rule drafting behind a confirm gate (#284).

draft_rule translates a description into a real rule and returns a
client_action Confirm proposal — it writes nothing itself. Covered: the
proposal shape, camera-scope refusal, empty input, and graceful failure.
"""

import asyncio
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from services.agent.tools import setup_tools as st


def _run(coro):
    return asyncio.run(coro)


class _DB:
    async def execute(self, stmt):  # only hit if ACL query runs (it won't for admin/none)
        raise AssertionError("unexpected DB query")


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role="admin", is_active=True)


def _none_user():
    # camera_access_mode != 'selected' -> allowed_camera_ids returns empty set
    # without a DB query, so every camera reference is out of scope.
    return SimpleNamespace(id=uuid.uuid4(), role="viewer", is_active=True,
                           camera_access_mode="none")


def _patch_translate(monkeypatch, rule=None, raise_exc=None):
    async def _fake(db, description, **kw):
        if raise_exc:
            raise raise_exc
        return {"rule": rule, "notes": ["n1"], "warnings": []}
    monkeypatch.setattr("services.api.routes.rules_nl.translate_rule", _fake)


def test_draft_rule_returns_confirm_proposal(monkeypatch):
    rule = {
        "name": "Night door watch",
        "trigger_pattern": {"type": "object_detected", "label": "person"},
        "conditions": {"time_after": "22:00", "time_before": "06:00"},
        "actions": [{"type": "notify"}],
        "enabled": True,
    }
    _patch_translate(monkeypatch, rule=rule)
    out = _run(st.draft_rule({"db": _DB(), "user": _admin()}, description="tell me about people at the door at night"))
    assert out["ok"] is True
    ca = out["client_action"]
    assert ca["kind"] == "create_rule"
    assert ca["method"] == "POST" and ca["path"] == "/api/rules"
    assert ca["body"] == rule
    assert "Night door watch" in ca["title"]
    assert out["summary"] and "person detected" in out["summary"]
    # It proposes, it does not create.
    assert "confirm" in out["message_for_user"].lower()


def test_draft_rule_refuses_foreign_camera(monkeypatch):
    foreign = str(uuid.uuid4())
    rule = {
        "name": "Garage watch",
        "trigger_pattern": {"type": "object_detected", "label": "person"},
        "conditions": {"camera_ids": [foreign]},
        "actions": [{"type": "notify"}],
    }
    _patch_translate(monkeypatch, rule=rule)
    out = _run(st.draft_rule({"db": _DB(), "user": _none_user()}, description="watch the garage"))
    assert out["ok"] is False
    assert out["error"] == "camera_out_of_scope"


def test_draft_rule_no_camera_ok_for_restricted(monkeypatch):
    # A rule with no camera reference is fine even for a no-access user.
    rule = {"name": "Any", "trigger_pattern": {"type": "motion"}, "actions": [{"type": "notify"}]}
    _patch_translate(monkeypatch, rule=rule)
    out = _run(st.draft_rule({"db": _DB(), "user": _none_user()}, description="any motion"))
    assert out["ok"] is True


def test_draft_rule_empty_description():
    out = _run(st.draft_rule({"db": _DB(), "user": _admin()}, description="   "))
    assert out["ok"] is False


def test_draft_rule_translate_failure_is_graceful(monkeypatch):
    _patch_translate(monkeypatch, raise_exc=HTTPException(status_code=409, detail="no provider"))
    out = _run(st.draft_rule({"db": _DB(), "user": _admin()}, description="do a thing"))
    assert out["ok"] is False
    assert out["error"] == "could_not_draft"
    assert "no provider" in out["message"]


def test_draft_rule_is_registered_and_preferred():
    from services.agent.tools import TOOL_REGISTRY
    names = {t["name"] for t in TOOL_REGISTRY}
    assert "draft_rule" in names
    entry = next(t for t in TOOL_REGISTRY if t["name"] == "draft_rule")
    assert "PREFERRED" in entry["description"]
