"""The rules of a spoken exchange (issue #157).

Turn-taking with a stranger at a door, expressed as pure decisions over
plain values so the awkward parts can be tested without a camera, a
microphone, or a clock.

Two of those parts cause most of the trouble in practice.

**Half duplex.** Cameras with a speaker and a microphone almost always
share one audio path, so while the speaker plays, the microphone hears
it. Left alone, the agent transcribes its own voice, treats it as the
visitor's next turn, and replies to itself. It is the single most likely
source of an embarrassing demo, and the fix is not clever: ignore audio
for as long as we are speaking, plus a tail for the room's echo.

**Barge-in.** A visitor who starts talking over the agent should
interrupt it, the way a person would. That directly conflicts with the
suppression above, so the two are reconciled in one place:
:func:`should_accept_audio` decides, and it distinguishes "our own voice
coming back" from "someone talking over us" by energy and timing rather
than by hope.

Budgets are hard stops, not suggestions. The agent's job is to hold the
line for a few seconds until a person picks up, so a session that runs
long has already failed at its actual purpose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("nurby.voice.session")

# How long after playback stops before the microphone is trusted again.
# Covers the room's reverb tail and the camera's own buffering. Too short
# and the agent hears its last syllable; too long and a quick visitor
# gets clipped.
ECHO_TAIL_SECONDS = 0.6

# A visitor has to be this much louder than our own playback to count as
# barging in rather than as echo leaking back. Echo returns attenuated,
# so a real interruption stands well clear of it.
BARGE_IN_RATIO = 2.5

# Silence that ends a session. Someone who has stopped talking has
# either left or is waiting for a human.
SILENCE_TIMEOUT_SECONDS = 12.0

# Hard stops.
DEFAULT_MAX_TURNS = 10
DEFAULT_MAX_SECONDS = 120.0

# Reasons a session can end. Recorded on the row.
ENDED_SILENT = "visitor_silent"
ENDED_MAX_TURNS = "max_turns"
ENDED_MAX_SECONDS = "max_seconds"
ENDED_HANDED_OFF = "handed_off"
ENDED_POLICY = "policy"
ENDED_ERROR = "error"


@dataclass
class SessionState:
    """Everything the turn loop needs to decide what happens next."""

    started_at: float
    turns: int = 0
    # When our own playback ends, on the same monotonic clock. None when
    # we are not speaking.
    speaking_until: float | None = None
    playback_level: float = 0.0
    last_visitor_audio_at: float | None = None
    handed_off: bool = False
    refusals: list[dict] = field(default_factory=list)

    def elapsed(self, now: float) -> float:
        return now - self.started_at


def is_speaking(state: SessionState, now: float) -> bool:
    """Whether our own audio is still playing. Pure."""
    return state.speaking_until is not None and now < state.speaking_until


def in_echo_window(state: SessionState, now: float,
                   tail: float = ECHO_TAIL_SECONDS) -> bool:
    """Whether incoming audio could still be our own voice. Pure.

    The window runs from the start of playback to its end plus a tail,
    because the room keeps returning our audio after the speaker stops.
    """
    if state.speaking_until is None:
        return False
    return now < state.speaking_until + tail


def should_accept_audio(
    state: SessionState,
    now: float,
    level: float,
    *,
    tail: float = ECHO_TAIL_SECONDS,
    barge_ratio: float = BARGE_IN_RATIO,
) -> bool:
    """Whether this audio is the visitor rather than our own echo. Pure.

    Outside the echo window everything is the visitor. Inside it, only
    audio clearly louder than our own playback counts, which is what
    lets a real interruption through without letting the agent hear
    itself.
    """
    if not in_echo_window(state, now, tail):
        return True
    if state.playback_level <= 0:
        # We do not know how loud we are, so we cannot tell echo from a
        # voice. Stay silent-eared rather than risk replying to
        # ourselves; the visitor can speak again a moment later.
        return False
    return level >= state.playback_level * barge_ratio


def should_barge_in(
    state: SessionState,
    now: float,
    level: float,
    *,
    tail: float = ECHO_TAIL_SECONDS,
    barge_ratio: float = BARGE_IN_RATIO,
) -> bool:
    """Whether to stop talking because the visitor started. Pure.

    Only meaningful while we are actually speaking; accepted audio after
    playback has finished is just the next turn.
    """
    if not is_speaking(state, now):
        return False
    return should_accept_audio(
        state, now, level, tail=tail, barge_ratio=barge_ratio
    )


def should_end(
    state: SessionState,
    now: float,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    silence_timeout: float = SILENCE_TIMEOUT_SECONDS,
) -> str | None:
    """The reason to end this session, or None to continue. Pure.

    Ordered by how definitive each reason is. A handoff outranks every
    budget: once a person is on the line, the agent stops regardless of
    how much time it had left.
    """
    if state.handed_off:
        return ENDED_HANDED_OFF
    if state.turns >= max_turns:
        return ENDED_MAX_TURNS
    if state.elapsed(now) >= max_seconds:
        return ENDED_MAX_SECONDS
    if state.last_visitor_audio_at is not None:
        if now - state.last_visitor_audio_at >= silence_timeout:
            return ENDED_SILENT
    return None


def begin_playback(state: SessionState, now: float, duration: float,
                   level: float = 1.0) -> None:
    """Record that we are speaking, so the microphone is discounted."""
    state.speaking_until = now + max(0.0, duration)
    state.playback_level = max(0.0, level)


def end_playback(state: SessionState, now: float) -> None:
    """Cut playback short, as a barge-in does. The echo tail still
    applies from this moment, because the room is still returning what
    we already played."""
    state.speaking_until = now


def record_refusal(state: SessionState, reason: str, matched: str | None,
                   spoken_instead: str) -> None:
    """Keep what the agent declined to say.

    The audit that matters most for a talking agent is not what it said
    but what it nearly said, so refusals are kept on the session rather
    than only logged.
    """
    state.refusals.append({
        "reason": reason,
        "matched": matched,
        "spoken_instead": spoken_instead,
    })
