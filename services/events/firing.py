"""Shared event-firing path.

Store the fired event, broadcast it to dashboards, run an action chain, and fan
out to webhook subscriptions. One implementation shared by three callers:

- the normal trigger path (RuleEngine._fire, runs rule.actions),
- sequence completion (on_complete, also rule.actions),
- sequence timeout (on_timeout, a separate chain on the sequence block).

Kept free of any RuleEngine import so the engine and the sequence sweeper can
both depend on it without a cycle.
"""

import logging
import uuid

from shared.database import async_session
from shared.models import Event

logger = logging.getLogger("nurby.events.firing")


def wrap_actions(actions) -> list[dict]:
    """Ensure an action chain is always a list."""
    if isinstance(actions, list):
        return actions
    if isinstance(actions, dict):
        return [actions]
    return []


async def store_event(
    rule_id: uuid.UUID,
    observation_id,
    payload: dict,
    severity: str = "alert",
) -> uuid.UUID:
    """Persist a fired event and return its id."""
    try:
        obs_uuid = uuid.UUID(str(observation_id)) if observation_id else None
    except (ValueError, TypeError):
        obs_uuid = None

    rec_raw = payload.get("recording_id")
    try:
        rec_uuid = uuid.UUID(str(rec_raw)) if rec_raw else None
    except (ValueError, TypeError):
        rec_uuid = None

    cam_raw = payload.get("camera_id")
    try:
        cam_uuid = uuid.UUID(str(cam_raw)) if cam_raw else None
    except (ValueError, TypeError):
        cam_uuid = None

    event = Event(
        rule_id=rule_id,
        observation_id=obs_uuid,
        recording_id=rec_uuid,
        severity=severity if severity in ("alert", "detection") else "alert",
        camera_id=cam_uuid,
        payload=payload,
    )
    try:
        async with async_session() as db:
            db.add(event)
            await db.commit()
            await db.refresh(event)
            logger.info("Stored event %s for rule %s", event.id, rule_id)
            return event.id
    except Exception:
        logger.exception("Failed to store event")
        return uuid.uuid4()


async def _broadcast_fired(event_id, rule, observation_data: dict, severity: str) -> None:
    try:
        from services.api.ws import broadcast as _ws_broadcast

        await _ws_broadcast({
            "type": "event_fired",
            "event_id": str(event_id),
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "severity": severity,
            "camera_id": observation_data.get("camera_id"),
            "camera_name": observation_data.get("camera_name") or "",
            "observation_id": observation_data.get("observation_id"),
            "event_kind": observation_data.get("event_kind") or "observation",
            "timestamp": observation_data.get("timestamp"),
        })
    except Exception:
        logger.debug("event_fired broadcast failed", exc_info=True)


async def fire_actions(
    rule,
    observation_data: dict,
    actions,
    *,
    severity: str = "alert",
    event_id=None,
) -> uuid.UUID:
    """Store the event (unless `event_id` supplied), broadcast it, run the action
    chain, then fan out to webhook subscriptions. Never raises."""
    from services.events.actions import execute_action

    if event_id is None:
        event_id = await store_event(
            rule.id, observation_data.get("observation_id"), observation_data, severity,
        )
    await _broadcast_fired(event_id, rule, observation_data, severity)

    # Thread a shared `vars` dict so later actions can reference earlier outputs.
    observation_data.setdefault("vars", {})
    for action in wrap_actions(actions):
        try:
            await execute_action(action, observation_data, rule, event_id)
        except RuntimeError as exc:
            # Chain-abort signal (vlm_call on_error=stop, verify failed, ...).
            logger.info("Rule '%s' chain stopped. %s", rule.name, exc)
            break
        except Exception:
            logger.exception("Action failed for rule '%s'", rule.name)

    try:
        from services.events.actions import dispatch_subscriptions

        await dispatch_subscriptions(observation_data, rule, event_id)
    except Exception:
        logger.exception("subscription dispatch failed for rule '%s'", rule.name)
    return event_id
