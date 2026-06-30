"""Temporal sequence rules — in-flight instance lifecycle (slice 1).

A *sequence rule* is a normal rule whose `trigger_pattern` carries a `sequence`
block (docs/sequence-rules-design.md): the base trigger is **step 0 (the
start)**, and `sequence.steps` are the ordered "and then" checks, each with a
time window. This module owns starting / advancing / completing instances; the
RuleEngine calls `evaluate_sequence()` per observation, and a sweeper
(`sequence_sweeper`) expires overdue instances.

Slice 1 scope: `camera` / `incident` / `none` correlation, cheap trigger-predicate
step checks, and the `on_complete` fire. `on_timeout` firing, locate/verify step
checks, and `person` / `journey` correlation are later slices (locate checks are
recognized here and skipped so they never spuriously match yet).

Pure helpers + module-level DB ops (each opens its own short session, mirroring
shared.app_settings) so the orchestration is unit-testable with the DB ops
monkeypatched.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("nurby.events.sequences")

_VALID_MODES = {"camera", "incident", "none", "person", "journey"}
_DEFAULT_MAX_ACTIVE = 20


# ── pure helpers ────────────────────────────────────────────────────────

def get_sequence(trigger_pattern) -> dict | None:
    """Return the sequence config if this is a sequence rule, else None."""
    if not isinstance(trigger_pattern, dict):
        return None
    seq = trigger_pattern.get("sequence")
    if isinstance(seq, dict) and isinstance(seq.get("steps"), list) and seq["steps"]:
        return seq
    return None


def _present_person_ids(data: dict) -> list[str]:
    """Recognized identities present this frame (face person_id, or a track's
    held person identity). De-duped, order preserved."""
    pd = data.get("person_detections") or {}
    out: list[str] = []
    for f in pd.get("faces") or []:
        pid = f.get("person_id")
        if pid and str(pid) not in out:
            out.append(str(pid))
    for t in pd.get("tracks") or []:
        pid = t.get("person_id")
        if pid and str(pid) not in out:
            out.append(str(pid))
    return out


def _present_body_ids(data: dict) -> list[str]:
    """Cross-camera body re-id clusters present this frame (the journey id)."""
    pd = data.get("person_detections") or {}
    out: list[str] = []
    for b in pd.get("bodies") or []:
        bid = b.get("body_cluster_id")
        if bid and str(bid) not in out:
            out.append(str(bid))
    for t in pd.get("tracks") or []:
        bid = t.get("body_cluster_id")
        if bid and str(bid) not in out:
            out.append(str(bid))
    return out


def correlation_keys(data: dict, mode: str, cameras=None) -> list[str]:
    """All keys this observation binds to. One key for camera/incident/none, but
    person/journey can yield several (multiple recognized subjects in frame), so
    a single frame can advance/start a sequence per subject. Empty = out of
    scope or no resolvable subject this frame."""
    cam = str(data.get("camera_id") or "")
    if cameras and cam not in {str(c) for c in cameras}:
        return []  # out of the rule's camera scope
    mode = (mode or "camera").lower()
    if mode == "none":
        return ["all"]
    if mode == "camera":
        return [f"cam:{cam}"] if cam else []
    if mode == "incident":
        inc = data.get("incident_id")
        return [f"inc:{inc}"] if inc else []
    if mode == "person":
        return [f"person:{p}" for p in _present_person_ids(data)]
    if mode == "journey":
        return [f"journey:{b}" for b in _present_body_ids(data)]
    return []


def correlation_key(data: dict, mode: str, cameras=None) -> str | None:
    """First key this observation binds to (see correlation_keys), or None."""
    ks = correlation_keys(data, mode, cameras)
    return ks[0] if ks else None


def step_within_seconds(step: dict) -> int:
    try:
        return max(1, int(step.get("within_seconds", 60)))
    except (TypeError, ValueError):
        return 60


def step_confirm_frames(step: dict) -> int:
    """How many agreeing frames within the window confirm this step. >1 trades
    latency for fewer false hits — agreement across frames substitutes for the
    grounding model's absent score."""
    try:
        return max(1, int(step.get("confirm_frames", 1)))
    except (TypeError, ValueError):
        return 1


def step_check(step: dict) -> dict:
    c = step.get("check")
    return c if isinstance(c, dict) else {}


def is_locate_check(step: dict) -> bool:
    """Grounding-backed step checks are handled in slice 3; recognize them so
    slice 1 skips (never matches) them rather than mis-evaluating."""
    return step_check(step).get("type") in ("locate", "verify")


# Compact observation fields snapshotted into an instance so on_complete /
# on_timeout actions can reference {{vars.trigger.*}} and {{vars.steps.N.*}}.
# Kept small so the JSON column stays bounded.
_SNAPSHOT_FIELDS = (
    "observation_id", "camera_id", "camera_name", "timestamp", "timestamp_local",
    "incident_id", "recording_id", "recording_url", "thumbnail_url", "vlm_description",
)


def _snapshot(data: dict) -> dict:
    return {k: data.get(k) for k in _SNAPSHOT_FIELDS if data.get(k) is not None}


def _reconstruct_obs(inst_vars: dict | None) -> dict:
    """Build an observation_data-like context for an on_timeout fire, which has
    no live frame. The start (trigger) snapshot supplies camera/timestamp, and
    vars expose the whole journey to the action chain."""
    inst_vars = inst_vars or {}
    trig = inst_vars.get("trigger") or {}
    data = dict(trig)
    data["event_kind"] = "sequence_timeout"
    data["vars"] = {"trigger": trig, "steps": inst_vars.get("steps") or []}
    return data


@dataclass
class _Active:
    id: uuid.UUID
    step_index: int
    step_deadline: datetime
    vars: dict | None = None


# ── DB ops (own sessions; monkeypatched in tests) ───────────────────────

async def _find_active_for_key(rule_id, key: str) -> list[_Active]:
    from sqlalchemy import select

    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        rows = (await db.execute(
            select(RuleSequenceInstance).where(
                RuleSequenceInstance.rule_id == rule_id,
                RuleSequenceInstance.status == "active",
                RuleSequenceInstance.correlation_key == key,
            )
        )).scalars().all()
        return [_Active(r.id, r.step_index, r.step_deadline, r.vars) for r in rows]


async def _count_active(rule_id) -> int:
    from sqlalchemy import func as safunc
    from sqlalchemy import select

    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        return int((await db.execute(
            select(safunc.count()).select_from(RuleSequenceInstance).where(
                RuleSequenceInstance.rule_id == rule_id,
                RuleSequenceInstance.status == "active",
            )
        )).scalar() or 0)


async def _create(rule_id, key: str, step_index: int, deadline: datetime, vars: dict | None = None) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        db.add(RuleSequenceInstance(
            rule_id=rule_id, correlation_key=key,
            step_index=step_index, step_deadline=deadline, status="active",
            vars=vars or {"trigger": {}, "steps": []},
        ))
        await db.commit()


async def _advance(instance_id, step_index: int, deadline: datetime, step_snapshot: dict | None = None) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.step_index = step_index
            inst.step_deadline = deadline
            # Reassign vars wholesale so SQLAlchemy detects the JSON change.
            cur = dict(inst.vars or {})
            cur["steps"] = list(cur.get("steps") or []) + [step_snapshot or {}]
            cur["_hits"] = 0  # reset multi-frame confirmation for the new step
            inst.vars = cur
            await db.commit()


async def _bump_hits(instance_id, hits: int) -> None:
    """Record a partial multi-frame confirmation (hits toward confirm_frames)
    without advancing the instance."""
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            cur = dict(inst.vars or {})
            cur["_hits"] = hits
            inst.vars = cur
            await db.commit()


async def _set_status(instance_id, status: str) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.status = status
            await db.commit()


async def _restart(instance_id, deadline: datetime, trigger_snapshot: dict | None = None) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.step_index = 0
            inst.step_deadline = deadline
            inst.vars = {"trigger": trigger_snapshot or {}, "steps": []}
            await db.commit()


async def expire_due(now: datetime | None = None) -> int:
    """Mark active instances past their deadline as expired and fire the rule's
    on_timeout action chain (the absence alert — "X happened but Y never did").
    Returns the number expired."""
    from sqlalchemy import select

    from services.events import firing
    from shared.database import async_session
    from shared.models import Rule, RuleSequenceInstance

    now = now or datetime.now(timezone.utc)
    pending = []  # (rule, on_timeout_actions, severity, inst_vars)
    n = 0
    async with async_session() as db:
        rows = (await db.execute(
            select(RuleSequenceInstance).where(
                RuleSequenceInstance.status == "active",
                RuleSequenceInstance.step_deadline < now,
            ).limit(500)
        )).scalars().all()
        rule_cache: dict = {}
        for r in rows:
            r.status = "expired"
            n += 1
            if r.rule_id not in rule_cache:
                rule_cache[r.rule_id] = await db.get(Rule, r.rule_id)
            rule = rule_cache[r.rule_id]
            if rule and rule.enabled:
                seq = get_sequence(rule.trigger_pattern)
                on_timeout = (seq or {}).get("on_timeout")
                if on_timeout:
                    pending.append((rule, on_timeout, getattr(rule, "severity", None) or "alert", r.vars))
        if n:
            await db.commit()
    # Fire on_timeout chains after the status commit, outside the session.
    for rule, on_timeout, severity, inst_vars in pending:
        try:
            await firing.fire_actions(
                rule, _reconstruct_obs(inst_vars), on_timeout, severity=severity,
            )
        except Exception:
            logger.exception("on_timeout fire failed for rule '%s'", getattr(rule, "name", "?"))
    return n


# ── orchestration ───────────────────────────────────────────────────────

async def _step_matches(step: dict, data: dict, step_match_fn, locate_check_fn) -> bool:
    """Does this observation satisfy ``step``? Cheap trigger-predicate checks go
    through ``step_match_fn``; grounding-backed (locate) checks go through the
    async ``locate_check_fn`` — but only after an optional cheap ``pre_gate``
    predicate passes, so GPU cost is spent only when worthwhile.

    ``step.negate`` inverts the check, so a step can match on ABSENCE. With step
    ordering this expresses a transition: "key NOT in box" then "key in box" =
    he put it in. (A pre_gate that fails still yields no-match, not asserted
    absence — we can't claim a thing is gone if we couldn't look.)"""
    chk = step_check(step)
    negate = bool(step.get("negate"))
    if is_locate_check(step):
        if locate_check_fn is None:
            return False  # grounding not wired (e.g. pure unit tests)
        pre = step.get("pre_gate")
        if isinstance(pre, dict) and pre.get("type") and not step_match_fn(pre):
            return False  # cheap precondition failed; don't spend GPU
        return bool(await locate_check_fn(chk, data)) != negate
    return bool(step_match_fn(chk)) != negate


async def evaluate_sequence(
    rule, seq: dict, data: dict, *,
    start_matched: bool,
    step_match_fn,
    fire_cb,
    locate_check_fn=None,
    now: datetime | None = None,
) -> None:
    """Advance any in-flight instance this observation satisfies, then (if the
    base trigger matched) start a new one. ``step_match_fn(pattern)->bool`` tests
    a step's cheap trigger-predicate check; ``locate_check_fn(check, data)`` runs
    a FindAnything/locate step check; ``fire_cb()`` runs the rule's on_complete
    actions. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        steps = seq.get("steps") or []
        if not steps:
            return
        mode = (seq.get("correlate_by") or "camera").lower()
        if mode not in _VALID_MODES:
            return
        # A frame can bind to several subjects (person/journey), so advance/start
        # per key. camera/incident/none yield a single key.
        keys = correlation_keys(data, mode, seq.get("cameras"))
        if not keys:
            return  # out of scope or no resolvable subject on this frame

        # 1. Advance any in-flight instance this observation satisfies.
        for key in keys:
            await _advance_key(
                rule, key, steps, data, now, step_match_fn, locate_check_fn, fire_cb,
            )

        # 2. Start a new instance per subject when the base trigger matched.
        if not start_matched:
            return
        on_refire = (seq.get("on_refire") or "ignore").lower()
        try:
            max_active = int(seq.get("max_active", _DEFAULT_MAX_ACTIVE) or _DEFAULT_MAX_ACTIVE)
        except (TypeError, ValueError):
            max_active = _DEFAULT_MAX_ACTIVE
        active_count = await _count_active(rule.id)
        first_deadline = now + timedelta(seconds=step_within_seconds(steps[0]))
        for key in keys:
            existing = await _find_active_for_key(rule.id, key)
            if existing:
                if on_refire == "restart":
                    await _restart(existing[0].id, first_deadline, _snapshot(data))
                continue  # ignore: leave the in-flight instance untouched
            if active_count >= max_active:
                logger.info(
                    "sequence rule '%s' at max_active=%d; dropping new start", rule.name, max_active,
                )
                continue
            await _create(rule.id, key, 0, first_deadline, {"trigger": _snapshot(data), "steps": []})
            active_count += 1
    except Exception:
        logger.exception("evaluate_sequence failed for rule '%s'", getattr(rule, "name", "?"))


async def _advance_key(rule, key, steps, data, now, step_match_fn, locate_check_fn, fire_cb) -> None:
    for inst in await _find_active_for_key(rule.id, key):
        if inst.step_deadline and inst.step_deadline < now:
            continue  # overdue; the sweeper will expire it
        if inst.step_index >= len(steps):
            continue
        step = steps[inst.step_index]
        if not await _step_matches(step, data, step_match_fn, locate_check_fn):
            continue
        # Multi-frame confirmation: require K agreeing frames within the window
        # before the step counts. Agreement substitutes for the absent score.
        need = step_confirm_frames(step)
        if need > 1:
            hits = int((inst.vars or {}).get("_hits", 0)) + 1
            if hits < need:
                await _bump_hits(inst.id, hits)
                continue  # not confirmed yet; stay on this step
        nxt = inst.step_index + 1
        if nxt >= len(steps):
            # Complete: thread the journey (trigger + all step snapshots,
            # including this final one) into vars so on_complete actions can
            # reference {{vars.trigger.*}} / {{vars.steps.N.*}}.
            data.setdefault("vars", {})
            data["vars"]["trigger"] = (inst.vars or {}).get("trigger") or {}
            data["vars"]["steps"] = list((inst.vars or {}).get("steps") or []) + [_snapshot(data)]
            data["event_kind"] = "sequence_complete"
            await _set_status(inst.id, "completed")
            await fire_cb()
        else:
            await _advance(
                inst.id, nxt,
                now + timedelta(seconds=step_within_seconds(steps[nxt])),
                _snapshot(data),
            )
