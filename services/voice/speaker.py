"""Say something through a camera, or record why not (issue #155).

The one place the pieces meet: policy decides, TTS renders, the codec
converts, a transport delivers, and a ``SpeechEvent`` records what
happened either way. Callers (the rule action today, the agent and
conversation sessions later) get one function and never assemble this
themselves, because every caller assembling it themselves is how a
guard gets skipped.

Nothing here raises at the caller. A camera that will not speak is an
outcome to record, not an exception to propagate into a rule engine that
is in the middle of firing other actions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from services.voice import policy as policy_mod
from services.voice.audio import for_backchannel
from services.voice.transport import TransportError, TransportUnsupported, build_transport
from shared import estop
from shared.app_settings import get_setting
from shared.models import Camera, SpeakerCapability, SpeechEvent

logger = logging.getLogger("nurby.voice.speaker")


@dataclass
class SpeakOutcome:
    """What happened, in a shape a caller can log or show."""

    spoken: bool
    status: str                    # played | suppressed | failed
    reason: str | None = None      # suppression reason or error kind
    detail: str | None = None
    transport: str | None = None
    duration_ms: int | None = None


async def _recent_activity(db, camera_id, now: datetime) -> tuple[int, float | None]:
    """``(spoken_today, seconds_since_last)`` for the rate limits.

    Counts only what was actually played. A suppressed attempt costing a
    household its daily cap would make one misconfigured rule silence a
    camera for the rest of the day.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spoken_today = (
        await db.execute(
            select(func.count(SpeechEvent.id))
            .where(SpeechEvent.camera_id == camera_id)
            .where(SpeechEvent.status == "played")
            .where(SpeechEvent.created_at >= midnight)
        )
    ).scalar() or 0

    last = (
        await db.execute(
            select(SpeechEvent.created_at)
            .where(SpeechEvent.camera_id == camera_id)
            .where(SpeechEvent.status == "played")
            .order_by(SpeechEvent.created_at.desc())
            .limit(1)
        )
    ).scalar()

    seconds_since = None
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        seconds_since = (now - last).total_seconds()
    return int(spoken_today), seconds_since


def resolve_transport_kind(camera, capability) -> str | None:
    """Which driver to use for this camera. Pure, for tests.

    An explicit setting on the camera wins: a household that knows their
    camera better than the probe did should be able to say so. Otherwise
    use what was probed. An external speaker endpoint is the fallback
    when nothing else is known, since it works regardless of the camera.
    """
    override = getattr(camera, "speaker_transport", None)
    if override:
        return override
    if capability is not None and getattr(capability, "supported", False):
        return getattr(capability, "transport", None)
    if getattr(camera, "speaker_endpoint", None):
        return "http_device"
    return None


async def speak(
    db,
    camera: Camera,
    text: str,
    *,
    trigger: str = "rule",
    rule_id=None,
    event_id=None,
    voice: str | None = None,
    volume: int | None = None,
    now: datetime | None = None,
) -> SpeakOutcome:
    """Render ``text`` and play it through ``camera``. Never raises."""
    now = now or datetime.now(timezone.utc)
    record = SpeechEvent(
        camera_id=camera.id, rule_id=rule_id, event_id=event_id,
        trigger=trigger, text=(text or "")[:4000],
        voice=voice or getattr(camera, "speaker_voice", None),
        status="queued",
    )
    db.add(record)

    def finish(outcome: SpeakOutcome) -> SpeakOutcome:
        record.status = outcome.status
        record.transport = outcome.transport
        record.duration_ms = outcome.duration_ms
        if outcome.status == "suppressed":
            record.suppressed_reason = outcome.reason
        elif outcome.status == "failed":
            record.error_message = outcome.detail
        elif outcome.status == "played":
            record.played_at = datetime.now(timezone.utc)
        return outcome

    try:
        household_enabled = bool(await get_setting("voice_enabled", False))
        tz_name = await get_setting("system_timezone") or "UTC"
        quiet_start = await get_setting("voice_quiet_hours_start")
        quiet_end = await get_setting("voice_quiet_hours_end")
        household_volume = await get_setting("voice_max_volume")

        capability = (
            await db.execute(
                select(SpeakerCapability)
                .where(SpeakerCapability.camera_id == camera.id)
            )
        ).scalars().first()

        spoken_today, seconds_since = await _recent_activity(db, camera.id, now)

        decision = policy_mod.may_speak(
            camera=camera, text=text, now=now,
            household_enabled=household_enabled,
            estop_engaged=estop.is_engaged(),
            capability=capability,
            spoken_today=spoken_today,
            seconds_since_last=seconds_since,
            tz_name=tz_name,
            household_quiet_start=quiet_start,
            household_quiet_end=quiet_end,
        )
        if not decision.allowed:
            return finish(SpeakOutcome(
                False, "suppressed", decision.reason, decision.detail
            ))

        kind = resolve_transport_kind(camera, capability)
        if not kind:
            return finish(SpeakOutcome(
                False, "suppressed", "unsupported",
                "no speaker transport known for this camera",
            ))

        clip = await _synthesize(text, voice or getattr(camera, "speaker_voice", None))
        if clip is None:
            return finish(SpeakOutcome(
                False, "suppressed", "empty_text", "nothing was synthesized"
            ))

        budget = policy_mod.within_duration_budget(clip.duration_seconds)
        if not budget.allowed:
            return finish(SpeakOutcome(
                False, "suppressed", budget.reason, budget.detail
            ))

        codec = (getattr(capability, "codec", None) or "pcmu").lower()
        rate = int(getattr(capability, "sample_rate", None) or 8000)
        payload = for_backchannel(clip, codec, rate)

        level = policy_mod.clamp_volume(
            volume, getattr(camera, "speaker_volume", None), household_volume
        )

        transport = await build_transport(kind)
        started = time.monotonic()
        await transport.speak(
            camera, payload, codec=codec, sample_rate=rate, volume=level,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        logger.info(
            "camera %s spoke %.1fs via %s", camera.id, clip.duration_seconds, kind
        )
        return finish(SpeakOutcome(True, "played", transport=kind, duration_ms=elapsed))

    except TransportUnsupported as exc:
        return finish(SpeakOutcome(False, "suppressed", "unsupported", str(exc)))
    except TransportError as exc:
        return finish(SpeakOutcome(False, "failed", "transport", str(exc)))
    except Exception as exc:  # noqa: BLE001 - a rule fire must survive this
        logger.exception("speaking through camera %s failed", camera.id)
        return finish(SpeakOutcome(
            False, "failed", type(exc).__name__, str(exc)[:500]
        ))


async def _synthesize(text: str, voice: str | None):
    """Render text with the configured provider. None if it cannot."""
    from services.voice.tts import build_provider, synthesize as run

    kind = await get_setting("voice_tts_provider") or "piper"
    use_cache = bool(await get_setting("voice_cache_enabled", True))
    provider = await build_provider(kind)
    return await run(provider, text, voice, use_cache=use_cache)
