"""Persistent grounding cache + teach-the-index tag store.

Backed by the ``grounding_results`` table (one row per observation+prompt+
model_revision). Two jobs in one (design §7): skip re-inference on a repeat
scan, and make a once-located term instantly searchable next time. Safe w.r.t.
rules. the engine never re-evaluates stored rows (§7.1).

Each function manages its own short DB session (mirrors shared.app_settings),
so callers in the scan loop never hold a connection open across a slow GPU
call.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

logger = logging.getLogger("nurby.grounding.cache")


def prompt_hash(prompt: str) -> str:
    """Stable hash of the normalized prompt (the lookup key component)."""
    return hashlib.sha256((prompt or "").strip().lower().encode()).hexdigest()


async def get_cached_grounding(observation_id, prompt: str, model_revision: str) -> dict | None:
    """Return the cached result for this (observation, prompt, revision), or
    None on a miss. Shape: {found, corroborated, count, boxes}."""
    try:
        obs_uuid = uuid.UUID(str(observation_id))
    except (ValueError, TypeError):
        return None
    try:
        from sqlalchemy import select

        from shared.database import async_session
        from shared.models import GroundingResult

        async with async_session() as db:
            row = (
                await db.execute(
                    select(GroundingResult).where(
                        GroundingResult.observation_id == obs_uuid,
                        GroundingResult.prompt_hash == prompt_hash(prompt),
                        GroundingResult.model_revision == model_revision,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "found": row.found,
                "corroborated": row.corroborated,
                "count": row.count,
                "boxes": row.boxes or [],
            }
    except Exception:
        # A cache miss must never sink a scan. degrade to "no cache".
        logger.debug("grounding cache read failed", exc_info=True)
        return None


async def store_grounding(
    observation_id,
    prompt: str,
    model_revision: str,
    *,
    found: bool,
    corroborated: bool,
    boxes: list,
) -> None:
    """Upsert a grounding result. Best-effort. a write failure (or a race on
    the unique key) is swallowed so it never breaks the scan."""
    try:
        obs_uuid = uuid.UUID(str(observation_id))
    except (ValueError, TypeError):
        return
    try:
        from sqlalchemy import select

        from shared.database import async_session
        from shared.models import GroundingResult

        ph = prompt_hash(prompt)
        async with async_session() as db:
            existing = (
                await db.execute(
                    select(GroundingResult).where(
                        GroundingResult.observation_id == obs_uuid,
                        GroundingResult.prompt_hash == ph,
                        GroundingResult.model_revision == model_revision,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.found = found
                existing.corroborated = corroborated
                existing.count = len(boxes)
                existing.boxes = boxes
            else:
                db.add(
                    GroundingResult(
                        observation_id=obs_uuid,
                        prompt=(prompt or "").strip(),
                        prompt_hash=ph,
                        model_revision=model_revision,
                        found=found,
                        corroborated=corroborated,
                        count=len(boxes),
                        boxes=boxes,
                    )
                )
            await db.commit()
    except Exception:
        logger.debug("grounding cache write failed", exc_info=True)
