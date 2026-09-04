"""Whether a camera may speak, and why not (issue #155).

Every guard between "a rule fired" and "a speaker made a noise" lives
here, as pure functions over plain values. The transport does IO, the
action does orchestration, and this decides. That split is deliberate:
the decisions are the part with real consequences in somebody's house, so
they are the part that has to be exhaustively testable without hardware,
a database, or a clock.

A refusal is always a *reason*, never a bare False. The reason is written
to ``SpeechEvent.suppressed_reason`` so a household can see that their
rule has been quietly muted by quiet hours for a month rather than
wondering why the camera never speaks.

The order the checks run in is itself a policy decision. Cheapest and
most absolute first: a paused household or a disabled camera should never
reach a cooldown lookup, and nothing should reach the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("nurby.voice.policy")

# Ceiling on any single utterance, whatever a rule asks for. A rule with
# a runaway template must not be able to hold a speaker open indefinitely.
MAX_UTTERANCE_SECONDS = 30.0

# Absolute volume ceiling regardless of camera or rule configuration.
MAX_VOLUME = 100


@dataclass(frozen=True)
class Decision:
    """May this be spoken, and if not, why."""

    allowed: bool
    reason: str | None = None
    detail: str | None = None

    @classmethod
    def yes(cls) -> "Decision":
        return cls(True)

    @classmethod
    def no(cls, reason: str, detail: str | None = None) -> "Decision":
        return cls(False, reason, detail)


def parse_hhmm(value: str | None) -> time | None:
    """``"22:00"`` to a time. None for anything unparseable. Pure.

    Tolerant on purpose: a malformed quiet-hours string should degrade to
    "no quiet hours configured" rather than raising inside a rule action
    and taking the whole fire with it.
    """
    if not value:
        return None
    try:
        hour, _, minute = str(value).strip().partition(":")
        return time(int(hour), int(minute or 0))
    except (ValueError, TypeError):
        logger.debug("unparseable quiet-hours value %r", value)
        return None


def in_quiet_hours(now: datetime, start: str | None, end: str | None,
                   tz_name: str = "UTC") -> bool:
    """Whether ``now`` falls inside the quiet window. Pure, for tests.

    Handles the overnight case, which is the normal one: 22:00 to 07:00
    wraps midnight, and a naive ``start <= t <= end`` comparison would
    make it match nothing at all and silently disable quiet hours.
    """
    begin = parse_hhmm(start)
    finish = parse_hhmm(end)
    if begin is None or finish is None:
        return False
    if begin == finish:
        return False  # a zero-length window means "no quiet hours"

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        local = now.astimezone(ZoneInfo(tz_name or "UTC"))
    except Exception:
        local = now.astimezone(timezone.utc)
    current = local.time()

    if begin < finish:
        return begin <= current < finish
    # Wraps midnight: inside if after the start OR before the end.
    return current >= begin or current < finish


def clamp_volume(requested: int | None, camera_max: int | None,
                 household_max: int | None) -> int:
    """The volume actually used. Pure, for tests.

    Every ceiling applies; the lowest wins. A rule cannot raise a camera
    above what the household set, and neither can raise it above
    MAX_VOLUME, so a misconfigured template cannot wake the street.
    """
    ceilings = [MAX_VOLUME]
    for ceiling in (camera_max, household_max):
        if isinstance(ceiling, int) and ceiling > 0:
            ceilings.append(ceiling)
    ceiling = min(ceilings)
    if not isinstance(requested, int) or requested <= 0:
        return ceiling
    return max(1, min(requested, ceiling))


def may_speak(
    *,
    camera,
    text: str,
    now: datetime,
    household_enabled: bool,
    estop_engaged: bool,
    capability=None,
    spoken_today: int = 0,
    seconds_since_last: float | None = None,
    tz_name: str = "UTC",
    household_quiet_start: str | None = None,
    household_quiet_end: str | None = None,
) -> Decision:
    """The whole gate, in one testable place. Pure, for tests.

    Ordered cheapest and most absolute first. A paused household never
    reaches a cooldown lookup, and nothing here touches the network.
    """
    # 1. Absolute stops. Someone has said no, globally.
    if estop_engaged:
        return Decision.no("estop", "Nurby is paused")
    if not household_enabled:
        return Decision.no("disabled", "voice is off for this household")
    if not getattr(camera, "speaker_enabled", False):
        return Decision.no("disabled", "voice is off for this camera")

    # 2. Nothing to say. Checked before capability so a broken template
    #    reports the broken template rather than blaming the hardware.
    if not (text or "").strip():
        return Decision.no("empty_text", "the rendered message was empty")

    # 3. Can this camera physically do it? An unprobed camera is allowed
    #    through: absence of a probe is not evidence of absence, and the
    #    transport will report the truth soon enough. A probe that ran and
    #    said no is a real answer and is honoured.
    if capability is not None and not getattr(capability, "supported", False):
        return Decision.no(
            "unsupported",
            getattr(capability, "probe_error", None) or "camera cannot play audio",
        )

    # 4. Time of day. Quiet hours are per-camera when set, household
    #    otherwise, so one noisy driveway can be silenced without
    #    silencing the house.
    start = getattr(camera, "speaker_quiet_start", None) or household_quiet_start
    end = getattr(camera, "speaker_quiet_end", None) or household_quiet_end
    if in_quiet_hours(now, start, end, tz_name):
        return Decision.no("quiet_hours", f"quiet hours {start}-{end}")

    # 5. Rate limits. Cooldown first: it is the one that stops a rule
    #    firing repeatedly at the same visitor.
    cooldown = int(getattr(camera, "speaker_cooldown_seconds", 0) or 0)
    if (
        cooldown > 0
        and seconds_since_last is not None
        and seconds_since_last < cooldown
    ):
        return Decision.no(
            "cooldown",
            f"spoke {seconds_since_last:.0f}s ago, cooldown is {cooldown}s",
        )

    cap = int(getattr(camera, "speaker_daily_cap", 0) or 0)
    if cap > 0 and spoken_today >= cap:
        return Decision.no("daily_cap", f"already spoke {spoken_today} times today")

    return Decision.yes()


def within_duration_budget(seconds: float) -> Decision:
    """Whether a synthesized clip is short enough to play. Pure.

    Checked after synthesis because the length is not knowable before it.
    A template that interpolated a whole VLM description would otherwise
    hold the speaker for minutes.
    """
    if seconds > MAX_UTTERANCE_SECONDS:
        return Decision.no(
            "policy",
            f"utterance is {seconds:.1f}s, limit is {MAX_UTTERANCE_SECONDS:.0f}s",
        )
    return Decision.yes()
