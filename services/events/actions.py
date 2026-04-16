"""
Action executors for rule engine.

Each action type has its own executor. Actions receive observation
data, the matched rule, and the stored event ID.
"""

import logging
import uuid

import httpx

logger = logging.getLogger("nurby.events.actions")


async def execute_action(
    action: dict,
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
):
    """Dispatch action to correct executor based on type."""
    action_type = action.get("type")

    if action_type == "webhook":
        await _execute_webhook(action, observation_data, rule, event_id)
    elif action_type == "broadcast":
        await _execute_broadcast(action, observation_data, rule, event_id)
    elif action_type == "notify":
        await _execute_notify(action, observation_data, rule, event_id)
    else:
        logger.warning("Unknown action type '%s' in rule '%s'", action_type, rule.name)


async def _execute_webhook(
    action: dict,
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
):
    """POST observation data to webhook URL."""
    url = action.get("url")
    if not url:
        logger.error("Webhook action missing 'url' in rule '%s'", rule.name)
        return

    payload = {
        "event_id": str(event_id),
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "camera_id": observation_data.get("camera_id"),
        "timestamp": observation_data.get("timestamp"),
        "motion_score": observation_data.get("motion_score"),
        "object_detections": observation_data.get("object_detections"),
        "person_detections": observation_data.get("person_detections"),
        "vlm_description": observation_data.get("vlm_description"),
    }

    headers = action.get("headers", {})
    headers.setdefault("Content-Type", "application/json")
    timeout = action.get("timeout", 10)

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            logger.info(
                "Webhook fired for rule '%s' -> %s (status %d)",
                rule.name, url, resp.status_code,
            )
        except httpx.TimeoutException:
            logger.error("Webhook timeout for rule '%s' -> %s", rule.name, url)
        except httpx.RequestError as exc:
            logger.error("Webhook failed for rule '%s' -> %s. %s", rule.name, url, exc)


async def _execute_broadcast(
    action: dict,
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
):
    """Push event to all connected WebSocket clients."""
    from services.api.ws import broadcast

    message = {
        "type": "event",
        "event_id": str(event_id),
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "camera_id": observation_data.get("camera_id"),
        "timestamp": observation_data.get("timestamp"),
        "motion_score": observation_data.get("motion_score"),
        "object_detections": observation_data.get("object_detections"),
        "person_detections": observation_data.get("person_detections"),
        "vlm_description": observation_data.get("vlm_description"),
    }

    # Merge custom fields from action config
    extra = action.get("extra_fields", {})
    message.update(extra)

    await broadcast(message)
    logger.info("Broadcast event for rule '%s' to WebSocket clients", rule.name)


async def _execute_notify(
    action: dict,
    observation_data: dict,
    rule,
    event_id: uuid.UUID,
):
    """Store notification for UI display. Also broadcasts via WebSocket."""
    from services.api.ws import broadcast

    template = action.get("message", "Rule '{rule_name}' triggered")
    message_text = template.replace("{rule_name}", rule.name).replace(
        "{camera_id}", observation_data.get("camera_id", "unknown")
    )

    notification = {
        "type": "notification",
        "event_id": str(event_id),
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "message": message_text,
        "severity": action.get("severity", "info"),
        "camera_id": observation_data.get("camera_id"),
        "timestamp": observation_data.get("timestamp"),
    }

    await broadcast(notification)
    logger.info("Notification for rule '%s'. %s", rule.name, message_text)
