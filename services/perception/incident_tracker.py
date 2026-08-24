"""Incident tracking. assignment + finalizer.

Mirrors the frontend coalescer's grouping logic but persists rows
so the dashboard can show a stable id, push WS events for live
append, and run a final summary VLM call when an incident closes.

Pipeline calls :func:`assign_incident` synchronously inside the
observation insert path. The :class:`IncidentFinalizer` worker
runs alongside the perception pipeline and closes incidents that
have been quiet beyond their camera's ``incident_idle_seconds``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.ws import broadcast as ws_broadcast
from services.perception.text_llm import call_text
from services.perception.token_budget import resolve_output_cap
from services.perception.vlm import get_active_provider
from services.search.embeddings import generate_embedding, get_embedding_provider
from shared.database import async_session
from shared.models import Camera, Incident, Observation, Provider

logger = logging.getLogger("nurby.perception.incident")


def _humanize_duration(seconds: float) -> str:
    """Human-readable duration. Avoids '1196-second period' in narratives."""
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s} second{'s' if s != 1 else ''}"
    if s < 3600:
        m = round(s / 60)
        return f"{m} minute{'s' if m != 1 else ''}"
    h = s / 3600
    txt = f"{h:.1f}".rstrip("0").rstrip(".")
    return f"{txt} hour{'s' if txt != '1' else ''}"


INCIDENT_SUMMARY_PROMPT = (
    "You are a security camera analyst. You are given a series of"
    " observations of the same person or object on one camera that"
    " happened over a short window. Write a single concise sentence"
    " summarizing what happened across the occurrences. Use identity,"
    " plate, and location facts as ground truth. If nothing notable"
    " happened, return SKIP."
)


# ---- signature -----------------------------------------------------------


# Subjects worth tracking as discrete incidents. everything else (furniture,
# appliances, tableware, plants) is ambient and rolls into motion instead of
# becoming a "Clock seen 4x" card. Mirrors the frontend INTERESTING_OBJECTS.
INTERESTING_INCIDENT_LABELS = {
    "person",
    "car", "truck", "bus", "motorcycle", "bicycle", "van",
    "dog", "cat", "bird", "horse",
    "backpack", "handbag", "suitcase", "package", "box",
    "knife", "gun", "fire",
}


# Rule-engine sink. The perception main wires this to the shared
# RuleEngine so incident lifecycle edges can fire incident_started /
# incident_ended rules. Kept as a loose hook so this module stays
# importable without the engine (tests, API process).
_rule_event_sink = None


def set_rule_event_sink(sink) -> None:
    global _rule_event_sink
    _rule_event_sink = sink


async def _emit_rule_event(payload: dict) -> None:
    if _rule_event_sink is None:
        return
    try:
        await _rule_event_sink(payload)
    except Exception:
        logger.exception("incident rule-event sink failed")


# Identity ladder, strongest rung first. A subject is keyed by the best
# evidence available for it, and the rung is carried alongside so callers
# can tell a face-derived identity from an appearance-derived one.
#
# Ordering note. Face clusters outrank body clusters deliberately. A face
# cluster survives a change of clothes; an OSNet appearance embedding does
# not, so it is the fallback that keeps a subject continuous *through
# occlusion*, not a cross-day identity. See resolve_subjects.
IDENTITY_LADDER = ("person", "cluster", "body")


def resolve_subjects(person_detections: dict | None) -> list[dict]:
    """Every distinct person-subject in an observation, best identity first.

    Returns ``[{"kind", "key", "name", "bound_by"}]`` where ``kind`` is one
    of ``person`` | ``cluster`` | ``body`` and ``bound_by`` records which
    evidence produced it (``face`` | ``held`` | ``face_cluster`` | ``body``).

    The pipeline resolves identity per track long before this runs. It
    stamps ``person_detections["tracks"]`` with a held ``person_id`` that
    survives the face going out of view, and ``body_cluster_id`` from
    cross-camera body re-identification. Both were previously dropped on
    the floor here, which is why a subject stopped being the same subject
    the moment they turned their head (issue #144).

    Pure, for tests. Tolerant of pre-``tracks`` observation payloads, which
    carry only ``faces`` and ``bodies``.
    """
    pd = person_detections or {}
    tracks = pd.get("tracks") or []
    faces = pd.get("faces") or []

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, key: str | None, name: str | None, bound_by: str) -> None:
        if not key:
            return
        ident = (kind, str(key))
        if ident in seen:
            return
        seen.add(ident)
        out.append(
            {"kind": kind, "key": str(key), "name": name, "bound_by": bound_by}
        )

    # Rung 1. A track the binder resolved to a real Person. This is the
    # rung that survives face occlusion, and the whole point of the fix.
    for t in tracks:
        if t.get("state") != "person":
            continue
        name = t.get("person_name")
        # A held binding with no name is still a person we know; fall back
        # to the id so the subject stays stable rather than collapsing to
        # "unknown" for want of a display string.
        _add("person", name or t.get("person_id"), name, "held")

    # Rung 1b. Faces matched this frame. Redundant with the tracks above
    # whenever the pipeline ran the binder, but observations written before
    # tracks existed (and any path that skips tracking) still land here.
    for f in faces:
        _add("person", f.get("person_name"), f.get("person_name"), "face")

    # Rung 2. Recurring unknown faces. A face cluster is durable across
    # days, so it outranks appearance.
    for f in faces:
        _add("cluster", f.get("cluster_id"), None, "face_cluster")

    # Rung 3. Body re-identification. No face this frame, but the body
    # matched a cross-camera appearance cluster, so the subject stays
    # continuous instead of decaying into "motion".
    for t in tracks:
        _add("body", t.get("body_cluster_id"), None, "body")
    for b in pd.get("bodies") or []:
        _add("body", b.get("body_cluster_id"), None, "body")

    order = {kind: i for i, kind in enumerate(IDENTITY_LADDER)}
    out.sort(key=lambda s: (order.get(s["kind"], len(order)), s["key"]))
    return out


def compute_signature(
    person_detections: dict | None,
    object_detections: dict | None,
) -> tuple[str, str]:
    """Return (signature_kind, signature_key) for an observation.

    Priority. named persons > recurring unknown clusters > re-identified
    bodies > unknown faces > top YOLO labels > motion. Mirrors the frontend
    coalescer so the two layers agree on what counts as 'the same thing'.

    Grouping caveat, tracked separately as issue #145. When several
    subjects share a frame their keys are joined, so "Ahmed,Sara" is a
    different signature than "Ahmed" and a person's history still
    fragments when they are with someone. Fixing that means one incident
    per subject, which is a schema change; this function is written to
    make that a small step by resolving subjects individually first.
    """
    kind, key, _bound_by = compute_signature_detail(
        person_detections, object_detections
    )
    return kind, key


def compute_signature_detail(
    person_detections: dict | None,
    object_detections: dict | None,
) -> tuple[str, str, str | None]:
    """:func:`compute_signature` plus the evidence rung that produced it.

    ``bound_by`` is ``None`` for the object and motion signatures, which
    are not identities at all. It is not persisted on ``Incident`` yet; it
    rides along on the WS and rule-event payloads so the confidence behind
    a signature is visible without a migration. The persisted form lands
    with the per-subject journey work.
    """
    faces = (person_detections or {}).get("faces") or []
    subjects = resolve_subjects(person_detections)

    for kind in IDENTITY_LADDER:
        matching = [s for s in subjects if s["kind"] == kind]
        if not matching:
            continue
        keys = sorted({s["key"] for s in matching})
        bound_by = matching[0]["bound_by"]
        return kind, ",".join(keys), bound_by

    if faces:
        return "unknown", "unknown", "face"
    objs = (object_detections or {}).get("objects") or []
    # Only meaningful subjects form an "object" incident. a clock or couch
    # seen N times is noise, not an event.
    labels = sorted(
        {
            d.get("label")
            for d in objs
            if d.get("label") in INTERESTING_INCIDENT_LABELS
        }
    )
    if labels:
        return "object", ",".join(labels[:3]), None
    # Inert-only or empty scene. group as ambient motion, not a subject.
    return "motion", "motion", None


# ---- assignment ----------------------------------------------------------


async def assign_incident(
    db: AsyncSession,
    cam: Camera,
    observation: Observation,
) -> uuid.UUID | None:
    """Find an open incident for this signature on the camera within
    the camera's idle window, and either append or open a new one.
    Returns the linked incident id (or None when tracking is off).

    Runs inside the same session as the observation insert so the
    observation.incident_id assignment lands atomically with the
    incident's occurrence_count bump.
    """
    if not getattr(cam, "incident_tracking_enabled", False):
        return None
    kind, key, bound_by = compute_signature_detail(
        observation.person_detections, observation.object_detections
    )
    idle_s = max(30, int(getattr(cam, "incident_idle_seconds", 600) or 600))
    cutoff = observation.started_at - timedelta(seconds=idle_s)

    existing = (
        await db.execute(
            select(Incident)
            .where(Incident.camera_id == cam.id)
            .where(Incident.finalized.is_(False))
            .where(Incident.signature_kind == kind)
            .where(Incident.signature_key == key)
            .where(Incident.last_seen_at >= cutoff)
            .order_by(Incident.last_seen_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if existing is not None:
        existing.last_seen_at = observation.started_at
        existing.occurrence_count = (existing.occurrence_count or 0) + 1
        ids = list(existing.observation_ids or [])
        ids.append(str(observation.id))
        existing.observation_ids = ids
        thumbs = list(existing.thumbnails or [])
        if observation.thumbnail_path:
            thumbs.append(
                {
                    "obs_id": str(observation.id),
                    "path": observation.thumbnail_path,
                    "ts": observation.started_at.isoformat(),
                }
            )
            # Cap denormalized thumbnails so the JSON column stays sane
            # even on a long-running incident.
            if len(thumbs) > 24:
                thumbs = thumbs[-24:]
        existing.thumbnails = thumbs
        # Update the journey link for this incident. If a journey is
        # already attached the call advances the segment for this
        # camera; if not, it stitches into a cross-camera journey
        # when a sibling exists for the same subject.
        try:
            from services.perception.journey_tracker import assign_journey

            jid = await assign_journey(db, existing, cam)
            if jid is not None and existing.journey_id != jid:
                existing.journey_id = jid
        except Exception:
            logger.exception("journey assignment failed inc=%s", existing.id)
        # Fire-and-forget WS append. The dashboard refetches on this
        # event to splice the new occurrence into the live card.
        try:
            asyncio.create_task(_broadcast_updated(existing))
        except RuntimeError:
            pass
        return existing.id

    new_inc = Incident(
        camera_id=cam.id,
        signature_kind=kind,
        signature_key=key,
        started_at=observation.started_at,
        last_seen_at=observation.started_at,
        ended_at=None,
        finalized=False,
        occurrence_count=1,
        peak_observation_id=observation.id,
        observation_ids=[str(observation.id)],
        thumbnails=(
            [
                {
                    "obs_id": str(observation.id),
                    "path": observation.thumbnail_path,
                    "ts": observation.started_at.isoformat(),
                }
            ]
            if observation.thumbnail_path
            else None
        ),
    )
    db.add(new_inc)
    await db.flush()
    # Stitch into a journey when one is already open for the same
    # subject across any camera. Otherwise opens a fresh journey row.
    try:
        from services.perception.journey_tracker import assign_journey

        jid = await assign_journey(db, new_inc, cam)
        if jid is not None:
            new_inc.journey_id = jid
    except Exception:
        logger.exception("journey assignment failed new inc=%s", new_inc.id)
    try:
        asyncio.create_task(_broadcast_opened(new_inc))
    except RuntimeError:
        pass
    await _emit_rule_event(
        {
            "event_kind": "incident",
            "incident_event": "started",
            "incident_id": str(new_inc.id),
            "camera_id": str(cam.id) if cam else None,
            "camera_name": cam.name if cam else "",
            "signature_kind": new_inc.signature_kind,
            "who_or_what": new_inc.signature_key,
            # Which evidence rung bound this identity (face / held / body).
            # Lets a rule distinguish "recognised by face" from "matched by
            # appearance" without inspecting the observation payload.
            "bound_by": bound_by,
            "timestamp": new_inc.started_at.isoformat(),
            "occurrence_count": new_inc.occurrence_count,
        }
    )
    return new_inc.id


# ---- finalizer worker ----------------------------------------------------


class IncidentFinalizer:
    """Closes idle incidents and writes a final VLM summary.

    Tick cadence is coarse (10s). Each tick scans up to 50 open
    incidents whose last_seen_at is past the camera's idle window.
    Closes them, optionally calls call_text for a summary, broadcasts
    incident_finalized.
    """

    TICK_SECONDS = 10

    def __init__(self, broadcast_fn=ws_broadcast) -> None:
        self._broadcast = broadcast_fn
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("incident finalizer started")
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:
                    logger.exception("incident finalizer tick failed")
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.TICK_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("incident finalizer stopped")

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            cams = (await db.execute(select(Camera))).scalars().all()
            cam_by_id = {c.id: c for c in cams}
            open_rows = (
                await db.execute(
                    select(Incident)
                    .where(Incident.finalized.is_(False))
                    .order_by(Incident.last_seen_at.asc())
                    .limit(50)
                )
            ).scalars().all()

        for inc in open_rows:
            cam = cam_by_id.get(inc.camera_id)
            if cam is None:
                await self._mark_finalized(inc.id, inc.last_seen_at)
                continue
            idle_s = max(30, int(cam.incident_idle_seconds or 600))
            quiet_for = (now - inc.last_seen_at).total_seconds()
            if quiet_for < idle_s:
                continue
            await self._finalize(cam, inc.id)

    async def _mark_finalized(self, inc_id: uuid.UUID, ended_at: datetime) -> None:
        try:
            async with async_session() as db:
                row = await db.get(Incident, inc_id)
                if row is None:
                    return
                row.finalized = True
                row.ended_at = ended_at
                await db.commit()
        except Exception:
            logger.exception("incident finalize failed inc=%s", inc_id)

    async def _finalize(self, cam: Camera, inc_id: uuid.UUID) -> None:
        async with async_session() as db:
            inc = await db.get(Incident, inc_id)
            if inc is None or inc.finalized:
                return
            obs_ids = inc.observation_ids or []
            obs_uuids = []
            for x in obs_ids:
                try:
                    obs_uuids.append(uuid.UUID(str(x)))
                except (TypeError, ValueError):
                    continue
            obs_rows = []
            if obs_uuids:
                obs_rows = list(
                    (
                        await db.execute(
                            select(Observation).where(Observation.id.in_(obs_uuids))
                        )
                    ).scalars().all()
                )
                obs_rows.sort(key=lambda r: r.started_at)

        # Mark closed first so a slow VLM call doesn't keep the row open.
        ended_at = inc.last_seen_at
        await self._mark_finalized(inc_id, ended_at)

        summary_text: str | None = None
        if obs_rows:
            provider = await self._resolve_provider(cam)
            if provider is not None:
                summary_text = await self._build_summary(provider, cam, inc, obs_rows)
                if summary_text and summary_text.strip().upper().startswith("SKIP"):
                    summary_text = None
                if summary_text:
                    await self._patch_summary(
                        inc_id=inc_id,
                        summary_text=summary_text.strip(),
                        provider_name=provider.name,
                    )

        try:
            await self._broadcast(
                {
                    "type": "incident_finalized",
                    "incident_id": str(inc_id),
                    "camera_id": str(cam.id),
                    "ended_at": ended_at.isoformat(),
                    "occurrence_count": inc.occurrence_count,
                    "summary_text": summary_text,
                }
            )
        except Exception:
            logger.debug("incident_finalized broadcast failed", exc_info=True)

        duration = max(0.0, (ended_at - inc.started_at).total_seconds())
        await _emit_rule_event(
            {
                "event_kind": "incident",
                "incident_event": "ended",
                "incident_id": str(inc_id),
                "camera_id": str(cam.id),
                "camera_name": cam.name,
                "signature_kind": inc.signature_kind,
                "who_or_what": inc.signature_key,
                "timestamp": ended_at.isoformat(),
                "started_at": inc.started_at.isoformat(),
                "duration_seconds": duration,
                "occurrence_count": inc.occurrence_count,
                "summary": summary_text,
            }
        )

    async def _resolve_provider(self, cam: Camera) -> Provider | None:
        for pid in (cam.summary_provider_id, cam.vlm_provider_id):
            if not pid:
                continue
            try:
                async with async_session() as db:
                    p = await db.get(Provider, pid)
                    if p:
                        db.expunge(p)
                        return p
            except Exception:
                logger.exception("provider lookup failed for incident summary")
        return await get_active_provider()

    async def _build_summary(
        self,
        provider: Provider,
        cam: Camera,
        inc: Incident,
        obs_rows: list[Observation],
    ) -> str | None:
        cam_bits = [b for b in (cam.name, cam.location_label) if b]
        lines = [
            f"Camera: {' / '.join(cam_bits) if cam_bits else 'unnamed'}.",
            f"Incident kind: {inc.signature_kind} ({inc.signature_key}).",
            f"Window: {inc.started_at.isoformat()} -> {inc.last_seen_at.isoformat()}"
            f" (lasted {_humanize_duration((inc.last_seen_at - inc.started_at).total_seconds())},"
            f" {inc.occurrence_count} occurrences).",
            "",
            "Occurrences:",
        ]
        for o in obs_rows[:30]:
            t = o.started_at.strftime("%H:%M:%S")
            desc = (o.vlm_description or "").strip().replace("\n", " ")[:200]
            if desc:
                lines.append(f"- {t} {desc}")
        if len(obs_rows) > 30:
            lines.append(f"- (+{len(obs_rows) - 30} more)")
        lines.append("")
        lines.append(
            "Write a single concise sentence summarizing what happened"
            " across these occurrences. Express any duration in human-readable"
            " terms (minutes or hours), never raw seconds. If nothing notable,"
            " return SKIP."
        )
        prompt = "\n".join(lines)
        max_out = resolve_output_cap(
            cam.summary_max_tokens,
            getattr(provider, "max_output_tokens", None),
        )
        return await call_text(
            provider=provider,
            system_prompt=INCIDENT_SUMMARY_PROMPT,
            user_prompt=prompt,
            max_tokens=max_out,
            camera_id=str(cam.id),
        )

    async def _patch_summary(
        self,
        inc_id: uuid.UUID,
        summary_text: str,
        provider_name: str,
    ) -> None:
        try:
            embed_provider = await get_embedding_provider()
            embedding = await generate_embedding(summary_text, embed_provider)
        except Exception:
            embedding = None
        try:
            async with async_session() as db:
                row = await db.get(Incident, inc_id)
                if row is None:
                    return
                row.summary_text = summary_text
                row.summary_provider_name = provider_name
                if embedding is not None:
                    row.embedding = embedding
                await db.commit()
        except Exception:
            logger.exception("incident summary patch failed inc=%s", inc_id)


# ---- WS broadcasts -------------------------------------------------------


async def _broadcast_opened(inc: Incident) -> None:
    payload = _ws_payload("incident_opened", inc)
    try:
        await ws_broadcast(payload)
    except Exception:
        logger.debug("incident_opened broadcast failed", exc_info=True)


async def _broadcast_updated(inc: Incident) -> None:
    payload = _ws_payload("incident_updated", inc)
    try:
        await ws_broadcast(payload)
    except Exception:
        logger.debug("incident_updated broadcast failed", exc_info=True)


def _ws_payload(kind: str, inc: Incident) -> dict[str, Any]:
    return {
        "type": kind,
        "incident_id": str(inc.id),
        "camera_id": str(inc.camera_id),
        "signature_kind": inc.signature_kind,
        "signature_key": inc.signature_key,
        "started_at": inc.started_at.isoformat(),
        "last_seen_at": inc.last_seen_at.isoformat(),
        "occurrence_count": inc.occurrence_count,
    }
