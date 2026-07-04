import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user, require_admin
from shared.config import settings
from shared.database import get_db
from shared.models import Observation, Rule, User
from shared.schemas import (
    RuleCreate,
    RuleReplayResponse,
    RuleReplaySample,
    RuleResponse,
    RuleTestActionPreview,
    RuleTestRequest,
    RuleTestResponse,
    RuleUpdate,
)

router = APIRouter()
logger = logging.getLogger("nurby.api.rules")


async def _publish_invalidation(rule_id: uuid.UUID | str) -> None:
    """Best-effort. perception listens on ``nurby:rules:invalidate`` and
    re-loads the rule set on the next evaluate() tick. Failures here
    only mean the perception engine waits up to its 30s passive TTL
    instead of refreshing within ~1s.

    Also drops the rule's Redis cooldown key so an edited rule starts
    from a clean slate. without this, shortening a cooldown has no
    effect until the old (longer) cooldown key expires.
    """
    try:
        import redis.asyncio as aioredis

        from services.events.engine import RULES_INVALIDATE_CHANNEL, RuleEngine

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.publish(RULES_INVALIDATE_CHANNEL, str(rule_id))
            await client.delete(RuleEngine.COOLDOWN_KEY_PREFIX + str(rule_id))
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
    except Exception:
        logger.debug("rule invalidation publish failed", exc_info=True)


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _collect_rule_refs(
    trigger_pattern, conditions, actions
) -> tuple[dict[str, list[tuple[str, uuid.UUID]]], list[str]]:
    """Gather every camera/person/telegram-channel/device reference in a
    rule, as (field_path, id) pairs, plus messages for values sitting in
    a ref position that are not UUIDs at all (e.g. an LLM writing a
    camera NAME into camera_ids — previously a silent never-match)."""
    refs: dict[str, list[tuple[str, uuid.UUID]]] = {
        "camera": [],
        "person": [],
        "telegram_channel": [],
        "device": [],
    }
    malformed: list[str] = []

    def add(kind: str, path: str, value) -> None:
        if value is None or value == "":
            return
        u = _as_uuid(value)
        if u is not None:
            refs[kind].append((path, u))
        else:
            malformed.append(
                f"{path} is not a valid {kind} id (got '{str(value)[:60]}'); use the entity's UUID"
            )

    tp = trigger_pattern if isinstance(trigger_pattern, dict) else {}
    add("camera", "trigger_pattern.camera_id", tp.get("camera_id"))
    add("person", "trigger_pattern.person_id", tp.get("person_id"))
    seq = tp.get("sequence")
    if isinstance(seq, dict):
        for i, cam in enumerate(seq.get("cameras") or []):
            add("camera", f"sequence.cameras[{i}]", cam)
        for i, step in enumerate(seq.get("steps") or []):
            check = step.get("check") if isinstance(step, dict) else None
            if isinstance(check, dict):
                add("camera", f"sequence.steps[{i}].camera_id", check.get("camera_id"))
                add("person", f"sequence.steps[{i}].person_id", check.get("person_id"))

    cond = conditions if isinstance(conditions, dict) else {}
    add("camera", "conditions.camera_id", cond.get("camera_id"))
    for i, cam in enumerate(cond.get("camera_ids") or []):
        add("camera", f"conditions.camera_ids[{i}]", cam)

    items = actions if isinstance(actions, list) else [actions] if isinstance(actions, dict) else []
    for i, action in enumerate(items):
        if not isinstance(action, dict):
            continue
        if action.get("type") == "telegram":
            add("telegram_channel", f"actions[{i}].channel_id", action.get("channel_id"))
        elif action.get("type") == "device":
            add("device", f"actions[{i}].device_id", action.get("device_id"))
    return refs, malformed


async def _stale_rule_refs(db: AsyncSession, trigger_pattern, conditions, actions) -> list[str]:
    """Return one human message per reference that matches no existing row.

    Catches the classic silent never-fire: a rule pointing at a deleted
    (or mistyped) camera/person/channel evaluates forever without matching
    and without erroring."""
    from shared.models import Camera, Device, Person, TelegramChannel

    refs, messages_pre = _collect_rule_refs(trigger_pattern, conditions, actions)
    model_by_kind = {
        "camera": Camera,
        "person": Person,
        "telegram_channel": TelegramChannel,
        "device": Device,
    }
    label_by_kind = {
        "camera": "camera",
        "person": "person",
        "telegram_channel": "Telegram channel",
        "device": "device",
    }
    messages: list[str] = list(messages_pre)
    for kind, pairs in refs.items():
        if not pairs:
            continue
        ids = {u for _, u in pairs}
        model = model_by_kind[kind]
        rows = await db.execute(select(model.id).where(model.id.in_(ids)))
        existing = {r[0] for r in rows.all()}
        for path, u in pairs:
            if u not in existing:
                messages.append(f"{path} does not match any {label_by_kind[kind]} ({u})")
    return messages


@router.get("", response_model=list[RuleResponse])
async def list_rules(_current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).order_by(Rule.created_at))
    return result.scalars().all()


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    body: RuleCreate,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stale = await _stale_rule_refs(db, body.trigger_pattern, body.conditions, body.actions)
    if stale:
        raise HTTPException(status_code=422, detail="; ".join(stale))
    rule = Rule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await _publish_invalidation(rule.id)
    return rule


@router.get("/last-fired")
async def rules_last_fired(
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Map of rule_id -> most recent fired_at, in one GROUP BY.

    Replaces the frontend workaround that fetched 200 events and
    aggregated client-side (missing anything older than the window)."""
    from sqlalchemy import func as sa_func

    from shared.models import Event

    rows = (
        await db.execute(
            select(Event.rule_id, sa_func.max(Event.fired_at))
            .where(Event.rule_id.is_not(None))
            .group_by(Event.rule_id)
        )
    ).all()
    return {str(rule_id): fired_at.isoformat() for rule_id, fired_at in rows}


@router.get("/schema")
async def rules_schema(_current_user: User = Depends(get_current_user)):
    """Introspection: every trigger type, action type, condition field, and
    the sequence block shape. Static registry (shared/rule_schema.py), so
    the frontend and NL rule generation stop hardcoding enums. Must stay
    registered before the /{rule_id} catch-all."""
    from shared.rule_schema import build_schema

    return build_schema()


@router.get("/health")
async def rules_health(
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Per-rule health aggregate for the rules list: last fire, 7-day fire
    count, latest action outcome, and stale references (camera/person/
    channel ids that no longer exist). Supersedes /last-fired, which is
    kept for compatibility."""
    from sqlalchemy import func as sa_func

    from shared.models import Event

    rules = (await db.execute(select(Rule))).scalars().all()

    last_fired = dict(
        (
            await db.execute(
                select(Event.rule_id, sa_func.max(Event.fired_at))
                .where(Event.rule_id.is_not(None))
                .group_by(Event.rule_id)
            )
        ).all()
    )
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    fires_7d = dict(
        (
            await db.execute(
                select(Event.rule_id, sa_func.count())
                .where(Event.rule_id.is_not(None), Event.fired_at >= week_ago)
                .group_by(Event.rule_id)
            )
        ).all()
    )
    # Latest event per rule for action_status/action_error (Postgres
    # DISTINCT ON keeps only the newest row per rule_id).
    latest = {
        rule_id: (status, error)
        for rule_id, status, error in (
            await db.execute(
                select(Event.rule_id, Event.action_status, Event.action_error)
                .where(Event.rule_id.is_not(None))
                .distinct(Event.rule_id)
                .order_by(Event.rule_id, Event.fired_at.desc())
            )
        ).all()
    }

    out: dict[str, dict] = {}
    for rule in rules:
        stale = await _stale_rule_refs(db, rule.trigger_pattern, rule.conditions, rule.actions)
        fired_at = last_fired.get(rule.id)
        status, error = latest.get(rule.id, (None, None))
        out[str(rule.id)] = {
            "last_fired_at": fired_at.isoformat() if fired_at else None,
            "fires_7d": int(fires_7d.get(rule.id, 0)),
            "last_action_status": status,
            "last_action_error": error,
            "stale_refs": stale,
        }
    return out


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    updates = body.model_dump(exclude_unset=True)
    stale = await _stale_rule_refs(
        db,
        updates.get("trigger_pattern", rule.trigger_pattern),
        updates.get("conditions", rule.conditions),
        updates.get("actions", rule.actions),
    )
    if stale:
        raise HTTPException(status_code=422, detail="; ".join(stale))
    for field, value in updates.items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    await _publish_invalidation(rule.id)
    return rule


@router.post("/{rule_id}/snooze", response_model=RuleResponse)
async def snooze_rule(
    rule_id: uuid.UUID,
    duration_seconds: int = Query(default=3600, ge=60, le=604800),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Web counterpart to the Telegram 💤 button. Sets ``snoozed_until``
    (default 1 hour, same as Telegram); notification sends for this rule
    are suppressed until then. Use /unsnooze to clear early."""
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.snoozed_until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.post("/{rule_id}/unsnooze", response_model=RuleResponse)
async def unsnooze_rule(
    rule_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear a snooze before it expires."""
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.snoozed_until = None
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    await _publish_invalidation(rule_id)


# ── Dry-run helpers (used by /test and /replay) ───────────────────
#
# The synthesis function builds an observation_data dict shaped to
# match the engine's _match_trigger expectations for each trigger
# type. The shapes follow the perception worker's runtime conventions,
# not the Observation SQL columns, so e.g. ``audio_event`` is a single
# dict not a list (the engine reads ``data["audio_event"]`` directly).
# If the perception worker ever changes its observation_data shape,
# update both _synthesize_observation_for_trigger and the engine in
# lockstep.

def _window_midpoint(after: str | None, before: str | None) -> tuple[int, int] | None:
    """Midpoint (hour, minute) of an HH:MM window, for placing a test
    timestamp inside a red-light window. None when no window is set."""
    def _mins(s):
        try:
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return None

    a = _mins(after) if after else None
    b = _mins(before) if before else None
    if a is None and b is None:
        return None
    if a is None:
        mid = b // 2
    elif b is None:
        mid = (a + 24 * 60) // 2 % (24 * 60)
    elif a <= b:
        mid = (a + b) // 2
    else:  # overnight window wraps midnight
        mid = (a + (b + 24 * 60)) // 2 % (24 * 60)
    return (mid // 60, mid % 60)


def _straddle_boxes(a, b):
    """Two bboxes whose centroids sit on opposite sides of segment a-b, so
    a track moving prev->cur crosses the line. Used to synthesize tripwire
    / speed-gate crossings for the rule tester."""
    import math as _math

    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    nlen = _math.hypot(dx, dy) or 1.0
    nx, ny = -dy / nlen, dx / nlen
    k = 25.0
    p1 = (mx - nx * k, my - ny * k)
    p2 = (mx + nx * k, my + ny * k)

    def _box(c):
        return [int(c[0] - 10), int(c[1] - 20), int(c[0] + 10), int(c[1] + 20)]

    return _box(p1), _box(p2)


def _synthesize_observation_for_trigger(
    trigger_pattern: dict,
    camera_id: uuid.UUID | None,
) -> dict:
    """Build a permissive observation dict that should match ``trigger_pattern``.

    Permissive means we err on the side of "yes, the trigger matches"
    so the user gets to verify their conditions / actions even when
    they have not described a fully-fleshed scenario.
    """
    t = trigger_pattern.get("type")
    cam = str(camera_id) if camera_id else "test-camera"
    obs: dict = {
        "observation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": cam,
    }

    if t == "object_detected":
        label = trigger_pattern.get("label") or "person"
        obs["object_detections"] = {
            "objects": [{"label": label, "confidence": 0.9}],
        }

    elif t == "face_recognized":
        pid = trigger_pattern.get("person_id") or str(uuid.uuid4())
        obs["person_detections"] = {
            "count": 1,
            "faces": [{"person_id": str(pid), "confidence": 0.9}],
        }

    elif t == "face_unknown":
        obs["person_detections"] = {
            "count": 1,
            "faces": [{"cluster_id": str(uuid.uuid4()), "person_id": None}],
        }

    elif t == "face_detected":
        obs["person_detections"] = {
            "count": 1,
            "faces": [{"confidence": 0.9}],
        }

    elif t == "motion":
        score = float(trigger_pattern.get("min_score", 0.01))
        obs["motion_score"] = score + 0.05

    elif t == "audio_event":
        label = trigger_pattern.get("label") or "baby_cry"
        score = float(trigger_pattern.get("min_score", 0.3)) + 0.1
        # Engine reads data["audio_event"] (singular dict).
        obs["audio_event"] = {"label": label, "score": score}

    elif t == "clap_pattern":
        count = int(trigger_pattern.get("count", 2))
        obs["clap_pattern"] = {"count": count}
        pcam = trigger_pattern.get("camera_id")
        if pcam:
            obs["camera_id"] = pcam

    elif t == "speech_phrase":
        phrases = trigger_pattern.get("phrases") or ["hello"]
        first = next((str(p) for p in phrases if str(p).strip()), "hello")
        obs["transcript"] = {"text": first}
        pcam = trigger_pattern.get("camera_id")
        if pcam:
            obs["camera_id"] = pcam

    elif t == "loitering":
        # Inline geometry mode. Place a track inside the polygon and
        # backdate the entry timestamp so the engine fires immediately.
        # The engine reads from self._loiter_entry. tests using this
        # endpoint just need first-call match semantics, which the
        # legacy "loitering_events" pre-computed list provides without
        # needing two evaluate() calls.
        label = trigger_pattern.get("label") or "person"
        threshold = float(trigger_pattern.get("threshold_seconds", 30))
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = pcam
        obs["loitering_events"] = [{
            "camera_id": str(pcam),
            "label": label,
            "duration_seconds": threshold + 1,
            "rule_id": None,
            "zone_name": trigger_pattern.get("zone_name") or "test-zone",
        }]

    elif t == "line_cross":
        label = trigger_pattern.get("label") or "person"
        direction = trigger_pattern.get("direction") or "in"
        if direction == "any":
            direction = "in"
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = pcam
        obs["line_cross_events"] = [{
            "camera_id": str(pcam),
            "label": label,
            "direction": direction,
            "zone_name": trigger_pattern.get("zone_name") or "test-line",
        }]

    elif t in ("camera_offline", "camera_online"):
        # Synthetic availability edge, matching what the ingestion worker
        # publishes on a real transition (see CameraStatusWatcher).
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = str(pcam)
        obs["event_kind"] = "camera_status"
        obs["camera_status"] = "offline" if t == "camera_offline" else "online"
        obs["previous_status"] = "recording" if t == "camera_offline" else "offline"
        obs["status_reason"] = "synthesized test transition"
        obs["camera_name"] = "Test Camera"

    elif t in ("incident_started", "incident_ended"):
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = str(pcam)
        obs["event_kind"] = "incident"
        obs["incident_event"] = "started" if t == "incident_started" else "ended"
        obs["incident_id"] = str(uuid.uuid4())
        obs["camera_name"] = "Test Camera"
        obs["signature_kind"] = trigger_pattern.get("signature_kind") or "person"
        obs["who_or_what"] = "test-subject"
        obs["occurrence_count"] = max(1, int(trigger_pattern.get("min_occurrences") or 1))
        if t == "incident_ended":
            obs["duration_seconds"] = float(trigger_pattern.get("min_duration_seconds") or 60) + 1
            obs["summary"] = "Synthesized incident recap for testing."

    elif t == "plate_list":
        mode = (trigger_pattern.get("mode") or "blacklist").lower()
        plates = trigger_pattern.get("plates") or []
        # Blacklist: synthesize a listed plate. Whitelist: an unlisted one.
        if mode == "blacklist":
            plate = (plates[0] if plates else "ABC123")
        else:
            plate = "NOTLISTED9"
        obs["vehicle_detections"] = {
            "vehicles": [{"bbox": [10, 10, 60, 50], "label": "car",
                          "confidence": 0.9, "plate_text": plate,
                          "zones": []}],
            "count": 1,
        }

    elif t == "parking_violation":
        spot = trigger_pattern.get("spot_zone") or "Reserved spot"
        obs["vehicle_detections"] = {
            "vehicles": [{"bbox": [10, 10, 60, 50], "label": "car",
                          "confidence": 0.9, "plate_text": "INTRUDER1",
                          "zones": [spot]}],
            "count": 1,
        }
        obs["tracks"] = [{"track_id": 1, "label": "car",
                          "bbox": [10, 10, 60, 50], "prev_bbox": [10, 10, 60, 50],
                          "state": "stationary"}]

    elif t == "wrong_way":
        import math as _math
        pts = trigger_pattern.get("points")
        label = trigger_pattern.get("label") or "car"
        allowed = trigger_pattern.get("allowed_direction", "in")
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = str(pcam)
        if pts and len(pts) == 2:
            a, b = pts[0], pts[1]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            dx, dy = b[0] - a[0], b[1] - a[1]
            nlen = _math.hypot(dx, dy) or 1.0
            nx, ny = -dy / nlen, dx / nlen
            k = 25.0
            p1 = (mx - nx * k, my - ny * k)
            p2 = (mx + nx * k, my + ny * k)

            def _side(pt):
                return dx * (pt[1] - a[1]) - dy * (pt[0] - a[0])

            dir12 = "in" if _side(p2) > _side(p1) else "out"
            # Orient the synthetic crossing AGAINST the allowed direction so
            # the tester confirms a wrong-way fire.
            prev_c, cur_c = (p2, p1) if dir12 == allowed else (p1, p2)
        else:
            prev_c, cur_c = (100, 100), (100, 60)

        def _box(c):
            return [int(c[0] - 10), int(c[1] - 20), int(c[0] + 10), int(c[1] + 20)]

        obs["tracks"] = [{
            "track_id": 1, "label": label,
            "bbox": _box(cur_c), "prev_bbox": _box(prev_c), "state": "moving",
        }]

    elif t == "red_light_cross":
        pts = trigger_pattern.get("points")
        label = trigger_pattern.get("label") or "car"
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = str(pcam)
        if pts and len(pts) == 2:
            prev_box, cur_box = _straddle_boxes(pts[0], pts[1])
        else:
            prev_box, cur_box = [90, 90, 110, 130], [90, 50, 110, 90]
        obs["tracks"] = [{
            "track_id": 1, "label": label,
            "bbox": cur_box, "prev_bbox": prev_box, "state": "moving",
        }]
        # If the rule gates on a detected signal zone, synthesize that zone
        # as red so the dry run exercises the crossing. Otherwise the
        # endpoint stamps a timestamp inside the manual red window instead.
        signal_zone = trigger_pattern.get("signal_zone")
        if signal_zone:
            obs["signal_states"] = {signal_zone: "red"}

    elif t == "speed_over":
        # A single gate-A crossing frame. The /test endpoint builds the
        # paired gate-B frame at a later timestamp so the engine can time
        # the traversal; a single observation cannot measure speed.
        la = trigger_pattern.get("line_a")
        label = trigger_pattern.get("label") or "car"
        pcam = trigger_pattern.get("camera_id") or cam
        obs["camera_id"] = str(pcam)
        if la and len(la) == 2:
            prev_box, cur_box = _straddle_boxes(la[0], la[1])
        else:
            prev_box, cur_box = [90, 90, 110, 130], [90, 50, 110, 90]
        obs["tracks"] = [{
            "track_id": 1, "label": label,
            "bbox": cur_box, "prev_bbox": prev_box, "state": "moving",
        }]

    elif t == "crosswalk_violation":
        zone = trigger_pattern.get("crosswalk_zone") or "Crosswalk"
        veh_label = trigger_pattern.get("vehicle_label") or "car"
        # A pedestrian and a vehicle in the same crosswalk zone.
        obs["object_detections"] = {
            "objects": [
                {"label": "person", "confidence": 0.9, "bbox": [20, 20, 50, 90],
                 "tracker_id": 1, "zones": [zone]},
                {"label": veh_label, "confidence": 0.9, "bbox": [60, 30, 140, 110],
                 "tracker_id": 2, "zones": [zone]},
            ],
            "count": 2,
        }

    elif t == "lane_occupancy":
        zone = trigger_pattern.get("lane_zone") or "Lane"
        label = trigger_pattern.get("label") or "car"
        n = max(1, int(trigger_pattern.get("min_vehicles") or 3))
        stationary = bool(trigger_pattern.get("require_stationary"))
        objs = [
            {"label": label, "confidence": 0.9,
             "bbox": [10 + i * 40, 30, 45 + i * 40, 110],
             "tracker_id": i + 1, "zones": [zone]}
            for i in range(n)
        ]
        obs["object_detections"] = {"objects": objs, "count": len(objs)}
        if stationary:
            obs["tracks"] = [
                {"track_id": o["tracker_id"], "label": label,
                 "bbox": o["bbox"], "prev_bbox": o["bbox"], "state": "stationary"}
                for o in objs
            ]

    elif t == "any":
        pass

    return obs


def _observation_to_engine_payload(observation: Observation) -> dict:
    """Reconstruct an observation_data dict from a stored Observation row.

    The perception worker emits observation_data as a single dict but
    the Observation table only stores a subset of the runtime fields
    (object_detections, person_detections, vlm_description, etc.).
    Trigger types that depend on transient fields like ``tracks`` or
    ``audio_event`` will not match against replayed rows. We document
    that limitation in the response (samples come back empty) instead
    of silently lying.
    """
    return {
        "observation_id": str(observation.id),
        "camera_id": str(observation.camera_id) if observation.camera_id else None,
        "timestamp": observation.started_at.isoformat() if observation.started_at else None,
        "object_detections": observation.object_detections or {},
        "person_detections": observation.person_detections or {},
        "vlm_description": observation.vlm_description or "",
        "confidence": observation.confidence,
        "thumbnail_path": observation.thumbnail_path,
    }


def _render_actions_preview(actions: list[dict], observation: dict, rule) -> list[RuleTestActionPreview]:
    """Render each action's templated fields against the observation.

    No action is executed. For vlm_call we leave the prompt template
    rendered so the user can preview what would be sent to the model.
    For webhook we render the payload_template into a dict so the user
    sees the final body. For telegram we render the text template.
    """
    from services.events.actions import _build_template_context
    from services.events.templates import render

    # Use a deterministic placeholder event_id so the preview matches
    # what the action chain would see.
    preview_event_id = uuid.uuid4()
    ctx = _build_template_context(observation, rule, preview_event_id)

    out: list[RuleTestActionPreview] = []
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        rendered = render(action, ctx, strict=False)
        out.append(RuleTestActionPreview(
            index=idx,
            action_type=str(action.get("type") or "unknown"),
            rendered_action=rendered if isinstance(rendered, dict) else {"value": rendered},
        ))
    return out


def _explain_outcome(
    matched_trigger: bool,
    matched_conditions: bool,
    trigger_pattern: dict,
    conditions: dict | None,
    observation: dict,
    tz,
) -> str:
    """Build a human-friendly explanation for the test result."""
    if not matched_trigger:
        t = trigger_pattern.get("type")
        if t == "object_detected":
            want = trigger_pattern.get("label")
            seen = [d.get("label") for d in (observation.get("object_detections") or {}).get("objects", [])]
            if want:
                return f"Trigger did not match. expected label '{want}', observation had {seen or 'no objects'}."
            return "Trigger did not match. no object detections in observation."
        if t == "motion":
            want = trigger_pattern.get("min_score", 0.01)
            return f"Trigger did not match. motion_score {observation.get('motion_score', 0)} below min_score {want}."
        if t == "face_recognized":
            return "Trigger did not match. no recognized face in observation."
        return f"Trigger did not match. trigger type '{t}' found no matching content."

    if not matched_conditions and conditions:
        # Identify which condition blocked us so the UI can highlight it.
        from datetime import datetime as _dt
        cam_ids = conditions.get("camera_ids")
        cam = conditions.get("camera_id")
        if cam_ids and observation.get("camera_id") not in cam_ids:
            return f"Camera filter blocked. observation camera {observation.get('camera_id')} not in {cam_ids}."
        if cam and not cam_ids and observation.get("camera_id") != cam:
            return f"Camera filter blocked. observation camera {observation.get('camera_id')} != {cam}."
        days = conditions.get("days")
        if days:
            day_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
            today = day_map.get(_dt.now(tz).weekday(), "")
            if today not in days:
                return f"Schedule blocked. today is {today}, rule only runs on {days}."
        time_after = conditions.get("time_after")
        time_before = conditions.get("time_before")
        if time_after or time_before:
            now_t = _dt.now(tz).strftime("%H:%M")
            window = f"{time_after or '00:00'}-{time_before or '23:59'}"
            return f"Schedule blocked. current time {now_t} outside window {window}."
        min_conf = conditions.get("min_confidence")
        if min_conf is not None:
            got = observation.get("confidence") or 0
            return f"Confidence too low. min_confidence {min_conf} required, observation has {got}."
        return "Conditions blocked the trigger."

    return "Trigger matched and all conditions passed."


@router.post("/test", response_model=RuleTestResponse)
async def test_rule(
    body: RuleTestRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run a (possibly unsaved) rule against a synthesized observation.

    No event is written. No action is executed. The response includes
    the observation that was evaluated so the UI can show "this is
    what we tested against".
    """
    from services.events.engine import RuleEngine

    # Build the observation: explicit > recent-by-camera > synthesized.
    observation: dict | None = None
    if body.dry_run_observation is not None:
        observation = dict(body.dry_run_observation)
        observation.setdefault("observation_id", str(uuid.uuid4()))
        observation.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        if body.camera_id:
            observation.setdefault("camera_id", str(body.camera_id))
    elif body.camera_id is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        q = (
            select(Observation)
            .where(Observation.camera_id == body.camera_id)
            .where(Observation.started_at >= cutoff)
            .order_by(Observation.started_at.desc())
            .limit(1)
        )
        result = await db.execute(q)
        row = result.scalars().first()
        if row is not None:
            observation = _observation_to_engine_payload(row)

    if observation is None:
        observation = _synthesize_observation_for_trigger(body.trigger_pattern, body.camera_id)

    # Build a fake rule and run the engine's pure matcher methods.
    fake_rule = SimpleNamespace(
        id=uuid.uuid4(),
        name="__test__",
        enabled=True,
        trigger_pattern=body.trigger_pattern,
        conditions=body.conditions,
        actions=body.actions,
        cooldown_seconds=body.cooldown_seconds,
    )
    engine = RuleEngine()
    tz = await engine._resolve_timezone()

    ttype = body.trigger_pattern.get("type")
    if ttype == "speed_over":
        # Speed needs two crossings over time. Feed a gate-A frame then a
        # gate-B frame spaced so the measured speed clearly beats the
        # threshold, through the same engine instance.
        la = body.trigger_pattern.get("line_a")
        lb = body.trigger_pattern.get("line_b")
        dist = float(body.trigger_pattern.get("distance_m") or 10)
        min_kmh = float(body.trigger_pattern.get("min_speed_kmh") or 30)
        label = body.trigger_pattern.get("label") or "car"
        camv = str(body.camera_id) if body.camera_id else "test-camera"
        matched_trigger = False
        if la and len(la) == 2 and lb and len(lb) == 2:
            target_kmh = max(min_kmh * 2, min_kmh + 10)
            dt = dist / (target_kmh / 3.6)  # seconds to clear the gates
            t0 = datetime.now(timezone.utc)
            a_prev, a_cur = _straddle_boxes(la[0], la[1])
            b_prev, b_cur = _straddle_boxes(lb[0], lb[1])
            for stamp, prev_box, cur_box in (
                (t0, a_prev, a_cur),
                (t0 + timedelta(seconds=dt), b_prev, b_cur),
            ):
                frame = {
                    "camera_id": camv,
                    "timestamp": stamp.isoformat(),
                    "tracks": [{"track_id": 1, "label": label,
                                "bbox": cur_box, "prev_bbox": prev_box,
                                "state": "moving"}],
                }
                matched_trigger = engine._match_trigger(
                    body.trigger_pattern, frame, fake_rule.id, tz
                )
                observation = frame
    elif ttype == "lane_occupancy" and float(body.trigger_pattern.get("sustain_seconds") or 0) > 0:
        # Sustained congestion needs the lane to stay over threshold across
        # time. Feed the synthesized over-threshold frame twice, spaced past
        # the sustain window, so the dry run confirms it would fire.
        sustain = float(body.trigger_pattern.get("sustain_seconds"))
        t0 = datetime.now(timezone.utc)
        matched_trigger = False
        for stamp in (t0, t0 + timedelta(seconds=sustain + 1)):
            frame = dict(observation)
            frame["timestamp"] = stamp.isoformat()
            matched_trigger = engine._match_trigger(
                body.trigger_pattern, frame, fake_rule.id, tz
            )
            observation = frame
    else:
        if ttype == "red_light_cross":
            # Stamp a timestamp inside the configured red window so the
            # window check passes during the test.
            ra = body.trigger_pattern.get("red_after")
            rb = body.trigger_pattern.get("red_before")
            mid = _window_midpoint(ra, rb)
            if mid is not None:
                ref = datetime.now(tz).replace(
                    hour=mid[0], minute=mid[1], second=0, microsecond=0
                )
                observation["timestamp"] = ref.astimezone(timezone.utc).isoformat()
        # Persistence-aware dry run: a min_frames=N rule needs the same
        # object to match on N keyframes, so feed the synthesized
        # observation through N times (the engine keeps the streak in-memory).
        eval_rounds = max(1, int(body.trigger_pattern.get("min_frames") or 1))
        matched_trigger = False
        for _ in range(eval_rounds):
            matched_trigger = engine._match_trigger(
                body.trigger_pattern, observation, fake_rule.id, tz
            )
    matched_conditions = engine._check_conditions(body.conditions or {}, observation, tz)
    schedule_blocked = matched_trigger and not matched_conditions
    matched = matched_trigger and matched_conditions

    reason = _explain_outcome(
        matched_trigger, matched_conditions, body.trigger_pattern, body.conditions, observation, tz,
    )

    would_fire = _render_actions_preview(body.actions or [], observation, fake_rule)

    warnings = await _stale_rule_refs(db, body.trigger_pattern, body.conditions, body.actions)

    return RuleTestResponse(
        matched=matched,
        reason=reason,
        matched_trigger=matched_trigger,
        matched_conditions=matched_conditions,
        schedule_blocked=schedule_blocked,
        cooldown_active=False,
        synthesized_observation=observation,
        would_fire=would_fire,
        warnings=warnings,
    )


@router.post("/{rule_id}/replay", response_model=RuleReplayResponse)
async def replay_rule(
    rule_id: uuid.UUID,
    hours: int = Query(default=24, ge=1, le=168),
    limit_samples: int = Query(default=5, ge=1, le=25),
    max_scanned: int = Query(default=10_000, ge=1, le=10_000),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replay a saved rule over the last ``hours`` of real observations.

    Pure read-only. We never write an Event row or execute an action.
    ``samples`` is capped by ``limit_samples``. ``scanned`` is capped
    by ``max_scanned``. ``hours`` is capped at 168 (7 days).

    Note. trigger types that depend on transient runtime fields like
    ``tracks`` (inline-geometry loitering/line_cross), ``audio_event``,
    ``transcript``, or ``clap_pattern`` will not match historical rows
    because those fields are not persisted on the Observation table.
    Those rules return scanned > 0 but matched = 0; the UI should
    show a tooltip explaining that replay is detection-only.
    """
    from services.events.engine import RuleEngine

    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Clamp inputs defensively. Query() bounds already enforce these
    # but a future caller that bypasses the validator (e.g. internal
    # use) still gets the same caps.
    hours = min(max(hours, 1), 168)
    limit_samples = min(max(limit_samples, 1), 25)
    max_scanned = min(max(max_scanned, 1), 10_000)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        select(Observation)
        .where(Observation.started_at >= cutoff)
        .order_by(Observation.started_at.desc())
        .limit(max_scanned)
    )

    conds = rule.conditions or {}
    cam_ids = conds.get("camera_ids")
    cam_id = conds.get("camera_id")
    if cam_ids:
        try:
            uuid_list = [uuid.UUID(str(c)) for c in cam_ids]
            q = q.where(Observation.camera_id.in_(uuid_list))
        except (ValueError, TypeError):
            pass
    elif cam_id:
        try:
            q = q.where(Observation.camera_id == uuid.UUID(str(cam_id)))
        except (ValueError, TypeError):
            pass

    result = await db.execute(q)
    rows = list(result.scalars().all())

    engine = RuleEngine()
    tz = await engine._resolve_timezone()

    scanned = 0
    matched_count = 0
    samples: list[RuleReplaySample] = []
    first_at: datetime | None = None
    last_at: datetime | None = None

    for row in rows:
        scanned += 1
        payload = _observation_to_engine_payload(row)
        if not engine._match_trigger(rule.trigger_pattern, payload, rule.id):
            continue
        if rule.conditions and not engine._check_conditions(rule.conditions, payload, tz):
            continue
        matched_count += 1
        ts = row.started_at
        if first_at is None or (ts and ts < first_at):
            first_at = ts
        if last_at is None or (ts and ts > last_at):
            last_at = ts
        if len(samples) < limit_samples:
            snippet = None
            if row.vlm_description:
                snippet = row.vlm_description[:140]
            else:
                # Fallback. compact detection summary so the UI has
                # something to show when the VLM did not run.
                objs = (row.object_detections or {}).get("objects") if isinstance(row.object_detections, dict) else None
                if objs:
                    labels = sorted({str(d.get("label")) for d in objs if d.get("label")})
                    if labels:
                        snippet = ", ".join(labels)[:140]
            samples.append(RuleReplaySample(
                observation_id=row.id,
                timestamp=row.started_at,
                camera_id=row.camera_id,
                thumbnail_path=row.thumbnail_path,
                snippet=snippet,
            ))

    return RuleReplayResponse(
        rule_id=rule_id,
        hours=hours,
        scanned=scanned,
        matched=matched_count,
        first_matched_at=first_at,
        last_matched_at=last_at,
        samples=samples,
    )
