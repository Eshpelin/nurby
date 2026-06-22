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

# Correlation modes implemented in slice 1. person/journey are accepted by the
# schema but resolve to no key here (no-op) until slice 4.
_SLICE1_MODES = {"camera", "incident", "none"}
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


def correlation_key(data: dict, mode: str, cameras=None) -> str | None:
    """Key that binds an observation to an in-flight instance, or None when the
    observation is out of scope / the mode isn't resolvable for this frame."""
    cam = str(data.get("camera_id") or "")
    if cameras:
        if cam not in {str(c) for c in cameras}:
            return None  # out of the rule's camera scope
    mode = (mode or "camera").lower()
    if mode == "none":
        return "all"
    if mode == "camera":
        return f"cam:{cam}" if cam else None
    if mode == "incident":
        inc = data.get("incident_id")
        return f"inc:{inc}" if inc else None
    # person / journey — slice 4
    return None


def step_within_seconds(step: dict) -> int:
    try:
        return max(1, int(step.get("within_seconds", 60)))
    except (TypeError, ValueError):
        return 60


def step_check(step: dict) -> dict:
    c = step.get("check")
    return c if isinstance(c, dict) else {}


def is_locate_check(step: dict) -> bool:
    """Grounding-backed step checks are handled in slice 3; recognize them so
    slice 1 skips (never matches) them rather than mis-evaluating."""
    return step_check(step).get("type") in ("locate", "verify")


@dataclass
class _Active:
    id: uuid.UUID
    step_index: int
    step_deadline: datetime


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
        return [_Active(r.id, r.step_index, r.step_deadline) for r in rows]


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


async def _create(rule_id, key: str, step_index: int, deadline: datetime) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        db.add(RuleSequenceInstance(
            rule_id=rule_id, correlation_key=key,
            step_index=step_index, step_deadline=deadline, status="active",
        ))
        await db.commit()


async def _advance(instance_id, step_index: int, deadline: datetime) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.step_index = step_index
            inst.step_deadline = deadline
            await db.commit()


async def _set_status(instance_id, status: str) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.status = status
            await db.commit()


async def _restart(instance_id, deadline: datetime) -> None:
    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    async with async_session() as db:
        inst = await db.get(RuleSequenceInstance, instance_id)
        if inst and inst.status == "active":
            inst.step_index = 0
            inst.step_deadline = deadline
            await db.commit()


async def expire_due(now: datetime | None = None) -> int:
    """Mark active instances past their deadline as expired. Returns the count.
    (on_timeout firing is slice 2; this just stops them lingering/advancing.)"""
    from sqlalchemy import select

    from shared.database import async_session
    from shared.models import RuleSequenceInstance

    now = now or datetime.now(timezone.utc)
    n = 0
    async with async_session() as db:
        rows = (await db.execute(
            select(RuleSequenceInstance).where(
                RuleSequenceInstance.status == "active",
                RuleSequenceInstance.step_deadline < now,
            ).limit(500)
        )).scalars().all()
        for r in rows:
            r.status = "expired"
            n += 1
        if n:
            await db.commit()
    return n


# ── orchestration ───────────────────────────────────────────────────────

async def evaluate_sequence(
    rule, seq: dict, data: dict, *,
    start_matched: bool,
    step_match_fn,
    fire_cb,
    now: datetime | None = None,
) -> None:
    """Advance any in-flight instance this observation satisfies, then (if the
    base trigger matched) start a new one. ``step_match_fn(pattern)->bool`` tests
    a step's cheap trigger-predicate check; ``fire_cb()`` runs the rule's
    on_complete actions. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        steps = seq.get("steps") or []
        if not steps:
            return
        mode = (seq.get("correlate_by") or "camera").lower()
        if mode not in _SLICE1_MODES:
            return  # person/journey not yet wired (slice 4)
        key = correlation_key(data, mode, seq.get("cameras"))
        if key is None:
            return  # out of scope or no resolvable subject on this frame

        # 1. Advance in-flight instances bound to this key.
        for inst in await _find_active_for_key(rule.id, key):
            if inst.step_deadline and inst.step_deadline < now:
                continue  # overdue; the sweeper will expire it
            if inst.step_index >= len(steps):
                continue
            step = steps[inst.step_index]
            if is_locate_check(step):
                continue  # slice 3
            if not step_match_fn(step_check(step)):
                continue
            nxt = inst.step_index + 1
            if nxt >= len(steps):
                await _set_status(inst.id, "completed")
                await fire_cb()
            else:
                await _advance(inst.id, nxt, now + timedelta(seconds=step_within_seconds(steps[nxt])))

        # 2. Start a new instance when the base trigger (step 0) matched.
        if start_matched:
            on_refire = (seq.get("on_refire") or "ignore").lower()
            existing = await _find_active_for_key(rule.id, key)
            first_deadline = now + timedelta(seconds=step_within_seconds(steps[0]))
            if existing:
                if on_refire == "restart":
                    await _restart(existing[0].id, first_deadline)
                # ignore: leave the in-flight instance untouched
                return
            try:
                max_active = int(seq.get("max_active", _DEFAULT_MAX_ACTIVE) or _DEFAULT_MAX_ACTIVE)
            except (TypeError, ValueError):
                max_active = _DEFAULT_MAX_ACTIVE
            if await _count_active(rule.id) >= max_active:
                logger.info(
                    "sequence rule '%s' at max_active=%d; dropping new start", rule.name, max_active,
                )
                return
            await _create(rule.id, key, 0, first_deadline)
    except Exception:
        logger.exception("evaluate_sequence failed for rule '%s'", getattr(rule, "name", "?"))
