"""Record a real, delivered event against verified-activation milestones.

Called best-effort from the event engine after an alert is delivered. It
advances the ``tested`` milestone for any activation that is tracking the
rule that fired, stamping the real event id, whether the alert was
delivered, and whether the camera was the demo camera (synthetic) or a
real one. It never creates a milestone and never touches ``configured`` or
``confirmed`` — a person still has to open the clip and confirm.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import ActivationMilestone, Camera

logger = logging.getLogger("nurby.activation")


def _is_synthetic_camera(camera: Camera | None) -> bool:
    # The demo camera plays a file rather than a live stream. A test against
    # it is real progress but is labelled synthetic so nothing claims a
    # proven live result. A missing camera is treated as synthetic: we
    # cannot prove it was a real device.
    if camera is None:
        return True
    return getattr(camera, "stream_type", None) == "file"


async def record_event_for_activation(
    db: AsyncSession,
    *,
    rule_id: uuid.UUID | str | None,
    camera_id: uuid.UUID | str | None,
    event_id: uuid.UUID | str | None,
    delivered: bool,
) -> None:
    """Advance the ``tested`` step for milestones tracking this rule.

    A real, delivered test wins: once a real delivered event is recorded it
    is never overwritten by a later synthetic or undelivered one.
    """
    if rule_id is None:
        return
    try:
        result = await db.execute(
            select(ActivationMilestone).where(ActivationMilestone.rule_id == _as_uuid(rule_id)).with_for_update()
        )
        milestones = result.scalars().all()
        if not milestones:
            return

        camera = None
        if camera_id is not None:
            camera = await db.get(Camera, _as_uuid(camera_id))
        synthetic = _is_synthetic_camera(camera)
        test_kind = "synthetic" if synthetic else "real"
        now = datetime.now(timezone.utc)

        changed = False
        for m in milestones:
            if m.configured_at is None or m.camera_id != _as_uuid(camera_id) or _as_uuid(event_id) is None:
                continue
            # Do not regress a real, delivered test to a weaker one.
            # Keep the exact evidence stable while someone reviews it. A new
            # test is explicitly requested by clearing the old milestone.
            already_real = m.test_kind == "real" and m.delivery_ok is True
            if already_real:
                continue
            if m.event_id != _as_uuid(event_id):
                m.confirmed_useful_at = None
            m.tested_at = now
            m.test_kind = test_kind
            m.delivery_ok = bool(delivered)
            m.event_id = _as_uuid(event_id)
            changed = True
        if changed:
            await db.commit()
    except Exception:
        # Activation tracking must never break alert delivery.
        logger.exception("Failed to record activation event for rule %s", rule_id)


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None
