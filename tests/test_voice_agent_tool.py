"""The Ask agent speaking out loud (issue #158).

This is the dangerous one. The doorbell agent has no tools and no
household context, so it cannot leak what it never had. This agent has
the orientation block, every tool result it gathered, and a question from
a household member, and a speaker pointed at whoever is standing outside.

So the tests here are mostly about what it is prevented from doing.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

import services.agent.tools as tools_mod
from services.agent.tools import get_tool, speak_on_camera
from services.voice.disclosure import SAFE_FALLBACK

CAM = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, camera=None, names=None):
        self.camera = camera
        self.names = names or []

    async def get(self, model, pk):
        return self.camera

    async def execute(self, *a, **kw):
        return _FakeResult(self.names)


def _wire(monkeypatch, *, enabled=True, allowed=True, camera=True,
          names=None, spoken=True, may_confirm=None, never_say=None):
    said = {}
    values = {
        "voice_agent_tool_enabled": enabled,
        "voice_may_confirm": may_confirm or [],
        "voice_never_say": never_say or [],
    }

    async def fake_get_setting(key, default=None):
        return values.get(key, default)

    async def fake_accessible(user, db):
        return {CAM} if allowed else set()

    async def fake_speak(db, cam, text, **kwargs):
        said["text"] = text
        said["kwargs"] = kwargs
        return SimpleNamespace(
            spoken=spoken, status="played" if spoken else "suppressed",
            reason=None if spoken else "quiet_hours",
            detail=None if spoken else "quiet hours 22:00-07:00",
            transport="mock", duration_ms=900,
        )

    import shared.app_settings as settings_mod
    import services.voice.speaker as speaker_mod

    monkeypatch.setattr(settings_mod, "get_setting", fake_get_setting)
    monkeypatch.setattr(speaker_mod, "speak", fake_speak)
    monkeypatch.setattr(tools_mod, "accessible_camera_ids", fake_accessible)

    db = _FakeDB(
        camera=SimpleNamespace(id=CAM, name="Front Door") if camera else None,
        names=names or [],
    )
    ctx = {"db": db, "user": SimpleNamespace(id="u-1"), "run_id": "run-9"}
    return ctx, said


# ---- the gate ------------------------------------------------------------


def test_the_tool_does_nothing_until_a_household_enables_it(monkeypatch):
    """A rule's words can be read and previewed before they play. An
    agent's cannot, so this ships off."""
    ctx, said = _wire(monkeypatch, enabled=False)

    out = _run(speak_on_camera(ctx, camera_id=str(CAM), text="Hello."))

    assert out["error"] == "not_enabled"
    assert said == {}


def test_it_is_the_only_tool_that_is_not_read_only():
    """Worth asserting: it is easy to add a second one without noticing
    that this registry used to have a uniform property."""
    physical = [
        t["name"] for t in tools_mod.TOOL_REGISTRY
        if t["side_effect"] != "read"
    ]
    assert physical == ["speak_on_camera"]
    assert get_tool("speak_on_camera")["side_effect"] == "physical"


def test_a_camera_the_asker_cannot_see_cannot_be_made_to_talk(monkeypatch):
    """Same access boundary every other tool honours."""
    ctx, said = _wire(monkeypatch, allowed=False)

    out = _run(speak_on_camera(ctx, camera_id=str(CAM), text="Hello."))

    assert out["error"] == "no_access"
    assert said == {}


def test_an_unknown_camera_id_is_refused(monkeypatch):
    ctx, said = _wire(monkeypatch)
    out = _run(speak_on_camera(ctx, camera_id="not-a-uuid", text="Hi"))

    assert out["error"] == "invalid_camera"
    assert said == {}


# ---- the disclosure filter applies here too -----------------------------


def test_the_agent_cannot_read_household_information_aloud(monkeypatch):
    """The whole reason this tool is treated carefully. This agent knows
    who lives here; the person standing at the camera must not."""
    ctx, said = _wire(monkeypatch, names=["Sarah"])

    out = _run(speak_on_camera(
        ctx, camera_id=str(CAM), text="Hi Sarah, your parcel arrived."
    ))

    assert said["text"] == SAFE_FALLBACK
    assert out["rewritten"] is True
    assert out["reason"] == "identity"


def test_it_cannot_announce_that_nobody_is_home(monkeypatch):
    ctx, said = _wire(monkeypatch)

    out = _run(speak_on_camera(
        ctx, camera_id=str(CAM), text="Nobody is home, please come back later."
    ))

    assert said["text"] == SAFE_FALLBACK
    assert out["reason"] == "absence"


def test_the_agent_is_told_its_wording_was_replaced(monkeypatch):
    """Otherwise it reports to the user that it said something it did
    not say."""
    ctx, _ = _wire(monkeypatch)

    out = _run(speak_on_camera(
        ctx, camera_id=str(CAM), text="The door is unlocked."
    ))

    assert "Tell the user this happened" in out["note"]


def test_an_ordinary_announcement_goes_through_unchanged(monkeypatch):
    ctx, said = _wire(monkeypatch)

    out = _run(speak_on_camera(
        ctx, camera_id=str(CAM), text="Please leave the parcel by the door."
    ))

    assert said["text"] == "Please leave the parcel by the door."
    assert out["spoken"] is True
    assert "rewritten" not in out


def test_household_disclosure_settings_are_honoured(monkeypatch):
    """The same allowlist the settings page writes."""
    ctx, said = _wire(monkeypatch, names=["Sarah"], may_confirm=["names"])

    out = _run(speak_on_camera(ctx, camera_id=str(CAM), text="Hi Sarah."))

    assert said["text"] == "Hi Sarah."
    assert out["spoken"] is True


# ---- the audit -----------------------------------------------------------


def test_the_utterance_is_traceable_to_the_run(monkeypatch):
    """An agent-initiated line is the one most worth being able to trace
    back to the question that caused it."""
    ctx, said = _wire(monkeypatch)

    _run(speak_on_camera(ctx, camera_id=str(CAM), text="Hello there."))

    assert said["kwargs"]["agent_run_id"] == "run-9"
    assert said["kwargs"]["trigger"] == "agent"


# ---- the camera's own guards still apply --------------------------------


def test_quiet_hours_still_win(monkeypatch):
    """The tool does not bypass the per-camera guards. Being asked by a
    person is not a reason to shout at 3am."""
    ctx, _ = _wire(monkeypatch, spoken=False)

    out = _run(speak_on_camera(ctx, camera_id=str(CAM), text="Hello."))

    assert out["spoken"] is False
    assert out["reason"] == "quiet_hours"
    assert "22:00" in out["note"]


# ---- the description steers it away from the obvious misuse -------------


def test_the_description_warns_against_answering_the_user_aloud():
    """The likeliest misuse is the agent replying to the user through a
    speaker instead of in chat."""
    description = get_tool("speak_on_camera")["description"].lower()

    assert "never use it to answer the user" in description
    assert "reply in chat" in description
