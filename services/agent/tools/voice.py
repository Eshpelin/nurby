"""Speaking out of a camera. The one tool with a physical side effect.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from services.agent.tools import _common
from shared.models import (
    Camera,
    Person,
)

_SPEAK_ON_CAMERA_SCHEMA = {
    "type": "object",
    "properties": {
        "camera_id": {
            "type": "string",
            "description": "Which camera should say it.",
        },
        "text": {
            "type": "string",
            "description": (
                "What to say, in one or two short sentences of plain "
                "speech. It is read aloud to whoever is standing there."
            ),
        },
    },
    "required": ["camera_id", "text"],
    "additionalProperties": False,
}


async def speak_on_camera(ctx: dict, *, camera_id: str, text: str) -> dict:
    """Say something out loud through a camera's speaker.

    The first tool in this registry that reaches out of the database and
    into a room, and the one that needs the most care, because THIS agent
    is the dangerous one to hand a speaker to. The doorbell agent has no
    tools and no household context; this one has the orientation block,
    every tool result it has gathered, and a question from a household
    member. All of that is exactly what must not be read aloud to
    whoever happens to be standing in front of the camera.

    So the same disclosure filter that guards the doorbell applies here,
    with the household's own names loaded, and the household has to turn
    the tool on before it exists at all.
    """
    from services.voice.disclosure import safe_reply
    from services.voice.speaker import speak
    from shared.app_settings import get_setting

    db = ctx["db"]

    if not bool(await get_setting("voice_agent_tool_enabled", False)):
        return {
            "error": "not_enabled",
            "message": (
                "speaking from the assistant is turned off for this "
                "household. Rules can still speak."
            ),
        }

    try:
        camera_uuid = uuid.UUID(str(camera_id))
    except (ValueError, TypeError):
        return {"error": "invalid_camera", "message": f"not a camera id: {camera_id!r}"}

    allowed = await _common.accessible_camera_ids(ctx["user"], db)
    if camera_uuid not in allowed:
        # Same boundary every other tool honours. A camera the asker
        # cannot see is not one they can make talk.
        return {"error": "no_access", "message": "no such camera"}

    camera = await db.get(Camera, camera_uuid)
    if camera is None:
        return {"error": "no_such_camera", "message": "no such camera"}

    names = [
        n for n in (
            await db.execute(select(Person.display_name))
        ).scalars().all() if n
    ]
    may_confirm = await get_setting("voice_may_confirm") or []
    never_say = await get_setting("voice_never_say") or []

    line, verdict = safe_reply(
        text,
        household_names=names,
        never_say=list(never_say),
        may_confirm=list(may_confirm),
    )

    outcome = await speak(
        db, camera, line,
        trigger="agent",
        agent_run_id=ctx.get("run_id"),
    )

    result = {
        "spoken": outcome.spoken,
        "said": line if outcome.spoken else None,
        "status": outcome.status,
        "camera_name": camera.name,
    }
    if not verdict.allowed:
        # Told plainly so the agent reports what happened rather than
        # claiming it said what it drafted.
        result["rewritten"] = True
        result["reason"] = verdict.reason
        result["note"] = (
            "your wording would have disclosed something about the "
            "household, so a neutral line was said instead. Tell the user "
            "this happened."
        )
    if not outcome.spoken:
        result["reason"] = outcome.reason
        result["note"] = outcome.detail or "the camera did not play it"
    return result


