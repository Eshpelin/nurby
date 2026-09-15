"""VLM analysis of a clip or a frame. The expensive tools.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    logger,
)
from shared.models import (
    Observation,
)

_SUMMARIZE_WINDOW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hours": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_WINDOW_HOURS,
            "default": 168,
            "description": (
                "Look-back window in hours. Default 168 (7 days), max 720 "
                "(30 days)."
            ),
        },
        "focus": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Optional free-text topic the final narrative weights "
                "toward, e.g. 'front door' or 'the dog'."
            ),
        },
        "chunk_by": {
            "type": "string",
            "enum": ["auto", "hour", "day", "incident", "journey"],
            "default": "auto",
            "description": (
                "Chunk boundary strategy. auto picks hourly buckets for "
                "windows <=48h and daily buckets for longer windows."
            ),
        },
        "provider_id": {"type": "string", "format": "uuid"},
    },
}


async def summarize_window(
    ctx: dict,
    *,
    hours: int = 168,
    focus: str | None = None,
    chunk_by: str = "auto",
    provider_id: str | None = None,
) -> dict:
    """Map-reduce summary of a LONG window (multiple days / weeks).

    Thin wrapper over services.agent.summarizer.summarize_window. The
    summarizer chunks the window, builds a deterministic zero-LLM
    mini-summary per chunk, then folds them into one narrative with a
    single budget-gated LLM reduce step. Use for 'summarize the last
    week/month'. For a single day use summarize_activity (cheaper).
    """
    from services.agent.summarizer import summarize_window as _summarize_window

    return await _summarize_window(
        ctx,
        hours=hours,
        focus=focus,
        chunk_by=chunk_by,
        provider_id=provider_id,
    )


# ── Tool 4. analyze_clip ──────────────────────────────────────────────


_ANALYZE_CLIP_SCHEMA = {
    "type": "object",
    "required": ["camera_id", "time_from", "time_to", "question"],
    "additionalProperties": False,
    "properties": {
        "camera_id": {"type": "string", "format": "uuid"},
        "time_from": {"type": "string", "format": "date-time"},
        "time_to": {"type": "string", "format": "date-time"},
        "question": {"type": "string", "minLength": 1, "maxLength": 500},
        "provider_id": {"type": "string", "format": "uuid"},
    },
}


def _analyzer_not_ready(message: str | None = None) -> dict:
    return {
        "answer": None,
        "confidence": 0.0,
        "frames_analyzed": 0,
        "cached": False,
        "cost_cents": 0,
        "thumbnails_url_base": None,
        "vlm_call_id": None,
        "error": "analyzer_not_ready",
        "message": message
        or "VLM analyzer module not yet deployed; this is expected during build wave 1",
    }


async def _check_user_budget(ctx: dict) -> tuple[bool, str | None]:
    """Hook into Wave 1A's budget enforcement. Returns (ok, reason).

    Wave 1A provides ``services.agent.budget.check_user_budget``. If the
    module isn't present we fail open since the analyzer module also
    isn't present and will short-circuit before any real spend.
    """
    try:
        from services.agent.budget import check_user_budget  # type: ignore
    except Exception:
        return True, None
    try:
        return await check_user_budget(ctx)
    except Exception:
        logger.debug("budget check raised; allowing", exc_info=True)
        return True, None


async def analyze_clip(
    ctx: dict,
    *,
    camera_id: str,
    time_from: str,
    time_to: str,
    question: str,
    provider_id: str | None = None,
) -> dict:
    """Run a VLM against a video clip over a time window.

    Expensive. Wave 2 prompt instructs the LLM to call query_observations
    first. This call validates inputs (camera access, window length),
    checks the per-user budget, and delegates to the Wave 1C analyzer.
    """
    user = ctx["user"]
    db = ctx["db"]

    try:
        cam_uuid = uuid.UUID(camera_id)
    except (TypeError, ValueError):
        return {"error": "invalid_camera_id", "message": "camera_id must be a UUID"}

    try:
        t_from = datetime.fromisoformat(time_from.replace("Z", "+00:00"))
        t_to = datetime.fromisoformat(time_to.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return {"error": "invalid_time", "message": "time_from / time_to must be ISO datetimes"}
    if t_to <= t_from:
        return {"error": "invalid_window", "message": "time_to must be after time_from"}

    # Clip-length ceiling per AppSetting. Defaults to 5 minutes when
    # the key is missing; documented at agent_max_clip_minutes.
    try:
        from shared.app_settings import get_setting

        max_minutes = int(await get_setting("agent_max_clip_minutes", 5))
    except Exception:
        max_minutes = 5
    if (t_to - t_from).total_seconds() > max_minutes * 60:
        return {
            "error": "window_too_large",
            "message": f"clip window exceeds agent_max_clip_minutes={max_minutes}",
        }

    allowed = await _common.accessible_camera_ids(user, db)
    if cam_uuid not in allowed:
        return {"error": "camera_access_denied", "message": "no access to this camera"}

    ok, reason = await _check_user_budget(ctx)
    if not ok:
        return {"error": "budget_exceeded", "message": reason or "user budget exhausted"}

    try:
        from services.agent.analyzer import analyze_clip_target  # type: ignore
    except Exception:
        return _analyzer_not_ready()

    try:
        provider_uuid = uuid.UUID(provider_id) if provider_id else None
    except (TypeError, ValueError):
        provider_uuid = None

    try:
        return await analyze_clip_target(
            ctx,
            camera_id=cam_uuid,
            time_from=t_from,
            time_to=t_to,
            question=question,
            provider_id=provider_uuid,
        )
    except Exception as exc:
        logger.exception("analyze_clip_target raised")
        return {
            "error": "analyzer_failed",
            "message": f"{type(exc).__name__}: {exc}",
            "answer": None,
            "confidence": 0.0,
            "frames_analyzed": 0,
            "cached": False,
            "cost_cents": 0,
        }


# ── Tool 5. analyze_frame ─────────────────────────────────────────────


_ANALYZE_FRAME_SCHEMA = {
    "type": "object",
    "required": ["observation_id", "question"],
    "additionalProperties": False,
    "properties": {
        "observation_id": {"type": "string", "format": "uuid"},
        "question": {"type": "string", "minLength": 1, "maxLength": 500},
        "provider_id": {"type": "string", "format": "uuid"},
    },
}


async def analyze_frame(
    ctx: dict,
    *,
    observation_id: str,
    question: str,
    provider_id: str | None = None,
) -> dict:
    """Run a VLM against a single Observation thumbnail. Cheapest VLM
    path. Use after query_observations returned a candidate row that
    needs a closer look."""
    user = ctx["user"]
    db = ctx["db"]

    try:
        obs_uuid = uuid.UUID(observation_id)
    except (TypeError, ValueError):
        return {"error": "invalid_observation_id", "message": "observation_id must be a UUID"}

    obs = await db.get(Observation, obs_uuid)
    if obs is None:
        return {"error": "observation_not_found", "message": "no such observation"}

    allowed = await _common.accessible_camera_ids(user, db)
    if obs.camera_id not in allowed:
        return {"error": "camera_access_denied", "message": "no access to this camera"}

    ok, reason = await _check_user_budget(ctx)
    if not ok:
        return {"error": "budget_exceeded", "message": reason or "user budget exhausted"}

    try:
        from services.agent.analyzer import analyze_frame_target  # type: ignore
    except Exception:
        ready = _analyzer_not_ready()
        ready["frames_analyzed"] = 1 if obs.thumbnail_path else 0
        return ready

    try:
        provider_uuid = uuid.UUID(provider_id) if provider_id else None
    except (TypeError, ValueError):
        provider_uuid = None

    try:
        return await analyze_frame_target(
            ctx,
            observation_id=obs_uuid,
            question=question,
            provider_id=provider_uuid,
        )
    except Exception as exc:
        logger.exception("analyze_frame_target raised")
        return {
            "error": "analyzer_failed",
            "message": f"{type(exc).__name__}: {exc}",
            "answer": None,
            "confidence": 0.0,
            "frames_analyzed": 0,
            "cached": False,
            "cost_cents": 0,
        }


