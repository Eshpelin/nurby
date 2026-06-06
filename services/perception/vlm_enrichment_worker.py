"""Idle-time VLM enrichment worker (v2.0).

When the live VLM backlog is empty, spend spare capacity running an extra
pass over already-captured frames whose first caption was thin or missing,
and store it as a versioned, append-only record. The original live caption
is never destroyed; if the new pass is clearly better the reduce step
repoints the observation's authoritative caption at it.

Design: docs/vlm-enrichment-design.md. This is the v2.0 slice. one extra
``attributes`` lens pass, empty-backlog trigger, budget-capped, lowest
priority (it only acts when nothing live is queued and yields between
items). Off by default.

The worker follows the safe DB pattern. it never holds a session open
across the slow VLM call. read (close) -> VLM call (no session) -> write
(fresh session).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import Observation, ObservationVlmPass

logger = logging.getLogger("nurby.perception.vlm_enrichment")

ATTRIBUTES_SYSTEM_PROMPT = (
    "You are reviewing a single security-camera still during quiet hours to "
    "capture detail a fast first pass may have missed. Reply with one or two "
    "plain sentences only. No preamble, no markdown, no bullet points, no "
    "headings. Describe the concrete things you can actually see. people and "
    "what they wear or carry, vehicles with color and type, any readable "
    "text, signage or license plates, notable objects, and time-of-day cues. "
    "Be factual and specific. Do not invent details you cannot see, and do "
    "not guess names."
)


_COLORS = {
    "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown",
    "black", "white", "gray", "grey", "silver", "gold", "tan", "beige",
}
_TIME_OF_DAY = {
    "morning", "afternoon", "evening", "night", "nighttime", "dusk", "dawn",
    "daytime", "midday", "noon", "sunset", "sunrise",
}


def build_attributes(description: str | None, detections: list[dict]) -> dict:
    """Derive structured, searchable fields from the enrichment text and the
    YOLO detections already attached to the observation. Deterministic, no
    extra VLM round-trip. Feeds search and (later) rule filtering.
    """
    desc = description or ""
    low = desc.lower()
    counts: dict[str, int] = {}
    for d in detections or []:
        lbl = d.get("label")
        if lbl:
            counts[lbl] = counts.get(lbl, 0) + 1
    colors = sorted(c for c in _COLORS if re.search(rf"\b{c}\b", low))
    tod = sorted(t for t in _TIME_OF_DAY if re.search(rf"\b{t}\b", low))
    # plate / sign tokens. short uppercase alphanumerics the model read off.
    text_seen = []
    for tok in re.findall(r"\b[A-Z0-9]{4,8}\b", desc):
        if any(ch.isdigit() for ch in tok) and tok not in text_seen:
            text_seen.append(tok)
    return {
        "objects": [{"label": k, "count": v} for k, v in sorted(counts.items())],
        "people_count": counts.get("person", 0),
        "colors": colors,
        "time_of_day": tod,
        "text_seen": text_seen[:6],
        "source": "attributes-pass-v1",
    }


class EnrichmentManager:
    """Background loop that enriches thin observations when idle."""

    def __init__(self) -> None:
        self._vlm = None  # lazy VLMClient
        self._redis = None

    async def _enabled(self) -> bool:
        return bool(await get_setting("vlm_enrichment_enabled", False))

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            from shared.config import settings
            self._redis = aioredis.from_url(settings.redis_url)
        return self._redis

    # ---- idle + budget gates ----------------------------------------

    async def _backlog_empty(self) -> bool:
        """True when no camera has any live VLM work queued.

        Reads the real Redis backlog lists (nurby:vlm_pending:*) rather than
        the in-memory EMA stats, which go stale the moment the pipeline
        stops updating them (e.g. a camera goes offline). Fails closed. if
        we cannot tell, assume not empty so enrichment never competes with
        live work.
        """
        try:
            r = await self._get_redis()
            keys = await r.keys("nurby:vlm_pending:*")
            for k in keys:
                if int(await r.llen(k) or 0) > 0:
                    return False
            return True
        except Exception:
            logger.debug("backlog check failed, assuming not empty", exc_info=True)
            return False

    def _usage_key(self) -> str:
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        return f"nurby:vlm_enrich_usage:{hour}"

    async def _within_budget(self, budget_minutes: int) -> bool:
        if budget_minutes <= 0:
            return False  # 0 disables enrichment work entirely
        try:
            r = await self._get_redis()
            used = float(await r.get(self._usage_key()) or 0.0)
        except Exception:
            return True  # fail open. a metering hiccup should not stall enrichment
        return used < budget_minutes * 60

    async def _record_usage(self, seconds: float) -> None:
        try:
            r = await self._get_redis()
            key = self._usage_key()
            await r.incrbyfloat(key, max(0.0, seconds))
            await r.expire(key, 7200)
        except Exception:
            logger.debug("enrichment budget write failed", exc_info=True)

    # ---- candidate selection ----------------------------------------

    async def _next_candidate(self, max_passes: int, min_len: int,
                              cooldown_s: int, retention_days: int):
        """Pick the most-deficient observation that still has a frame on
        disk. Thinnest and oldest first, so a quiet night lifts the worst
        records. Returns (id, thumbnail_path, detections, pass_count) or None.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        recool = datetime.now(timezone.utc) - timedelta(seconds=cooldown_s)
        async with async_session() as db:
            rows = (await db.execute(
                select(Observation)
                .where(Observation.thumbnail_path.is_not(None))
                .where(Observation.started_at >= cutoff)
                .where(Observation.enrich_pass_count < max_passes)
                .where(
                    (Observation.vlm_description.is_(None))
                    | (Observation.vlm_late.is_(True))
                    | (func.length(Observation.vlm_description) < min_len)
                )
                .where(
                    (Observation.last_enriched_at.is_(None))
                    | (Observation.last_enriched_at < recool)
                )
                .order_by(
                    Observation.enrich_pass_count.asc(),
                    Observation.started_at.asc(),
                )
                .limit(1)
            )).scalars().all()
            if not rows:
                return None
            o = rows[0]
            return (o.id, o.thumbnail_path,
                    (o.object_detections or {}).get("objects", []),
                    o.enrich_pass_count, o.vlm_description)

    # ---- one enrichment pass ----------------------------------------

    async def _enrich_one(self, min_len: int) -> bool:
        from services.perception.vlm import get_active_provider

        provider = await get_active_provider()
        if provider is None:
            return False

        cand = await self._next_candidate(
            max_passes=int(await get_setting("vlm_enrichment_max_passes", 5)),
            min_len=min_len,
            cooldown_s=int(await get_setting("vlm_enrichment_cooldown_seconds", 3600)),
            retention_days=int(await get_setting("vlm_enrichment_retention_days", 30)),
        )
        if cand is None:
            return False
        obs_id, thumb, detections, pass_count, current_desc = cand

        frame = _load_frame(thumb)
        if frame is None:
            # No usable frame. bump last_enriched_at so we do not spin on it.
            await self._touch(obs_id)
            return True

        if self._vlm is None:
            from services.perception.vlm import VLMClient
            self._vlm = VLMClient()

        t0 = time.monotonic()
        try:
            text = await self._vlm.describe(
                frame, detections, provider,
                system_prompt=ATTRIBUTES_SYSTEM_PROMPT,
                max_tokens=160,
            )
        except Exception:
            logger.debug("enrichment VLM call failed for %s", obs_id, exc_info=True)
            await self._touch(obs_id)
            return True
        await self._record_usage(time.monotonic() - t0)

        if not text or not text.strip():
            await self._touch(obs_id)
            return True
        text = text.strip()

        attributes = build_attributes(text, detections)
        # If this pass will become authoritative, regenerate the search
        # embedding from the enriched text BEFORE opening the write session,
        # so the (possibly network-bound) embedding call never holds a DB
        # connection open. Mirrors how the live VLM patch feeds search.
        embedding = None
        if self.should_promote(current_desc, min_len):
            embedding = await self._embed(text)

        await self._store_pass(obs_id, pass_count, provider.name,
                               provider.default_model, text, current_desc,
                               min_len, attributes, embedding)
        logger.info("enriched observation %s (pass %d). %s",
                    obs_id, pass_count + 1, text[:80])
        return True

    async def _embed(self, text: str):
        try:
            from services.search.embeddings import (
                generate_embedding, get_embedding_provider,
            )
            ep = await get_embedding_provider()
            return await generate_embedding(text, ep)
        except Exception:
            logger.debug("enrichment embedding failed", exc_info=True)
            return None

    @staticmethod
    def should_promote(current_desc: str | None, min_len: int) -> bool:
        """v2.0 reduce rule. promote a new pass to authoritative only when
        the existing caption is missing or thin. otherwise the new pass is
        appended as a non-authoritative layer."""
        return (not current_desc) or len(current_desc.strip()) < min_len

    async def _store_pass(self, obs_id: uuid.UUID, prev_count: int,
                          provider_name: str | None, model: str | None,
                          text: str, current_desc: str | None, min_len: int,
                          attributes: dict | None = None,
                          embedding=None) -> None:
        new_no = prev_count + 1
        promote = self.should_promote(current_desc, min_len)
        async with async_session() as db:
            if promote:
                await db.execute(
                    update(ObservationVlmPass)
                    .where(ObservationVlmPass.observation_id == obs_id)
                    .where(ObservationVlmPass.authoritative.is_(True))
                    .values(authoritative=False)
                )
            db.add(ObservationVlmPass(
                observation_id=obs_id, pass_no=new_no, lens="attributes",
                prompt_version="v1", provider_name=provider_name, model=model,
                description=text, attributes=attributes, authoritative=promote,
            ))
            obs = await db.get(Observation, obs_id)
            if obs is not None:
                obs.enrich_pass_count = new_no
                obs.last_enriched_at = datetime.now(timezone.utc)
                if promote:
                    # Preserve the original once, then repoint authoritative
                    # and refresh the search embedding so semantic search
                    # reflects the enriched caption.
                    if obs.primary_vlm_description is None and obs.vlm_description:
                        obs.primary_vlm_description = obs.vlm_description
                    obs.vlm_description = text
                    if embedding is not None:
                        obs.description_embedding = embedding
            await db.commit()

    async def _touch(self, obs_id: uuid.UUID) -> None:
        async with async_session() as db:
            obs = await db.get(Observation, obs_id)
            if obs is not None:
                obs.last_enriched_at = datetime.now(timezone.utc)
                await db.commit()

    # ---- main loop --------------------------------------------------

    async def run(self) -> None:
        logger.info("VLM enrichment worker started (idle backfill)")
        while True:
            try:
                poll = int(await get_setting("vlm_enrichment_idle_poll_seconds", 30))
                if not await self._enabled():
                    await asyncio.sleep(max(30, poll))
                    continue
                budget = int(await get_setting("vlm_enrichment_budget_minutes_per_hour", 20))
                min_len = int(await get_setting("vlm_enrichment_min_caption_len", 40))
                if not await self._backlog_empty() or not await self._within_budget(budget):
                    await asyncio.sleep(poll)
                    continue
                did = await self._enrich_one(min_len)
                # Yield between items so a live frame always preempts us.
                await asyncio.sleep(1 if did else poll)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("enrichment loop error")
                await asyncio.sleep(30)


def _load_frame(path: str | None):
    if not path:
        return None
    try:
        import cv2
        if not os.path.exists(path):
            return None
        return cv2.imread(path)
    except Exception:
        return None
