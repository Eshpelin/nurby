"""Who was with whom, who came back, who went where.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String as SAString
from sqlalchemy import and_, cast, func, or_, select

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    _clamp_hours,
    _clamp_limit,
    _thumbnail_url,
)
from shared.models import (
    EntityAssociation,
    Journey,
    Observation,
    Person,
)
from shared.person_alias import display_name_for

_KNOWN_LABELS = (
    "person",
    "cat",
    "dog",
    "car",
    "truck",
    "bus",
    "bicycle",
    "motorcycle",
    "package",
    "bird",
    "backpack",
    "handbag",
    "suitcase",
    "umbrella",
)

_REVISIT_GAP_SECONDS = 30 * 60  # 30 min between journeys counts as a return

_RELATIONS = (
    "co_present_with",
    "revisited",
    "path",
    "seen_with_label",
    "transitions",
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


_QUERY_RELATIONSHIPS_SCHEMA = {
    "type": "object",
    "required": ["subject", "relation"],
    "additionalProperties": False,
    "properties": {
        "subject": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Person display_name (case-insensitive substring), a "
                "person_id UUID, or a label like 'cat' / 'car' / "
                "'package'."
            ),
        },
        "relation": {
            "type": "string",
            "enum": list(_RELATIONS),
            "description": (
                "co_present_with (who/what overlapped subject on the same "
                "camera), revisited (subject came back after a >30min "
                "gap), path (ordered camera transitions of the subject's "
                "most recent journey), seen_with_label (a label detected "
                "during the subject's journey windows), transitions (all "
                "camera-to-camera movement gaps in the window)."
            ),
        },
        "object": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Optional second party. For co_present_with, restrict to "
                "this person/label. For seen_with_label, the label to look "
                "for (e.g. 'dog'). Ignored by other relations."
            ),
        },
        "hours": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_WINDOW_HOURS,
            "default": 168,
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
}



_GET_ASSOCIATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": (
                "Person name to look up patterns for. Omit to list every "
                "established pattern in the household."
            ),
        },
        "relation": {
            "type": "string",
            "enum": ["uses", "accompanies", "arrives_with", "authorized_for"],
            "description": "Only this kind of relationship. Omit for any.",
        },
        "include_candidates": {
            "type": "boolean",
            "description": (
                "Include patterns that have not recurred on enough separate "
                "days to be established yet. Default false."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}


async def get_associations(
    ctx: dict,
    *,
    subject: str | None = None,
    relation: str | None = None,
    include_candidates: bool = False,
) -> dict:
    """Learned habits and declared authorizations between identities.

    Answers "which car does Ahmed use" directly, instead of the agent
    stitching journeys together and guessing. Each row carries how often
    the pairing has been seen, over how many separate days, and the hours
    it usually happens at, so the answer can be honest about how strong
    the pattern is.
    """
    db = ctx["db"]
    q = select(EntityAssociation)
    if subject:
        q = q.where(EntityAssociation.subject_key.ilike(subject))
    if relation:
        q = q.where(EntityAssociation.relation == relation)
    if include_candidates:
        q = q.where(EntityAssociation.status.in_(("established", "candidate")))
    else:
        q = q.where(EntityAssociation.status == "established")
    q = q.order_by(
        EntityAssociation.distinct_days.desc(),
        EntityAssociation.evidence_count.desc(),
    ).limit(50)

    rows = (await db.execute(q)).scalars().all()
    out = []
    for r in rows:
        hours = sorted(
            (int(h) for h, c in (r.hour_histogram or {}).items() if int(c) > 0)
        )
        out.append({
            "association_id": str(r.id),
            "subject": r.subject_key,
            "subject_kind": r.subject_kind,
            "relation": r.relation,
            "object": r.object_label or r.object_key,
            "object_kind": r.object_kind,
            # learned = observed habit, declared = asserted by an admin.
            # The agent must not present the first as a rule or the second
            # as a pattern.
            "source": r.source,
            "status": r.status,
            "times_seen": int(r.evidence_count or 0),
            "distinct_days": int(r.distinct_days or 0),
            "usual_hours": hours,
            "first_seen": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None,
        })
    return {
        "associations": out,
        "count": len(out),
        "note": (
            "learned rows are observed habits and may be wrong; declared "
            "rows are authorizations set by an administrator. Never state a "
            "learned habit as a rule."
        ),
    }



_GET_HOUSEHOLD_FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": (
                "Attach-point to look up: a person display_name/UUID, a "
                "vehicle display_name/plate/UUID, a camera name/UUID, or "
                "'household' for whole-home notes. Omit for every "
                "established note."
            ),
        },
        "include_candidates": {
            "type": "boolean",
            "description": (
                "Include Nurby's unreviewed proposals. Default false: "
                "proposals are not yet knowledge."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}


async def get_household_facts(
    ctx: dict,
    *,
    subject: str | None = None,
    include_candidates: bool = False,
) -> dict:
    """What the household has told Nurby, plus what Nurby has learned.

    Answers "what do you know about the cleaner" from the durable note
    store, in one cheap indexed lookup. Established rows only unless
    ``include_candidates`` — a candidate is a pending proposal, not
    knowledge. The response says which notes came from the household and
    which were learned from observation, and the agent must keep that
    distinction when answering.
    """
    from shared.models import HouseholdFact

    db = ctx["db"]
    q = select(HouseholdFact)
    if include_candidates:
        q = q.where(HouseholdFact.status.in_(("established", "candidate")))
    else:
        q = q.where(HouseholdFact.status == "established")

    attach = None
    if subject and str(subject).strip().lower() != "household":
        attach = await _resolve_remember_attachment(str(subject), db)
        if attach is not None:
            kind, key = attach
            q = q.where(
                HouseholdFact.entity_kind == kind,
                HouseholdFact.entity_key == key,
            )
        else:
            return {
                "facts": [],
                "count": 0,
                "note": f"nothing in the library matches {subject!r}; "
                "household-wide notes are returned only when subject is omitted "
                "or 'household'.",
            }

    q = q.order_by(
        HouseholdFact.pinned.desc(),
        HouseholdFact.evidence_count.desc(),
        HouseholdFact.created_at.desc(),
    ).limit(50)
    rows = (await db.execute(q)).scalars().all()

    out = []
    for f in rows:
        entry = {
            "id": str(f.id),
            "text": f.text,
            "source": f.source,  # user = the household said so; agent = learned
            "status": f.status,
            "pinned": bool(f.pinned),
            "evidence_count": int(f.evidence_count or 0),
            "entity_kind": f.entity_kind or "household",
            "schedule": None
            if getattr(f, "schedule_days", None) is None
            else {
                "days": f.schedule_days,
                "start_minute": f.schedule_start_minute,
                "end_minute": f.schedule_end_minute,
            },
        }
        out.append(entry)
    return {
        "facts": out,
        "count": len(out),
        "note": (
            "source='user' notes are what the household said on purpose; "
            "source='agent' facts are distilled from observations and may be "
            "wrong. Never present a learned fact as something the household "
            "told you."
        ),
    }


async def _resolve_remember_attachment(subject: str, db) -> tuple[str, str] | None:
    """Resolve 'the cleaner' style input to an (entity_kind, entity_key)
    attach point, or None. Person first, then vehicle, then camera."""
    subj = subject.strip()
    person = await _resolve_subject(subj, db)
    if person["type"] == "person":
        return "person", str(person["person_id"])
    try:
        return "camera", str(await _camera_id_by_name(subj, db))
    except Exception:
        pass
    from shared.models import Vehicle

    rows = (
        await db.execute(
            select(Vehicle).where(
                func.lower(Vehicle.display_name).like(f"%{subj.lower()}%")
                | func.lower(func.coalesce(Vehicle.license_plate, "")).like(f"%{subj.lower()}%")
            )
        )
    ).scalars().all()
    if len(rows) == 1:
        return "vehicle", str(rows[0].id)
    return None


async def _camera_id_by_name(name: str, db) -> "uuid.UUID":
    from shared.models import Camera

    row = (
        await db.execute(select(Camera).where(func.lower(Camera.name) == name.lower()))
    ).scalars().first()
    if row is None:
        raise LookupError(name)
    return row.id


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value.strip()))


def _seg_cam_ids(journey: Any, allowed: set[uuid.UUID]) -> set[uuid.UUID]:
    """Accessible camera UUIDs touched by a journey's segments."""
    out: set[uuid.UUID] = set()
    for seg in journey.segments or []:
        if not isinstance(seg, dict):
            continue
        cid = seg.get("camera_id")
        if not cid:
            continue
        try:
            cu = uuid.UUID(cid)
        except (TypeError, ValueError):
            continue
        if cu in allowed:
            out.add(cu)
    return out


def _journey_window(journey: Any) -> tuple[datetime | None, datetime | None]:
    start = journey.started_at
    end = journey.ended_at or journey.last_seen_at
    return start, end


def _windows_overlap(
    a_start: datetime | None,
    a_end: datetime | None,
    b_start: datetime | None,
    b_end: datetime | None,
) -> bool:
    if not (a_start and a_end and b_start and b_end):
        return False
    return a_start < b_end and a_end > b_start


async def _resolve_subject(
    subject: str, db: Any
) -> dict[str, Any]:
    """Resolve a subject string to a (kind, key-set) descriptor.

    Returns one of.
      {"type": "person", "person_id": uuid, "display_name": str}
      {"type": "label", "label": str}
      {"type": "disambiguation", "candidates": [...]}
      {"type": "unresolved"}

    Person journeys are keyed by display_name(s) in Journey.subject_key
    (the incident tracker joins person_name values, NOT the person_id),
    so we resolve a Person row to get its display_name and match journeys
    on subject_kind == 'person' + name-in-subject_key downstream.
    """
    subj = subject.strip()
    if not subj:
        return {"type": "unresolved"}

    # UUID -> a Person row by id.
    if _looks_like_uuid(subj):
        try:
            p = await db.get(Person, uuid.UUID(subj))
        except Exception:
            p = None
        if p is not None:
            return {
                "type": "person",
                "person_id": p.id,
                "display_name": p.display_name,
                "display": display_name_for(p),
            }
        # An unknown UUID. nothing to resolve.
        return {"type": "unresolved"}

    # Person match on canonical display_name or household nickname. The
    # returned display_name stays canonical so the journey subject_key
    # filter matches; ``display`` carries the nickname for the user echo.
    like = f"%{subj.lower()}%"
    person_rows = (
        await db.execute(
            select(Person.id, Person.display_name, Person.nickname).where(
                or_(
                    func.lower(Person.display_name).like(like),
                    func.lower(Person.nickname).like(like),
                )
            )
        )
    ).all()
    if len(person_rows) > 1:
        return {
            "type": "disambiguation",
            "candidates": [
                {"person_id": str(pid), "display_name": (nk or dname)}
                for pid, dname, nk in person_rows
            ],
        }
    if len(person_rows) == 1:
        pid, dname, nk = person_rows[0]
        return {
            "type": "person",
            "person_id": pid,
            "display_name": dname,
            "display": (nk.strip() if isinstance(nk, str) and nk.strip() else dname),
        }

    # No Person matched. Treat a known label word as an object subject.
    if subj.lower() in _KNOWN_LABELS:
        return {"type": "label", "label": subj.lower()}

    return {"type": "unresolved"}


def _token_match(column, token: str):
    """Match ``token`` as a whole comma-separated entry in ``column``.

    Journeys written before per-subject fan-out carry a comma-joined
    subject_key ("Ahmed,Sara"), so a person's history genuinely does live
    inside those rows and has to be found there. A plain ILIKE would find
    it, but it also matches substrings: searching for Ann returns
    Anna's journeys, and searching for a one-word name returns anyone
    whose name contains it. This anchors on the entry boundaries instead.
    """
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    text = cast(column, SAString)
    return or_(
        text.ilike(escaped, escape="\\"),
        text.ilike(f"{escaped},%", escape="\\"),
        text.ilike(f"%,{escaped}", escape="\\"),
        text.ilike(f"%,{escaped},%", escape="\\"),
    )


def _subject_journey_filter(subject: dict[str, Any]) -> list[Any]:
    """SQLAlchemy filters selecting the journeys that belong to a
    resolved subject. Person journeys match their display_name as a whole
    entry in the comma-joined subject_key; label journeys match
    subject_kind=='object' with the label as a whole entry."""
    if subject["type"] == "person":
        return [
            Journey.subject_kind == "person",
            _token_match(Journey.subject_key, subject["display_name"]),
        ]
    if subject["type"] == "label":
        return [
            Journey.subject_kind == "object",
            _token_match(Journey.subject_key, subject["label"]),
        ]
    return [select(Journey.id).where(False)]  # never matches


def _subject_echo(subject: dict[str, Any]) -> dict[str, Any]:
    if subject["type"] == "person":
        return {
            "type": "person",
            "person_id": str(subject["person_id"]),
            "display_name": subject.get("display") or subject["display_name"],
        }
    if subject["type"] == "label":
        return {"type": "label", "label": subject["label"]}
    return {"type": "unresolved"}


async def query_relationships(
    ctx: dict,
    *,
    subject: str,
    relation: str,
    object: str | None = None,
    hours: int = 168,
    limit: int = 50,
) -> dict:
    """Walk relationships between people, animals, vehicles, cameras, and
    time over the existing Journey graph (foreign keys + segments /
    transitions JSON). One DB pass, no new tables.

    All results are filtered through accessible_camera_ids. When the
    subject name resolves to more than one Person the response carries a
    ``disambiguation`` block and an empty ``results`` list, matching the
    get_journeys convention.
    """
    user = ctx["user"]
    db = ctx["db"]

    hours = _clamp_hours(hours)
    limit = _clamp_limit(limit, default=50, max_=100)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    if relation not in _RELATIONS:
        return {
            "relation": relation,
            "subject": {"type": "unresolved"},
            "hours": hours,
            "results": [],
            "error": "unknown_relation",
        }

    allowed = await _common.accessible_camera_ids(user, db)
    base = {"relation": relation, "hours": hours}
    if not allowed:
        return {**base, "subject": {"type": "unresolved"}, "results": []}

    subject_desc = await _resolve_subject(subject, db)
    if subject_desc["type"] == "disambiguation":
        return {
            **base,
            "subject": {"type": "person_ambiguous"},
            "results": [],
            "disambiguation": subject_desc["candidates"],
        }
    if subject_desc["type"] == "unresolved":
        return {**base, "subject": {"type": "unresolved"}, "results": []}

    subj_echo = _subject_echo(subject_desc)

    # Load the subject's journeys in the window once. Every relation but
    # `transitions` is grounded on this set.
    subj_filters = _subject_journey_filter(subject_desc) + [
        Journey.last_seen_at >= cutoff
    ]
    subj_journeys = (
        await db.execute(
            select(Journey)
            .where(and_(*subj_filters))
            .order_by(Journey.last_seen_at.desc())
            .limit(200)
        )
    ).scalars().all()
    # Keep only journeys that touch at least one accessible camera.
    subj_journeys = [j for j in subj_journeys if _seg_cam_ids(j, allowed)]

    # Exact-token guard. ``subject_key`` is a comma-joined set of names
    # (persons) or labels (objects). The SQL ilike above is a coarse
    # prefilter; require an exact member match here so "Ann" does not
    # match a journey for "Anna", and "car" does not match "carriage".
    if subject_desc["type"] == "person":
        token = subject_desc["display_name"]
    elif subject_desc["type"] == "label":
        token = subject_desc["label"]
    else:
        token = None
    if token is not None:
        subj_journeys = [
            j
            for j in subj_journeys
            if token in [n.strip() for n in (j.subject_key or "").split(",")]
        ]

    if relation == "co_present_with":
        results = await _rel_co_present(
            db, subject_desc, subj_journeys, allowed, cutoff, object, limit
        )
    elif relation == "revisited":
        results = _rel_revisited(subj_journeys, allowed, limit)
    elif relation == "path":
        results = _rel_path(subj_journeys, allowed, limit)
    elif relation == "seen_with_label":
        results = await _rel_seen_with_label(
            db, subj_journeys, allowed, object, limit
        )
    else:  # transitions
        results = await _rel_transitions(db, allowed, cutoff, limit)

    return {**base, "subject": subj_echo, "results": results}


async def _rel_co_present(
    db: Any,
    subject_desc: dict[str, Any],
    subj_journeys: list[Any],
    allowed: set[uuid.UUID],
    cutoff: datetime,
    object_filter: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Other subjects whose journey windows overlap the subject's
    journeys on the SAME camera."""
    if not subj_journeys:
        return []

    # Precompute subject (window, camera-set) tuples.
    subj_spans: list[tuple[datetime, datetime, set[uuid.UUID]]] = []
    subj_keys: set[str] = set()
    for j in subj_journeys:
        s, e = _journey_window(j)
        if s and e:
            subj_spans.append((s, e, _seg_cam_ids(j, allowed)))
        subj_keys.add(j.subject_key)

    # Candidate journeys. everything else in the window. We over-fetch
    # then filter in Python for the overlap + shared-camera test.
    others = (
        await db.execute(
            select(Journey)
            .where(Journey.last_seen_at >= cutoff)
            .order_by(Journey.last_seen_at.desc())
            .limit(500)
        )
    ).scalars().all()

    obj_needle = object_filter.strip().lower() if object_filter else None

    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for o in others:
        if o.subject_key in subj_keys:
            continue  # the subject themselves
        if obj_needle and obj_needle not in (o.subject_key or "").lower():
            continue
        o_cams = _seg_cam_ids(o, allowed)
        if not o_cams:
            continue
        o_start, o_end = _journey_window(o)
        shared: set[uuid.UUID] | None = None
        for (s, e, cams) in subj_spans:
            if _windows_overlap(s, e, o_start, o_end) and (cams & o_cams):
                shared = cams & o_cams
                break
        if shared is None:
            continue
        if o.subject_key in seen_keys:
            continue
        seen_keys.add(o.subject_key)
        out.append(
            {
                "journey_id": str(o.id),
                "subject_kind": o.subject_kind,
                "subject_key": o.subject_key,
                "person_id": str(o.person_id)
                if getattr(o, "person_id", None)
                else None,
                "overlap_cameras": [
                    {"id": str(cid), "name": _seg_cam_name(o, cid)}
                    for cid in shared
                ],
                "started_at": o.started_at.isoformat() if o.started_at else None,
                "last_seen_at": o.last_seen_at.isoformat()
                if o.last_seen_at
                else None,
            }
        )
        if len(out) >= limit:
            break
    return out


def _seg_cam_name(journey: Any, cam_id: uuid.UUID) -> str | None:
    for seg in journey.segments or []:
        if isinstance(seg, dict) and seg.get("camera_id") == str(cam_id):
            return seg.get("camera_name")
    return None


def _rel_revisited(
    subj_journeys: list[Any], allowed: set[uuid.UUID], limit: int
) -> list[dict[str, Any]]:
    """Same subject_key appearing in 2+ journeys separated by a >30min
    gap. Works on body-cluster / object subjects without a face."""
    by_key: dict[str, list[Any]] = {}
    for j in subj_journeys:
        by_key.setdefault(j.subject_key, []).append(j)

    out: list[dict[str, Any]] = []
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda j: j.started_at or datetime.min.replace(tzinfo=timezone.utc))
        for i in range(1, len(ordered)):
            prev = ordered[i - 1]
            cur = ordered[i]
            prev_end = prev.ended_at or prev.last_seen_at
            cur_start = cur.started_at
            if not (prev_end and cur_start):
                continue
            gap = int((cur_start - prev_end).total_seconds())
            if gap < _REVISIT_GAP_SECONDS:
                continue
            out.append(
                {
                    "subject_key": key,
                    "subject_kind": cur.subject_kind,
                    "gap_seconds": gap,
                    "gap_minutes": round(gap / 60),
                    "first_journey_id": str(prev.id),
                    "first_left_at": prev_end.isoformat(),
                    "return_journey_id": str(cur.id),
                    "returned_at": cur_start.isoformat(),
                    "return_cameras": [
                        {"id": str(cid), "name": _seg_cam_name(cur, cid)}
                        for cid in _seg_cam_ids(cur, allowed)
                    ],
                }
            )
            if len(out) >= limit:
                return out
    return out


def _rel_path(
    subj_journeys: list[Any], allowed: set[uuid.UUID], limit: int
) -> list[dict[str, Any]]:
    """Ordered camera transitions for the subject's most recent journey,
    read from Journey.transitions, falling back to segment order."""
    if not subj_journeys:
        return []
    j = subj_journeys[0]  # already ordered last_seen_at desc

    out: list[dict[str, Any]] = []
    transitions = j.transitions or []
    for t in transitions:
        if not isinstance(t, dict):
            continue
        from_cid = t.get("from_camera_id")
        to_cid = t.get("to_camera_id")
        # ACL. only surface a hop when both endpoints are accessible.
        try:
            if from_cid and uuid.UUID(from_cid) not in allowed:
                continue
            if to_cid and uuid.UUID(to_cid) not in allowed:
                continue
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "journey_id": str(j.id),
                "from_camera_id": from_cid,
                "from_camera_name": t.get("from_camera_name"),
                "to_camera_id": to_cid,
                "to_camera_name": t.get("to_camera_name"),
                "gap_seconds": t.get("gap_seconds"),
                "at": t.get("ts"),
            }
        )
        if len(out) >= limit:
            break

    if not out:
        # No transition rows (single-camera journey). Surface the ordered
        # segment cameras so the agent still gets the path shape.
        for seg in j.segments or []:
            if not isinstance(seg, dict):
                continue
            cid = seg.get("camera_id")
            try:
                if cid and uuid.UUID(cid) not in allowed:
                    continue
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "journey_id": str(j.id),
                    "camera_id": cid,
                    "camera_name": seg.get("camera_name"),
                    "started_at": seg.get("started_at"),
                    "last_seen_at": seg.get("last_seen_at"),
                }
            )
            if len(out) >= limit:
                break
    return out


async def _rel_seen_with_label(
    db: Any,
    subj_journeys: list[Any],
    allowed: set[uuid.UUID],
    label: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Observations carrying ``label`` in object_detections that fall
    inside one of the subject's journey windows on a shared camera."""
    if not label or not subj_journeys:
        return []
    needle = label.strip()
    if not needle:
        return []

    out: list[dict[str, Any]] = []
    seen_obs: set[str] = set()
    for j in subj_journeys:
        j_start, j_end = _journey_window(j)
        if not (j_start and j_end):
            continue
        cams = _seg_cam_ids(j, allowed)
        if not cams:
            continue
        # Same JSON label-in-detections filter get_last_sightings uses,
        # over Observation.object_detections (the real column name).
        rows = (
            await db.execute(
                select(Observation)
                .where(Observation.camera_id.in_(cams))
                .where(Observation.started_at >= j_start)
                .where(Observation.started_at <= j_end)
                .where(
                    cast(Observation.object_detections, SAString).ilike(
                        f'%"label": "{needle}"%'
                    )
                )
                .order_by(Observation.started_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for obs in rows:
            if str(obs.id) in seen_obs:
                continue
            if obs.camera_id not in allowed:
                continue
            seen_obs.add(str(obs.id))
            out.append(
                {
                    "observation_id": str(obs.id),
                    "journey_id": str(j.id),
                    "label": needle,
                    "camera_id": str(obs.camera_id),
                    "camera_name": _seg_cam_name(j, obs.camera_id),
                    "timestamp": obs.started_at.isoformat()
                    if obs.started_at
                    else None,
                    "description": obs.vlm_description,
                    "thumbnail_url": _thumbnail_url(obs.thumbnail_path),
                }
            )
            if len(out) >= limit:
                return out
    return out


async def _rel_transitions(
    db: Any, allowed: set[uuid.UUID], cutoff: datetime, limit: int
) -> list[dict[str, Any]]:
    """Aggregate of all camera-to-camera movement gaps across journeys
    in the window. Answers 'what's the usual path through the house?'."""
    journeys = (
        await db.execute(
            select(Journey)
            .where(Journey.last_seen_at >= cutoff)
            .order_by(Journey.last_seen_at.desc())
            .limit(1000)
        )
    ).scalars().all()

    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for j in journeys:
        for t in j.transitions or []:
            if not isinstance(t, dict):
                continue
            from_cid = t.get("from_camera_id")
            to_cid = t.get("to_camera_id")
            if not (from_cid and to_cid):
                continue
            try:
                if uuid.UUID(from_cid) not in allowed:
                    continue
                if uuid.UUID(to_cid) not in allowed:
                    continue
            except (TypeError, ValueError):
                continue
            k = (from_cid, to_cid)
            bucket = agg.setdefault(
                k,
                {
                    "from_camera_id": from_cid,
                    "from_camera_name": t.get("from_camera_name"),
                    "to_camera_id": to_cid,
                    "to_camera_name": t.get("to_camera_name"),
                    "count": 0,
                    "_gap_total": 0,
                },
            )
            bucket["count"] += 1
            bucket["_gap_total"] += int(t.get("gap_seconds") or 0)

    out: list[dict[str, Any]] = []
    for bucket in sorted(agg.values(), key=lambda b: -b["count"]):
        cnt = bucket["count"]
        out.append(
            {
                "from_camera_id": bucket["from_camera_id"],
                "from_camera_name": bucket["from_camera_name"],
                "to_camera_id": bucket["to_camera_id"],
                "to_camera_name": bucket["to_camera_name"],
                "count": cnt,
                "avg_gap_seconds": round(bucket["_gap_total"] / cnt) if cnt else 0,
            }
        )
        if len(out) >= limit:
            break
    return out


# ── Tool 3f. summarize_window (map-reduce long-window summary) ────────


