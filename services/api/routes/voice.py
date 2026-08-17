"""Voice settings, test playback, and the speech audit trail (#156).

The UI's job here is mostly to be honest. A camera that cannot speak has
to say so and why, a preset that no longer matches has to read as custom,
and a test phrase has to go through the same path a rule would rather
than a simulated one, or the button proves nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.voice import presets as presets_mod
from shared.auth import require_admin
from shared.database import get_db
from shared.models import (
    Camera,
    SpeakerCapability,
    SpeechEvent,
    Transcript,
    User,
    VoiceSession,
)

router = APIRouter()

# What the test button says. Short, obviously a test, and not something
# that would alarm anyone who happens to be standing there.
TEST_PHRASE = "This is a test of the camera speaker."


class VoicePatch(BaseModel):
    preset: str | None = None
    speaker_enabled: bool | None = None
    speaker_transport: str | None = None
    speaker_voice: str | None = None
    speaker_volume: int | None = Field(default=None, ge=1, le=100)
    speaker_quiet_start: str | None = None
    speaker_quiet_end: str | None = None
    speaker_cooldown_seconds: int | None = Field(default=None, ge=0)
    speaker_daily_cap: int | None = Field(default=None, ge=0)
    speaker_endpoint: str | None = None


def _capability_view(capability: SpeakerCapability | None) -> dict:
    """What the UI should say about this camera's hardware.

    Three states, deliberately distinguishable. Never probed is not the
    same as probed and unsupported, and a household deserves to know
    which one it is looking at before concluding their camera is mute.
    """
    if capability is None:
        return {
            "probed": False,
            "supported": None,
            "transport": None,
            "summary": "Not checked yet. Run a speaker probe to find out.",
        }
    if capability.supported:
        return {
            "probed": True,
            "supported": True,
            "transport": capability.transport,
            "codec": capability.codec,
            "sample_rate": capability.sample_rate,
            "vendor": capability.vendor,
            "probed_at": capability.probed_at.isoformat() if capability.probed_at else None,
            "summary": f"Can speak over {capability.transport}.",
        }
    return {
        "probed": True,
        "supported": False,
        "transport": capability.transport,
        "vendor": capability.vendor,
        "probed_at": capability.probed_at.isoformat() if capability.probed_at else None,
        "summary": capability.probe_error or "This camera cannot play audio.",
    }


def _camera_view(camera: Camera, capability: SpeakerCapability | None) -> dict:
    return {
        "id": str(camera.id),
        "name": camera.name,
        # Inferred rather than stored, so a camera whose numbers were
        # edited directly reads as custom instead of claiming a preset it
        # no longer matches.
        "preset": presets_mod.infer(camera),
        "speaker_enabled": camera.speaker_enabled,
        "speaker_transport": camera.speaker_transport,
        "speaker_voice": camera.speaker_voice,
        "speaker_volume": camera.speaker_volume,
        "speaker_quiet_start": camera.speaker_quiet_start,
        "speaker_quiet_end": camera.speaker_quiet_end,
        "speaker_cooldown_seconds": camera.speaker_cooldown_seconds,
        "speaker_daily_cap": camera.speaker_daily_cap,
        "speaker_endpoint": bool(camera.speaker_endpoint),
        "capability": _capability_view(capability),
    }


def interleave_transcript(heard, said) -> list[dict]:
    """Merge both halves of a conversation into one time-ordered list.

    The two sides come from different systems: the visitor's words are
    Transcript rows written by the STT path, the camera's are
    SpeechEvent rows. Neither knows about the other, so they are merged
    here rather than stored pre-joined.

    Suppressed lines are kept and labelled. What a camera declined to say
    is the more interesting half of the audit, and dropping it would make
    a filtered conversation look like an ordinary one. Pure, for tests.
    """
    turns = [
        {
            "at": t.started_at.isoformat() if t.started_at else None,
            "speaker": "visitor",
            "text": t.text,
        }
        for t in heard or []
    ] + [
        {
            "at": e.created_at.isoformat() if e.created_at else None,
            "speaker": "camera",
            "text": e.text,
            "status": e.status,
            "suppressed_reason": e.suppressed_reason,
        }
        for e in said or []
    ]
    # A row with no timestamp sorts first rather than crashing the sort.
    turns.sort(key=lambda t: t["at"] or "")
    return turns


async def _load(camera_id: uuid.UUID, db: AsyncSession):
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    capability = (
        await db.execute(
            select(SpeakerCapability).where(SpeakerCapability.camera_id == camera_id)
        )
    ).scalars().first()
    return camera, capability


@router.get("/presets")
async def list_presets():
    """The intents a household picks between, in offer order."""
    return {"presets": presets_mod.listing()}


@router.get("/voices")
async def list_voices():
    """Voices the configured TTS provider can produce."""
    from services.voice.tts import known_kinds
    from shared.app_settings import get_setting

    kind = await get_setting("voice_tts_provider") or "piper"
    default = await get_setting("voice_default")
    return {
        "provider": kind,
        "providers": known_kinds(),
        "default": default,
        # Piper voices are model files rather than a queryable list, so
        # the UI offers the configured default and free text rather than
        # pretending to enumerate something we cannot see.
        "enumerable": False,
    }


@router.get("/cameras/{camera_id}")
async def get_camera_voice(
    camera_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    camera, capability = await _load(camera_id, db)
    return _camera_view(camera, capability)


@router.patch("/cameras/{camera_id}")
async def patch_camera_voice(
    camera_id: uuid.UUID,
    body: VoicePatch,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply a preset, explicit fields, or both.

    The preset lands first and explicit fields override it, so a UI can
    offer "Deterrent, but quieter" in one request without having to
    resolve the preset itself.
    """
    camera, capability = await _load(camera_id, db)
    changes = body.model_dump(exclude_unset=True)

    preset_key = changes.pop("preset", None)
    if preset_key and preset_key != presets_mod.CUSTOM:
        preset = presets_mod.get(preset_key)
        if preset is None:
            raise HTTPException(status_code=400, detail=f"Unknown preset {preset_key!r}")
        for field, value in preset.as_settings().items():
            setattr(camera, field, value)

    for field, value in changes.items():
        setattr(camera, field, value)

    await db.commit()
    await db.refresh(camera)
    return _camera_view(camera, capability)


@router.post("/cameras/{camera_id}/test")
async def test_speak(
    camera_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Say a test phrase through the real path.

    Deliberately not a simulation and deliberately not exempt from the
    guards. A test that bypassed quiet hours would tell a household their
    camera works at a time it will refuse to, which is worse than not
    offering the button.
    """
    from services.voice.speaker import speak

    camera, _ = await _load(camera_id, db)
    outcome = await speak(db, camera, TEST_PHRASE, trigger="manual")
    await db.commit()
    return {
        "spoken": outcome.spoken,
        "status": outcome.status,
        "reason": outcome.reason,
        "detail": outcome.detail,
        "transport": outcome.transport,
        "phrase": TEST_PHRASE,
    }


@router.get("/events")
async def list_speech_events(
    camera_id: uuid.UUID | None = None,
    hours: int = Query(default=168, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """What the house said, and what it decided not to say.

    Suppressed rows are included by default on purpose. A rule quietly
    muted by quiet hours for a month is otherwise indistinguishable from
    one that never fired.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        select(SpeechEvent)
        .where(SpeechEvent.created_at >= since)
        .order_by(SpeechEvent.created_at.desc())
        .limit(limit)
    )
    if camera_id is not None:
        query = query.where(SpeechEvent.camera_id == camera_id)

    rows = (await db.execute(query)).scalars().all()
    return {
        "count": len(rows),
        "events": [
            {
                "id": str(row.id),
                "camera_id": str(row.camera_id),
                "trigger": row.trigger,
                "text": row.text,
                "status": row.status,
                "suppressed_reason": row.suppressed_reason,
                "transport": row.transport,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "played_at": row.played_at.isoformat() if row.played_at else None,
            }
            for row in rows
        ],
    }


# ---- conversation sessions and handoff -----------------------------------


class SayPatch(BaseModel):
    text: str = Field(min_length=1, max_length=240)


def _session_view(row: VoiceSession) -> dict:
    return {
        "id": str(row.id),
        "camera_id": str(row.camera_id),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "ended_reason": row.ended_reason,
        "turns": row.turns,
        "handed_off": row.handed_off_to_user_id is not None,
        "handed_off_at": row.handed_off_at.isoformat() if row.handed_off_at else None,
        # What the camera declined to say. The audit that matters most
        # for a talking agent is not what it said but what it nearly did.
        "refusals": row.refusals or [],
    }


@router.get("/sessions")
async def list_sessions(
    camera_id: uuid.UUID | None = None,
    active: bool = Query(default=False, description="Only sessions still open"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Spoken exchanges, newest first."""
    query = select(VoiceSession).order_by(VoiceSession.started_at.desc()).limit(limit)
    if camera_id is not None:
        query = query.where(VoiceSession.camera_id == camera_id)
    if active:
        query = query.where(VoiceSession.ended_at.is_(None))
    rows = (await db.execute(query)).scalars().all()
    return {"count": len(rows), "sessions": [_session_view(r) for r in rows]}


@router.post("/sessions/{session_id}/handoff")
async def take_over(
    session_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """A person takes the conversation.

    The agent stops immediately, mid-budget. This is the outcome the
    conversation phase was designed around rather than an escape hatch:
    the agent's job was to hold the line politely until exactly this
    happened.
    """
    from services.voice import session as session_mod

    row = await db.get(VoiceSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.ended_at is not None:
        # Not an error. Someone tapping the push after the visitor left
        # should be told plainly, not shown a failure.
        #
        # took_over is whether THIS call did anything; handed_off in the
        # view is the session's state. They differ exactly here, and
        # naming them the same thing let a dict spread silently overwrite
        # one with the other.
        return {
            **_session_view(row),
            "took_over": False,
            "already_ended": True,
            "reason": row.ended_reason,
        }

    row.handed_off_to_user_id = user.id
    row.handed_off_at = datetime.now(timezone.utc)
    row.ended_at = row.handed_off_at
    row.ended_reason = session_mod.ENDED_HANDED_OFF
    await db.commit()
    await db.refresh(row)
    return {**_session_view(row), "took_over": True, "already_ended": False}


@router.post("/sessions/{session_id}/say")
async def say_as_human(
    session_id: uuid.UUID,
    body: SayPatch,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Push-to-talk: speak a person's own words through the camera.

    Deliberately NOT run through the disclosure filter. That filter
    exists to stop a language model leaking a household's own
    information to a stranger; a member of the household deciding what
    to say to their own visitor is not that, and censoring them would be
    both wrong and infuriating.

    The camera's own guards still apply, because they are about the
    hardware and the neighbours rather than about disclosure.
    """
    from services.voice.speaker import speak

    row = await db.get(VoiceSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    camera = await db.get(Camera, row.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Speaking implies taking over; leaving the agent running alongside a
    # human would have them talking over each other.
    if row.ended_at is None:
        from services.voice import session as session_mod

        row.handed_off_to_user_id = user.id
        row.handed_off_at = datetime.now(timezone.utc)
        row.ended_at = row.handed_off_at
        row.ended_reason = session_mod.ENDED_HANDED_OFF

    outcome = await speak(db, camera, body.text, trigger="manual")
    await db.commit()
    return {
        "spoken": outcome.spoken,
        "status": outcome.status,
        "reason": outcome.reason,
        "detail": outcome.detail,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """One exchange, with both halves of the conversation.

    The two sides live in different tables because they are produced by
    different systems: the visitor's words come from the existing STT
    path as Transcript rows, and the camera's words are SpeechEvent rows.
    They are interleaved by time here rather than stored pre-merged, so
    neither side has to know about the other.

    Suppressed lines are included and labelled. What a camera declined to
    say is the more interesting half of the audit, and hiding it would
    make a filtered conversation look like a normal one.
    """
    row = await db.get(VoiceSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    said = (
        await db.execute(
            select(SpeechEvent)
            .where(SpeechEvent.session_id == session_id)
            .order_by(SpeechEvent.created_at)
        )
    ).scalars().all()

    # The visitor's side is bounded by the session window. An open
    # session deliberately has NO upper bound: capping it at "now" would
    # drop a line whose timestamp is a second ahead of this process's
    # clock, and the STT writer and the API do not share one.
    heard_query = (
        select(Transcript)
        .where(Transcript.camera_id == row.camera_id)
        .where(Transcript.started_at >= row.started_at)
        .order_by(Transcript.started_at)
    )
    if row.ended_at is not None:
        heard_query = heard_query.where(Transcript.started_at <= row.ended_at)
    heard = (await db.execute(heard_query)).scalars().all()

    return {**_session_view(row), "transcript": interleave_transcript(heard, said)}


# ---- household voice settings --------------------------------------------


# Keys a household controls for voice as a whole, as opposed to the
# per-camera ones. Kept here rather than in the global settings
# whitelist so the voice surface stays in one file.
_HOUSEHOLD_KEYS = (
    "voice_enabled",
    "voice_conversation_enabled",
    "voice_default",
    "voice_max_volume",
    "voice_quiet_hours_start",
    "voice_quiet_hours_end",
    "voice_session_max_turns",
    "voice_session_max_seconds",
    "voice_may_confirm",
    "voice_never_say",
)

# Disclosure keys a household may turn on, with what each one actually
# permits. Absence, access and impersonation are deliberately absent:
# no setting should be able to make "nobody is home" sayable, and
# offering them here would imply otherwise.
DISCLOSURE_KEYS = [
    {
        "key": "names",
        "label": "Greet people by name",
        "description": (
            "Lets the camera say a household member's name out loud. A "
            "stranger within earshot learns who lives here and who is in."
        ),
    },
    {
        "key": "schedule",
        "label": "Mention when someone will be back",
        "description": (
            "Lets the camera say things like \"back around six\". It tells "
            "a visitor when the house is unoccupied."
        ),
    },
]


class HouseholdVoicePatch(BaseModel):
    voice_enabled: bool | None = None
    voice_conversation_enabled: bool | None = None
    voice_default: str | None = None
    voice_max_volume: int | None = Field(default=None, ge=1, le=100)
    voice_quiet_hours_start: str | None = None
    voice_quiet_hours_end: str | None = None
    voice_session_max_turns: int | None = Field(default=None, ge=1, le=50)
    voice_session_max_seconds: int | None = Field(default=None, ge=10, le=900)
    may_confirm: list[str] | None = None
    never_say: list[str] | None = None


@router.get("/settings")
async def get_voice_settings(
    user: User = Depends(require_admin),
):
    """Household-wide voice settings, and what may be disclosed."""
    from shared.app_settings import DEFAULTS, get_setting

    out = {}
    for key in _HOUSEHOLD_KEYS:
        out[key] = await get_setting(key, DEFAULTS.get(key))
    return {
        **out,
        "disclosure_keys": DISCLOSURE_KEYS,
        # Stated so a UI can say it rather than leaving a household to
        # wonder whether an "allow everything" switch exists somewhere.
        "always_forbidden": [
            "Saying whether anyone is or is not home",
            "Discussing doors, locks, codes or keys",
            "Claiming to be a person",
        ],
    }


@router.patch("/settings")
async def patch_voice_settings(
    body: HouseholdVoicePatch,
    user: User = Depends(require_admin),
):
    """Update household voice settings.

    Unknown disclosure keys are rejected rather than stored. A key that
    does nothing would read as an enabled permission on the settings
    page, which is worse than an error.
    """
    from shared.app_settings import DEFAULTS, get_setting, set_setting

    changes = body.model_dump(exclude_unset=True)

    may_confirm = changes.pop("may_confirm", None)
    if may_confirm is not None:
        known = {entry["key"] for entry in DISCLOSURE_KEYS}
        unknown = [k for k in may_confirm if k not in known]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown disclosure key(s): {', '.join(sorted(unknown))}",
            )
        await set_setting("voice_may_confirm", list(may_confirm))

    never_say = changes.pop("never_say", None)
    if never_say is not None:
        cleaned = [p.strip() for p in never_say if p and p.strip()]
        await set_setting("voice_never_say", cleaned)

    for key, value in changes.items():
        await set_setting(key, value)

    out = {}
    for key in _HOUSEHOLD_KEYS:
        out[key] = await get_setting(key, DEFAULTS.get(key))
    return {**out, "disclosure_keys": DISCLOSURE_KEYS}
