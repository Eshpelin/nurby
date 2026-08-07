"""Run one doorstep exchange (issue #157).

Where the pieces meet: a visitor's transcribed speech comes in, the
session decides whether the exchange continues, the doorbell agent
drafts a reply, the disclosure filter checks it, and the speaker plays
whatever survived. Every one of those steps already has its own tested
module; this is the sequence, kept thin on purpose so the interesting
decisions stay where they can be tested without hardware.

The ordering carries a few decisions worth stating.

**The filter runs on the rendered line, always, with no exception for
fixed text.** The greeting and the fallback pass it too. A check with an
exemption is a check with a hole, and fixed text is exactly what a future
edit would change without re-reading this file.

**A refused reply still speaks.** Silence makes a visitor ring again or
conclude the house is empty, which is the outcome the refusal existed to
prevent.

**Handoff ends the exchange immediately.** Once a person is on the line
the agent stops mid-budget, because its whole job was to hold the line
until exactly that happened.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.voice import conversation, disclosure, session as session_mod
from services.voice.speaker import speak

logger = logging.getLogger("nurby.voice.orchestrator")


@dataclass
class TurnResult:
    """What happened on one exchange."""

    spoken: str | None = None
    refused: disclosure.Verdict | None = None
    ended: str | None = None
    injection_flagged: bool = False
    history: list[dict] = field(default_factory=list)


async def open_session(db, camera, *, now: float | None = None):
    """Start a session and say the fixed greeting.

    The opening line is fixed rather than generated so the first thing a
    visitor hears is reviewable, identical every time, and still said
    when the model is unreachable.
    """
    from shared.models import VoiceSession

    now = now if now is not None else time.monotonic()
    row = VoiceSession(camera_id=camera.id, turns=0)
    db.add(row)
    # Flushed before the greeting so the first line carries the session
    # id like every other one. Without it the opening line would be the
    # only orphan in the transcript.
    await db.flush()

    state = session_mod.SessionState(started_at=now)
    outcome = await speak(
        db, camera, conversation.GREETING, trigger="conversation",
        session_id=row.id,
    )
    if outcome.spoken and outcome.duration_ms:
        session_mod.begin_playback(
            state, now, duration=outcome.duration_ms / 1000.0
        )
    return row, state, outcome


async def handle_utterance(
    db,
    camera,
    row,
    state: session_mod.SessionState,
    utterance: str,
    *,
    provider,
    model: str,
    household_names: list[str] | None = None,
    never_say: list[str] | None = None,
    may_confirm: list[str] | None = None,
    history: list[dict] | None = None,
    max_turns: int = session_mod.DEFAULT_MAX_TURNS,
    max_seconds: float = session_mod.DEFAULT_MAX_SECONDS,
    now: float | None = None,
) -> TurnResult:
    """One visitor turn: hear, draft, check, speak.

    Never raises. A doorbell that throws is a doorbell that goes silent
    at the worst possible moment.
    """
    now = now if now is not None else time.monotonic()
    history = list(history or [])
    result = TurnResult(history=history)

    state.last_visitor_audio_at = now

    ending = session_mod.should_end(
        state, now, max_turns=max_turns, max_seconds=max_seconds
    )
    if ending:
        result.ended = ending
        return result

    # Recorded, not blocked. Someone joking about ignoring instructions
    # still deserves a polite answer, and refusing would itself be
    # informative.
    result.injection_flagged = conversation.looks_like_injection(utterance)
    if result.injection_flagged:
        logger.info("visitor at camera %s attempted an injection", camera.id)

    history.append({"role": "visitor", "content": utterance})

    try:
        draft = await conversation.reply(provider, model, history[:-1], utterance)
    except Exception:
        logger.exception("doorbell agent failed")
        draft = conversation.FALLBACK

    # No exemption for fixed text: FALLBACK goes through this too.
    line, verdict = disclosure.safe_reply(
        draft,
        household_names=household_names,
        never_say=never_say,
        may_confirm=may_confirm,
    )
    if not verdict.allowed:
        result.refused = verdict
        session_mod.record_refusal(
            state, verdict.reason or "unknown", verdict.matched, line
        )

    outcome = await speak(
        db, camera, line, trigger="conversation",
        session_id=getattr(row, "id", None),
    )
    if outcome.spoken and outcome.duration_ms:
        session_mod.begin_playback(state, now, duration=outcome.duration_ms / 1000.0)

    history.append({"role": "agent", "content": line})
    state.turns += 1
    row.turns = state.turns
    row.refusals = list(state.refusals) or None
    result.spoken = line

    result.ended = session_mod.should_end(
        state, now, max_turns=max_turns, max_seconds=max_seconds
    )
    return result


def close_session(row, state: session_mod.SessionState, reason: str) -> None:
    """Finish a session row. Pure apart from the timestamp."""
    row.ended_at = datetime.now(timezone.utc)
    row.ended_reason = reason
    row.turns = state.turns
    row.refusals = list(state.refusals) or None


def hand_off(row, state: session_mod.SessionState, user_id) -> None:
    """A person has picked up. The agent stops talking immediately.

    Not an error path. This is the outcome the phase was designed
    around: the agent holds the line for a few seconds so a visitor is
    not left at a silent door, and a human takes it from there.
    """
    state.handed_off = True
    row.handed_off_to_user_id = user_id
    row.handed_off_at = datetime.now(timezone.utc)
    close_session(row, state, session_mod.ENDED_HANDED_OFF)
