"""Observation and journey search. The two broadest read tools.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String as SAString
from sqlalchemy import and_, cast, or_, select

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    WIDEN_LADDER,
    _alias_map,
    _clamp_hours,
    _clamp_limit,
    _thumbnail_url,
    _to_uuid_set,
    widen_ladder,
)
from shared.models import (
    Camera,
    Journey,
    Observation,
    Person,
)
from shared.person_alias import alias_names
from shared.subject_keys import subject_key_has

_QUERY_OBSERVATIONS_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 500},
        "hours": {"type": "integer", "minimum": 1, "maximum": _MAX_WINDOW_HOURS, "default": 24},
        "camera_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
        },
        "person_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
        },
        "labels": {
            "type": "array",
            "items": {"type": "string"},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    },
}


async def query_observations(
    ctx: dict,
    *,
    query: str,
    hours: int = 24,
    camera_ids: list[str] | None = None,
    person_ids: list[str] | None = None,
    labels: list[str] | None = None,
    limit: int = 20,
) -> dict:
    """Search past camera observations.

    Combines pgvector cosine similarity over Observation.description_embedding
    with structured filters. The result list is bounded by ``limit``
    (clamped 1..100) and the time window is bounded by ``hours``
    (clamped 1..720). Every result is filtered through
    accessible_camera_ids before returning.
    """
    user = ctx["user"]
    db = ctx["db"]

    requested_hours = _clamp_hours(hours)
    limit = _clamp_limit(limit, default=20, max_=100)

    allowed = await _common.accessible_camera_ids(user, db)
    if not allowed:
        return {"count": 0, "observations": []}

    requested_cam_ids = _to_uuid_set(camera_ids)
    if requested_cam_ids:
        effective_cams = requested_cam_ids & allowed
        if not effective_cams:
            return {"count": 0, "observations": []}
    else:
        effective_cams = allowed

    requested_persons = _to_uuid_set(person_ids)
    # Embedded once and reused across widened retries: the text does not
    # change, only the window does.
    query_embedding = await _common._embed_query(query) if query else None
    amap = await _alias_map(db)

    async def _search(window_hours: int) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        filters = [
            Observation.started_at >= cutoff,
            Observation.camera_id.in_(effective_cams),
        ]

        if requested_persons:
            # Person UUIDs are embedded in the person_detections JSON blob
            # as the ``person_id`` field on each detected face. We match via
            # a substring scan since the column is JSON, not JSONB indexed.
            person_conditions = [
                cast(Observation.person_detections, SAString).ilike(f"%{str(pid)}%")
                for pid in requested_persons
            ]
            filters.append(or_(*person_conditions))

        if labels:
            label_conditions = []
            for lbl in labels:
                if not lbl:
                    continue
                label_conditions.append(
                    cast(Observation.object_detections, SAString).ilike(f"%\"{lbl}\"%")
                )
            if label_conditions:
                filters.append(or_(*label_conditions))

        rows: list[tuple[Observation, float | None]] = []

        if query_embedding is not None:
            vec_filters = list(filters) + [Observation.description_embedding.isnot(None)]
            cosine = Observation.description_embedding.cosine_distance(query_embedding)
            stmt = (
                select(Observation, cosine.label("distance"))
                .where(and_(*vec_filters))
                .order_by(cosine.asc())
                .limit(limit * 2)
            )
            result = await db.execute(stmt)
            for obs, dist in result.all():
                rows.append((obs, float(dist) if dist is not None else None))
            # threshold low-similarity matches
            rows = [(o, d) for (o, d) in rows if d is None or d <= 0.85][:limit]

        if not rows:
            # Keyword fallback. ILIKE the vlm_description so even a
            # missing-embedding deployment returns sensible results.
            kw = query.strip()
            kw_filter = (
                Observation.vlm_description.ilike(f"%{kw}%") if kw else None
            )
            stmt = (
                select(Observation)
                .where(and_(*filters, kw_filter) if kw_filter is not None else and_(*filters))
                .order_by(Observation.started_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            rows = [(o, None) for o in result.scalars().all()]

        observations: list[Observation] = [o for o, _ in rows]

        # Resolve camera names in one shot.
        camera_map: dict[uuid.UUID, str] = {}
        if observations:
            cam_rows = await db.execute(
                select(Camera.id, Camera.name).where(
                    Camera.id.in_({o.camera_id for o in observations})
                )
            )
            camera_map = {cid: cname for cid, cname in cam_rows.all()}

        out_rows: list[dict[str, Any]] = []
        for (obs, dist) in rows:
            if obs.camera_id not in allowed:
                # Belt-and-braces. effective_cams should already enforce
                # this but a stale cache or race could slip a row through.
                continue
            person_names: list[str] = []
            pd = obs.person_detections or {}
            for face in pd.get("faces", []) or []:
                name = face.get("person_name")
                if name:
                    person_names.append(name)
            person_names = alias_names(person_names, amap)
            out_rows.append(
                {
                    "id": str(obs.id),
                    "camera_id": str(obs.camera_id),
                    "camera_name": camera_map.get(obs.camera_id, "Unknown"),
                    "timestamp": obs.started_at.isoformat(),
                    "description": obs.vlm_description,
                    "thumbnail_url": _thumbnail_url(obs.thumbnail_path),
                    "detections": obs.object_detections,
                    "person_names": person_names,
                    "similarity_score": (1.0 - dist) if dist is not None else None,
                }
            )
        return out_rows

    out_rows = await _search(requested_hours)

    # Widen-then-fail, enforced here rather than asked for in the prompt.
    widened_to: int | None = None
    if not out_rows:
        for wider in widen_ladder(requested_hours):
            out_rows = await _search(wider)
            if out_rows:
                widened_to = wider
                break

    payload: dict[str, Any] = {"count": len(out_rows), "observations": out_rows}
    if widened_to is not None:
        payload["requested_hours"] = requested_hours
        payload["widened_to"] = widened_to
        payload["note"] = (
            f"Nothing matched in the requested {requested_hours}h window. These "
            f"rows come from a widened {widened_to}h window. Lead your answer "
            f"with the fact that there was nothing in the {requested_hours}h "
            "window, then give what you did find and when."
        )
    elif not out_rows and widen_ladder(requested_hours):
        payload["requested_hours"] = requested_hours
        payload["searched_up_to_hours"] = WIDEN_LADDER[-1]
        payload["note"] = (
            f"Nothing matched in the requested {requested_hours}h window, and "
            f"nothing matched after widening to {WIDEN_LADDER[-1]}h either. "
            "Absence is now well evidenced; you may say there is no record."
        )
    return payload


# ── Tool 2. get_journeys ──────────────────────────────────────────────


_GET_JOURNEYS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "person_id": {"type": "string", "format": "uuid"},
        "person_name": {"type": "string", "minLength": 1, "maxLength": 255},
        "hours": {"type": "integer", "minimum": 1, "maximum": _MAX_WINDOW_HOURS, "default": 24},
        "camera_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    },
}


async def get_journeys(
    ctx: dict,
    *,
    person_id: str | None = None,
    person_name: str | None = None,
    hours: int = 24,
    camera_ids: list[str] | None = None,
    limit: int = 20,
) -> dict:
    """Cross-camera Person sighting sessions.

    A Journey row represents a contiguous period a Person was visible
    across one or more cameras. When ``person_name`` is provided and
    resolves to more than one Person, the response sets
    ``disambiguation`` and returns an empty ``journeys`` list. The
    Wave 2 driver convention is to surface that disambiguation back to
    the user (or pick the highest-sighting candidate if the context
    makes it obvious).
    """
    user = ctx["user"]
    db = ctx["db"]

    hours = _clamp_hours(hours)
    limit = _clamp_limit(limit, default=20, max_=100)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    allowed = await _common.accessible_camera_ids(user, db)
    if not allowed:
        return {"journeys": []}

    requested_cams = _to_uuid_set(camera_ids)
    effective_cams = (requested_cams & allowed) if requested_cams else allowed
    if not effective_cams:
        return {"journeys": []}

    # ── Subject resolution ──────────────────────────────────────────
    # Person journeys key ``subject_key`` by a comma-joined,
    # alphabetically-sorted set of display names (see
    # incident_tracker.compute_signature), NOT by person_id. So a
    # person filter resolves to a display name and matches the
    # name-signature, not a UUID.
    resolved_name: str | None = None
    if person_id:
        try:
            pid = uuid.UUID(person_id)
        except (TypeError, ValueError):
            return {"journeys": [], "error": "invalid person_id"}
        resolved_name = (
            await db.execute(select(Person.display_name).where(Person.id == pid))
        ).scalars().first()
        if not resolved_name:
            return {"journeys": [], "error": "person not found"}
    elif person_name:
        like = f"%{person_name.strip()}%"
        # Match the typed name on canonical display_name or household
        # nickname. resolved_name stays canonical because Journey
        # subject_key is keyed by canonical names.
        person_rows = (
            await db.execute(
                select(Person.id, Person.display_name, Person.nickname).where(
                    or_(
                        Person.display_name.ilike(like),
                        Person.nickname.ilike(like),
                    )
                )
            )
        ).all()
        if not person_rows:
            return {"journeys": [], "disambiguation": []}
        if len(person_rows) > 1:
            return {
                "journeys": [],
                "disambiguation": [
                    {"person_id": str(pid), "display_name": (nk or dname)}
                    for pid, dname, nk in person_rows
                ],
            }
        resolved_name = person_rows[0][1]

    filters = [
        Journey.subject_kind == "person",
        Journey.last_seen_at >= cutoff,
    ]
    # Exact per-element match in SQL (#151). The Python token check below
    # is kept as belt and braces, but it no longer has to discard
    # substring hits, so the overfetch is cheaper.
    if resolved_name is not None:
        filters.append(subject_key_has(Journey.subject_key, resolved_name))

    # When name-filtering, overfetch so the Python token filter still
    # has enough candidates after dropping coincidental substring hits.
    fetch_limit = max(limit, 200) if resolved_name is not None else limit
    stmt = (
        select(Journey)
        .where(and_(*filters))
        .order_by(Journey.last_seen_at.desc())
        .limit(fetch_limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    def _names(subject_key: str | None) -> list[str]:
        return [n.strip() for n in (subject_key or "").split(",") if n.strip()]

    # Precise exact-token filter. subject_key is comma-joined names; the
    # person matches only if their exact display name is one of them.
    if resolved_name is not None:
        rows = [j for j in rows if resolved_name in _names(j.subject_key)][:limit]
    else:
        rows = rows[:limit]

    # Resolve person_id for single-name journeys so the agent can cite
    # one. Multi-person journeys keep person_id null but list the names.
    single_names: set[str] = set()
    for j in rows:
        ns = _names(j.subject_key)
        if len(ns) == 1:
            single_names.add(ns[0])
    name_to_id: dict[str, str] = {}
    if single_names:
        for pid, dname in (
            await db.execute(
                select(Person.id, Person.display_name).where(
                    Person.display_name.in_(single_names)
                )
            )
        ).all():
            name_to_id[dname] = str(pid)

    # Resolve thumbnails from each journey's peak observation.
    peak_ids: set[uuid.UUID] = set()
    for j in rows:
        for seg in j.segments or []:
            if isinstance(seg, dict):
                poid = seg.get("peak_observation_id")
                if poid:
                    try:
                        peak_ids.add(uuid.UUID(poid))
                    except (TypeError, ValueError):
                        continue
    thumb_by_obs: dict[uuid.UUID, str] = {}
    if peak_ids:
        for oid, tpath in (
            await db.execute(
                select(Observation.id, Observation.thumbnail_path).where(
                    Observation.id.in_(peak_ids)
                )
            )
        ).all():
            if tpath:
                thumb_by_obs[oid] = tpath

    amap = await _alias_map(db)
    journeys_out: list[dict[str, Any]] = []
    for j in rows:
        # Filter segments to accessible cameras and skip the journey if
        # nothing remains. Segments already carry camera_name +
        # occurrence_count (see journey_tracker._segment).
        seg_cams: list[dict[str, str]] = []
        seen: set[uuid.UUID] = set()
        observation_count = 0
        first_thumb: str | None = None
        for seg in j.segments or []:
            if not isinstance(seg, dict):
                continue
            cid_str = seg.get("camera_id")
            try:
                cid = uuid.UUID(cid_str) if cid_str else None
            except (TypeError, ValueError):
                cid = None
            if cid is None or cid not in effective_cams:
                continue
            if cid not in seen:
                seg_cams.append(
                    {"id": str(cid), "name": seg.get("camera_name") or "Unknown"}
                )
                seen.add(cid)
            observation_count += int(seg.get("occurrence_count") or 0)
            if first_thumb is None:
                poid = seg.get("peak_observation_id")
                if poid:
                    try:
                        first_thumb = thumb_by_obs.get(uuid.UUID(poid))
                    except (TypeError, ValueError):
                        first_thumb = None
        if not seg_cams:
            continue

        ns = _names(j.subject_key)
        ns_display = alias_names(ns, amap)
        person_id_out = name_to_id.get(ns[0]) if len(ns) == 1 else None

        started = j.started_at
        ended = j.ended_at or j.last_seen_at
        duration_s = int((ended - started).total_seconds()) if started and ended else None

        journeys_out.append(
            {
                "id": str(j.id),
                "person_id": person_id_out,
                "person_name": ", ".join(ns_display) if ns_display else j.subject_key,
                "person_names": ns_display,
                "started_at": started.isoformat() if started else None,
                "ended_at": ended.isoformat() if ended else None,
                "duration_seconds": duration_s,
                "cameras": seg_cams,
                "observation_count": observation_count,
                "thumbnail_url": _thumbnail_url(first_thumb),
            }
        )

    return {"journeys": journeys_out}


# ── Tool 3. get_camera_layout ─────────────────────────────────────────


