"""Shared helpers for the agent tools: window clamps, uuid coercion,
thumbnail urls, alias lookups and the widen ladder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select

# Every tool reaches the access filter through this module, so a test or
# embedding application can replace this seam in one place.  Delegate at call
# time rather than capturing the function object at import time: legacy
# integrations that patch services.agent.access remain effective as well.
from services.agent import access as _agent_access
from shared.models import (
    Journey,
    Person,
)
from shared.subject_keys import subject_key_has

logger = logging.getLogger("nurby.agent.tools")


# ── Helpers ───────────────────────────────────────────────────────────


async def accessible_camera_ids(user, db):
    return await _agent_access.accessible_camera_ids(user, db)


_MAX_WINDOW_HOURS = 720  # 30 days, matches docs/agent-design.md
_MIN_WINDOW_HOURS = 1


# The escalation ladder behind the prompt's "widen-then-fail" rule. Kept in
# code because a small local model reads the instruction and skips it, then
# answers "not seen" off one empty 24h window (issue #128).
WIDEN_LADDER = (168, 720)  # 7 days, then 30 days


def widen_ladder(hours: int) -> list[int]:
    """Windows to retry, widest last, for a search that found nothing at
    ``hours``. Empty when the caller already asked for the widest window.
    Pure, for tests."""
    return [h for h in WIDEN_LADDER if h > hours]


def _clamp_hours(hours: int | None) -> int:
    if hours is None:
        return 24
    try:
        h = int(hours)
    except (TypeError, ValueError):
        raise ValueError("hours must be an integer")
    if h < _MIN_WINDOW_HOURS:
        raise ValueError(f"hours must be >= {_MIN_WINDOW_HOURS}")
    if h > _MAX_WINDOW_HOURS:
        return _MAX_WINDOW_HOURS
    return h


def _clamp_limit(limit: int | None, default: int = 20, max_: int = 100) -> int:
    if limit is None:
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return 1
    return min(n, max_)


def _to_uuid_set(values: list[str] | None) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for v in values or []:
        try:
            out.add(uuid.UUID(str(v)))
        except (TypeError, ValueError):
            continue
    return out


def _infer_role(name: str | None, location: str | None) -> str:
    """Keyword classifier for camera roles. Matches the buckets in
    docs/agent-design.md section 9.2."""
    haystack = f"{(name or '').lower()} {(location or '').lower()}"
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("entry", ("door", "entry", "front door", "porch", "gate")),
        ("kitchen", ("kitchen",)),
        ("garage", ("garage",)),
        ("outdoor", ("yard", "outdoor", "backyard", "driveway")),
        ("nursery", ("baby", "nursery")),
        ("living", ("living", "family")),
        ("bedroom", ("bedroom", "bed room")),
        ("bathroom", ("bathroom", "bath")),
        ("office", ("office",)),
    ]
    for role, needles in rules:
        for n in needles:
            if n in haystack:
                return role
    return "other"


async def _embed_query(text: str) -> list[float] | None:
    """Best-effort embedding generation. None when unavailable so the
    caller falls back to keyword-only search."""
    try:
        from services.search.embeddings import generate_embedding, get_embedding_provider

        provider = await get_embedding_provider()
        embedding = await generate_embedding(text, provider)
        if any(v != 0.0 for v in embedding):
            return embedding
    except Exception:
        logger.debug("embedding generation failed", exc_info=True)
    return None


def _thumbnail_url(thumbnail_path: str | None) -> str | None:
    if not thumbnail_path:
        return None
    # The frontend resolves these via /api/thumbnails/{path}. We return
    # the bare relative path so the agent driver / UI can mount it
    # under whatever base url the deployment uses.
    return thumbnail_path


def _subject_names(subject_key: str | None) -> list[str]:
    """Split a Journey.subject_key into its component names/labels.

    Journeys key persons by a comma-joined set of display NAMES (see
    incident_tracker.compute_signature), never a person_id.
    """
    return [n.strip() for n in (subject_key or "").split(",") if n.strip()]


async def _person_journeys(
    db,
    display_name: str,
    *,
    since: datetime | None = None,
    order_desc: bool = True,
    limit: int | None = None,
) -> list:
    """Return Journey rows for a Person, matched by display-name signature.

    Journey has no person_id column. persons are identified by
    subject_kind == 'person' plus their display name living inside the
    comma-joined subject_key. A coarse SQL ILIKE prefilters, then an
    exact-token check drops coincidental substring hits ("Ann" must not
    match a journey for "Anna").
    """
    stmt = (
        select(Journey)
        .where(Journey.subject_kind == "person")
        .where(subject_key_has(Journey.subject_key, display_name))
    )
    if since is not None:
        stmt = stmt.where(Journey.last_seen_at >= since)
    stmt = stmt.order_by(
        Journey.last_seen_at.desc() if order_desc else Journey.started_at.asc()
    )
    rows = (await db.execute(stmt)).scalars().all()
    out = [j for j in rows if display_name in _subject_names(j.subject_key)]
    return out[:limit] if limit else out


async def _alias_map(db) -> dict[str, str]:
    """Load canonical display_name -> household nickname for all persons.

    One cheap query per tool call. Used to rewrite canonical names pulled
    from Journey.subject_key or stored detections into the household
    nickname before the result reaches the model.
    """
    rows = (await db.execute(select(Person.display_name, Person.nickname))).all()
    return {
        dn: nk.strip()
        for dn, nk in rows
        if dn and isinstance(nk, str) and nk.strip()
    }


def _seg_camera_id(seg) -> uuid.UUID | None:
    """Parse a Journey segment's camera_id into a UUID, or None.

    Journey.segments entries are dicts shaped like
    {camera_id, camera_name, location_label, incident_id, started_at,
    last_seen_at, occurrence_count, peak_observation_id}. There is no
    ``cameras`` attribute and segments key the camera as ``camera_id``,
    not ``id``.
    """
    if not isinstance(seg, dict):
        return None
    try:
        return uuid.UUID(str(seg.get("camera_id")))
    except (ValueError, TypeError):
        return None


# ── Tool 1. query_observations ────────────────────────────────────────

