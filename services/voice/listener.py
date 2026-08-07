"""Wire heard speech to spoken replies (issue #157).

Everything else in this package was reachable only by calling it. This is
the piece that makes a doorbell actually work: the existing STT path
already turns a visitor's voice into a Transcript row, and this hangs off
that so the words reach the doorbell agent and an answer comes back out
of the speaker.

Held deliberately thin. Every decision it needs already lives in a tested
module, so this owns only the things that cannot be pure: which session a
camera currently has, not running two turns for one camera at once, and
never letting a failure here break the transcript write it hangs off.

Three details that are easy to get wrong:

**Our own voice.** A transcript arriving while the speaker is playing is
very likely the camera hearing itself. Transcripts carry no loudness, so
there is nothing to compare against our playback level, and the honest
move is to drop anything inside the echo window rather than guess. A
visitor who gets talked over can repeat themselves; an agent answering
itself is a loop.

**One turn at a time.** Two segments can finish transcribing at once. A
per-camera lock keeps a session's turns ordered, because two concurrent
turns would interleave into nonsense and double-count the budget.

**Sessions live in two places.** The row is durable so the UI and the
audit can see it; the timing state is in memory because monotonic clocks
and playback windows do not survive a restart and should not. A restart
drops live conversations, which is correct: nobody is still standing
there.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from services.voice import conversation, orchestrator, session as session_mod
from shared import estop
from shared.app_settings import get_setting
from shared.database import async_session

logger = logging.getLogger("nurby.voice.listener")


@dataclass
class _Live:
    """A conversation currently happening at one camera."""

    session_id: object
    state: session_mod.SessionState
    history: list[dict] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# camera_id (str) -> the conversation open there. In memory on purpose:
# see the module docstring.
_live: dict[str, _Live] = {}


def live_session_id(camera_id) -> object | None:
    """The session open at this camera, if any. For tests and the API."""
    entry = _live.get(str(camera_id))
    return entry.session_id if entry else None


def forget(camera_id) -> None:
    """Drop the in-memory state for a camera."""
    _live.pop(str(camera_id), None)


def reset() -> None:
    """Clear every live conversation. For tests."""
    _live.clear()


async def _allowed(camera) -> bool:
    """Whether this camera may hold a conversation at all.

    Conversation is gated separately from speaking. A household that
    wanted a deterrent announcement has not thereby agreed to an agent
    talking with whoever turns up.
    """
    if estop.is_engaged():
        return False
    if not bool(await get_setting("voice_enabled", False)):
        return False
    if not bool(await get_setting("voice_conversation_enabled", False)):
        return False
    return bool(getattr(camera, "speaker_enabled", False))


async def _household_names() -> list[str]:
    """Names the agent must not say out loud.

    Fetched per session rather than cached: a household that has just
    added a person should not have to restart perception before the
    filter protects that name.
    """
    from sqlalchemy import select

    from shared.models import Person

    try:
        async with async_session() as db:
            rows = (await db.execute(select(Person.display_name))).scalars().all()
        return [r for r in rows if r]
    except Exception:
        logger.debug("household name lookup failed", exc_info=True)
        return []


async def _provider():
    """The model that drafts replies, or None when none is configured."""
    from services.perception.vlm import get_active_provider

    try:
        return await get_active_provider()
    except Exception:
        logger.debug("no provider available for the doorbell agent", exc_info=True)
        return None


async def _notify(camera, session_id) -> None:
    """Tell the household somebody is at the door.

    The push is the point of the whole handoff design. The agent holds
    the line for a few seconds precisely so this has time to arrive and
    for someone to tap it.
    """
    from shared.push import send_push_to_user

    try:
        async with async_session() as db:
            await send_push_to_user(
                db,
                None,  # household-wide
                "Someone is at your door",
                f"{getattr(camera, 'name', 'A camera')} is talking to a visitor. "
                "Tap to take over.",
                {"kind": "voice_session", "session_id": str(session_id),
                 "camera_id": str(camera.id)},
            )
    except Exception:
        logger.debug("session push failed", exc_info=True)


async def on_transcript(camera_id, text: str, *, now: float | None = None) -> None:
    """A visitor said something. Answer them if we are allowed to.

    Never raises. This hangs off the transcript write path, and a
    doorbell failing must not cost the household their transcript.
    """
    try:
        await _handle(camera_id, text, now)
    except Exception:
        logger.exception("voice listener failed for camera %s", camera_id)


async def _handle(camera_id, text: str, now: float | None) -> None:
    from shared.models import Camera

    spoken = (text or "").strip()
    if not spoken:
        return

    now = now if now is not None else time.monotonic()
    key = str(camera_id)

    async with async_session() as db:
        camera = await db.get(Camera, camera_id)
        if camera is None or not await _allowed(camera):
            return

        entry = _live.get(key)

        # Our own voice coming back. Dropped rather than guessed at:
        # a transcript carries no loudness to compare against playback.
        if entry and session_mod.in_echo_window(entry.state, now):
            logger.debug("ignoring echo at camera %s", key)
            return

        provider = await _provider()
        if provider is None:
            return

        max_turns = int(await get_setting("voice_session_max_turns", 10))
        max_seconds = float(await get_setting("voice_session_max_seconds", 120))
        names = await _household_names()
        may_confirm = await get_setting("voice_may_confirm") or []
        never_say = await get_setting("voice_never_say") or []

        opening = entry is None
        if opening:
            row, state, _ = await orchestrator.open_session(db, camera, now=now)
            await db.commit()
            entry = _Live(session_id=row.id, state=state)
            _live[key] = entry
            # The greeting is already playing. The visitor's words that
            # opened the session are answered on their next turn rather
            # than talked over.
            await _notify(camera, row.id)
            return

    # Outside the session above so a slow model does not hold a
    # connection open for the whole turn.
    async with entry.lock:
        async with async_session() as db:
            from shared.models import Camera as _Camera, VoiceSession

            camera = await db.get(_Camera, camera_id)
            row = await db.get(VoiceSession, entry.session_id)
            if camera is None or row is None or row.ended_at is not None:
                forget(camera_id)
                return

            result = await orchestrator.handle_utterance(
                db, camera, row, entry.state, spoken,
                provider=provider, model=getattr(provider, "default_model", None),
                household_names=names,
                never_say=list(never_say),
                may_confirm=list(may_confirm),
                history=entry.history,
                max_turns=max_turns,
                max_seconds=max_seconds,
                now=now,
            )
            entry.history = result.history

            if result.ended:
                orchestrator.close_session(row, entry.state, result.ended)
                forget(camera_id)
            await db.commit()


async def sweep(now: float | None = None) -> int:
    """Close conversations whose visitor has stopped talking.

    Silence has no event to hang off, so it needs a sweep. Without one a
    session stays open until the process restarts, and the live card
    would claim somebody is still at the door.
    """
    from shared.models import VoiceSession

    now = now if now is not None else time.monotonic()
    closed = 0
    for key, entry in list(_live.items()):
        reason = session_mod.should_end(entry.state, now)
        if not reason:
            continue
        try:
            async with async_session() as db:
                row = await db.get(VoiceSession, entry.session_id)
                if row is not None and row.ended_at is None:
                    orchestrator.close_session(row, entry.state, reason)
                    await db.commit()
        except Exception:
            logger.exception("closing session at camera %s failed", key)
        _live.pop(key, None)
        closed += 1
    return closed


class SilenceSweeper:
    """Closes conversations nobody is having any more.

    Mirrors the shape of the other perception workers. Ticks often
    because the thing it is waiting for is a visitor walking away, and a
    live card claiming someone is still at the door is worse than a
    slightly eager close.
    """

    TICK_SECONDS = 5

    def __init__(self) -> None:
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("voice silence sweeper started")
        try:
            while not self._stopping.is_set():
                try:
                    closed = await sweep()
                    if closed:
                        logger.info("closed %d quiet conversation(s)", closed)
                except Exception:
                    logger.exception("silence sweep failed")
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.TICK_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("voice silence sweeper stopped")
