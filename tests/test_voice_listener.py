"""The runtime glue between hearing and speaking (issue #157).

This is the piece that makes a doorbell work rather than merely exist.
It owns the things that cannot be pure: which session a camera has, not
running two turns at once, and never breaking the transcript write it
hangs off.
"""

import asyncio
from types import SimpleNamespace

import pytest

from services.voice import listener, orchestrator, session as session_mod


class _FakeDB:
    def __init__(self, camera=None, row=None):
        self.camera = camera
        self.row = row
        self.committed = 0

    async def get(self, model, pk):
        name = model.__name__
        if name == "Camera":
            return self.camera
        if name == "VoiceSession":
            return self.row
        return None

    def add(self, row):
        pass

    async def flush(self):
        return None

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _camera(**kw):
    base = dict(id="cam-1", name="Front Door", speaker_enabled=True)
    base.update(kw)
    return SimpleNamespace(**base)


def _row(**kw):
    base = dict(
        id="sess-1", camera_id="cam-1", turns=0, refusals=None,
        ended_at=None, ended_reason=None,
        handed_off_to_user_id=None, handed_off_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _wire(monkeypatch, *, camera=None, row=None, settings=None, provider=True,
          turn_result=None, opened=None):
    """Patch every edge of the listener. Returns what it recorded."""
    camera = camera if camera is not None else _camera()
    row = row if row is not None else _row()
    db = _FakeDB(camera, row)
    calls = {"opened": 0, "turns": [], "pushes": 0, "closed": []}

    values = {
        "voice_enabled": True,
        "voice_conversation_enabled": True,
        "voice_session_max_turns": 10,
        "voice_session_max_seconds": 120,
        "voice_may_confirm": [],
        "voice_never_say": [],
    }
    values.update(settings or {})

    async def fake_get_setting(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(listener, "async_session", lambda: db)
    monkeypatch.setattr(listener, "get_setting", fake_get_setting)
    monkeypatch.setattr(listener, "_household_names", lambda: _async([]))
    monkeypatch.setattr(
        listener, "_provider",
        lambda: _async(SimpleNamespace(default_model="m") if provider else None),
    )

    async def fake_notify(cam, sid):
        calls["pushes"] += 1

    monkeypatch.setattr(listener, "_notify", fake_notify)

    async def fake_open(db_, cam, now=None):
        calls["opened"] += 1
        state = opened or session_mod.SessionState(started_at=now or 1000.0)
        return row, state, SimpleNamespace(spoken=True, duration_ms=1200)

    monkeypatch.setattr(orchestrator, "open_session", fake_open)

    async def fake_turn(db_, cam, row_, state, text, **kw):
        calls["turns"].append(text)
        return turn_result or orchestrator.TurnResult(spoken="ok", history=[])

    monkeypatch.setattr(orchestrator, "handle_utterance", fake_turn)
    monkeypatch.setattr(
        orchestrator, "close_session",
        lambda r, s, reason: calls["closed"].append(reason),
    )
    monkeypatch.setattr(listener.estop, "is_engaged", lambda: False)

    listener.reset()
    return calls, db, camera, row


def _async(value):
    async def inner():
        return value
    return inner()


def _run(coro):
    return asyncio.run(coro)


# ---- opening -------------------------------------------------------------


def test_the_first_words_open_a_session_and_push(monkeypatch):
    """The push is the point of the handoff design. The agent holds the
    line precisely so this has time to arrive."""
    calls, _, _, _ = _wire(monkeypatch)

    _run(listener.on_transcript("cam-1", "Hello?", now=1000.0))

    assert calls["opened"] == 1
    assert calls["pushes"] == 1
    assert listener.live_session_id("cam-1") == "sess-1"


def test_the_opening_words_are_not_also_answered(monkeypatch):
    """The greeting is already playing. Answering the same words on top
    of it would have the camera talking over itself."""
    calls, _, _, _ = _wire(monkeypatch)

    _run(listener.on_transcript("cam-1", "Hello?", now=1000.0))

    assert calls["turns"] == []


def test_a_second_utterance_is_answered(monkeypatch):
    calls, _, _, _ = _wire(monkeypatch)

    _run(listener.on_transcript("cam-1", "Hello?", now=1000.0))
    _run(listener.on_transcript("cam-1", "I have a parcel", now=1100.0))

    assert calls["opened"] == 1
    assert calls["turns"] == ["I have a parcel"]


# ---- the gates -----------------------------------------------------------


def test_conversation_is_gated_separately_from_speaking(monkeypatch):
    """Wanting a deterrent announcement is not agreeing to an agent
    talking with whoever turns up."""
    calls, _, _, _ = _wire(
        monkeypatch, settings={"voice_conversation_enabled": False}
    )

    _run(listener.on_transcript("cam-1", "hello", now=1000.0))

    assert calls["opened"] == 0


def test_voice_off_household_wide_stops_it(monkeypatch):
    calls, _, _, _ = _wire(monkeypatch, settings={"voice_enabled": False})
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    assert calls["opened"] == 0


def test_a_camera_with_voice_off_stays_quiet(monkeypatch):
    calls, _, _, _ = _wire(monkeypatch, camera=_camera(speaker_enabled=False))
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    assert calls["opened"] == 0


def test_a_paused_household_never_answers(monkeypatch):
    calls, _, _, _ = _wire(monkeypatch)
    monkeypatch.setattr(listener.estop, "is_engaged", lambda: True)

    _run(listener.on_transcript("cam-1", "hello", now=1000.0))

    assert calls["opened"] == 0


def test_no_provider_means_no_conversation(monkeypatch):
    """Better to stay silent than to open a session that cannot reply."""
    calls, _, _, _ = _wire(monkeypatch, provider=False)
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    assert calls["opened"] == 0


def test_empty_speech_is_ignored(monkeypatch):
    calls, _, _, _ = _wire(monkeypatch)
    _run(listener.on_transcript("cam-1", "   ", now=1000.0))
    assert calls["opened"] == 0


def test_an_unknown_camera_is_survivable(monkeypatch):
    calls, db, _, _ = _wire(monkeypatch)
    db.camera = None
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    assert calls["opened"] == 0


# ---- hearing ourselves ---------------------------------------------------


def test_our_own_voice_is_not_treated_as_the_visitor(monkeypatch):
    """A transcript arriving while the speaker plays is very likely the
    camera hearing itself. Answering it is a loop."""
    state = session_mod.SessionState(started_at=1000.0)
    calls, _, _, _ = _wire(monkeypatch, opened=state)

    _run(listener.on_transcript("cam-1", "Hello?", now=1000.0))
    session_mod.begin_playback(state, 1000.0, duration=3.0, level=1.0)

    _run(listener.on_transcript("cam-1", "this is the echo", now=1001.0))

    assert calls["turns"] == []


def test_speech_after_the_echo_window_is_answered(monkeypatch):
    state = session_mod.SessionState(started_at=1000.0)
    calls, _, _, _ = _wire(monkeypatch, opened=state)

    _run(listener.on_transcript("cam-1", "Hello?", now=1000.0))
    session_mod.begin_playback(state, 1000.0, duration=1.0, level=1.0)

    after = 1001.0 + session_mod.ECHO_TAIL_SECONDS + 0.1
    _run(listener.on_transcript("cam-1", "I have a parcel", now=after))

    assert calls["turns"] == ["I have a parcel"]


# ---- ending --------------------------------------------------------------


def test_a_finished_turn_closes_the_session(monkeypatch):
    ended = orchestrator.TurnResult(
        spoken="ok", ended=session_mod.ENDED_MAX_TURNS, history=[]
    )
    calls, _, _, _ = _wire(monkeypatch, turn_result=ended)

    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    _run(listener.on_transcript("cam-1", "again", now=1100.0))

    assert calls["closed"] == [session_mod.ENDED_MAX_TURNS]
    assert listener.live_session_id("cam-1") is None


def test_an_already_ended_row_is_forgotten(monkeypatch):
    """Somebody took over from the app. The listener should notice
    rather than keep answering alongside them."""
    calls, db, _, row = _wire(monkeypatch)

    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    row.ended_at = "2026-09-08T10:00:00Z"
    _run(listener.on_transcript("cam-1", "again", now=1100.0))

    assert calls["turns"] == []
    assert listener.live_session_id("cam-1") is None


def test_the_sweeper_closes_a_quiet_conversation(monkeypatch):
    """Silence has no event to hang off. Without a sweep the live card
    would claim somebody is still at the door."""
    calls, _, _, _ = _wire(monkeypatch)
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))

    entry = listener._live["cam-1"]
    entry.state.last_visitor_audio_at = 1000.0

    closed = _run(listener.sweep(now=1000.0 + session_mod.SILENCE_TIMEOUT_SECONDS))

    assert closed == 1
    assert listener.live_session_id("cam-1") is None


def test_the_sweeper_leaves_a_live_conversation_alone(monkeypatch):
    _wire(monkeypatch)
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))
    listener._live["cam-1"].state.last_visitor_audio_at = 1000.0

    assert _run(listener.sweep(now=1001.0)) == 0
    assert listener.live_session_id("cam-1") == "sess-1"


# ---- it must never break the transcript ---------------------------------


def test_a_failure_inside_is_swallowed(monkeypatch):
    """This hangs off the transcript write path. A doorbell failing must
    not cost the household their transcript."""
    _wire(monkeypatch)

    async def boom(*a, **kw):
        raise RuntimeError("everything is broken")

    monkeypatch.setattr(listener, "_handle", boom)

    # Must not raise.
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))


# ---- bookkeeping ---------------------------------------------------------


def test_forget_and_reset_clear_state(monkeypatch):
    _wire(monkeypatch)
    _run(listener.on_transcript("cam-1", "hello", now=1000.0))

    listener.forget("cam-1")
    assert listener.live_session_id("cam-1") is None

    _run(listener.on_transcript("cam-1", "hello", now=1100.0))
    listener.reset()
    assert listener.live_session_id("cam-1") is None
