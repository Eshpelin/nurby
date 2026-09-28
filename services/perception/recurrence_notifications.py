"""Notifications for recurring unknown-subject patterns (#216).

The review queue is the detailed surface. This module only creates the
attention signal when an unknown face/body cluster crosses the default
three-distinct-day threshold; it deliberately does not infer an identity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Type
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.app_settings import get_setting
from shared.models import BodyClusterSample, Camera, FaceClusterSample, Notification

RECURRENCE_THRESHOLD_DAYS = 3


def reconcile_recurrence_notifications(notifications, survivor_marker: str):
    """Re-key a merged cluster's alerts without creating a second active item.

    A merge can bring together two clusters that each crossed the recurrence
    threshold before the system learned they were the same subject. Keep the
    oldest alert as the canonical active alert. Older duplicate rows remain
    in history, but are detached from recurrence evidence and marked read so
    the merge cannot produce duplicate work in the review queue.
    """
    ordered = sorted(
        notifications,
        key=lambda item: (item.created_at is None, item.created_at, str(item.id)),
    )
    if not ordered:
        return None
    canonical = ordered[0]
    canonical.dedupe_key = survivor_marker
    for duplicate in ordered[1:]:
        duplicate.dedupe_key = None
        duplicate.read = True
    return canonical


def recurrence_notification_marker(cluster_kind: str, cluster_id: UUID) -> str:
    return f"recurring_unknown:{cluster_kind}:{cluster_id}"


def should_notify_recurrence(
    distinct_days: int,
    already_notified: bool,
    threshold_days: int = RECURRENCE_THRESHOLD_DAYS,
) -> bool:
    """Return true only on the first threshold crossing."""
    return distinct_days >= max(1, threshold_days) and not already_notified


async def maybe_emit_recurrence_notification(
    db: AsyncSession,
    *,
    cluster_kind: str,
    cluster_id: UUID,
    sample_model: Type[FaceClusterSample] | Type[BodyClusterSample],
    camera_id: UUID | None,
    now: datetime | None = None,
) -> bool:
    """Persist one household notification after three separate visit days.

    The caller is already inside the cluster write transaction. The pending
    sample is flushed first, so the query includes it without committing a
    partially-created cluster. Returning whether a row was added keeps this
    helper easy to test and lets callers remain best-effort.
    """
    now = now or datetime.now(timezone.utc)
    try:
        threshold_days = max(1, min(30, int(await get_setting(
            "unknown_recurrence_threshold_days", RECURRENCE_THRESHOLD_DAYS
        ))))
    except (TypeError, ValueError):
        threshold_days = RECURRENCE_THRESHOLD_DAYS
    if camera_id is not None:
        camera = await db.get(Camera, camera_id)
        if camera is not None and not camera.relationship_notifications_enabled:
            return False
    await db.flush()
    rows = (
        await db.execute(
            select(sample_model.captured_at)
            .where(sample_model.cluster_id == cluster_id)
        )
    ).scalars().all()
    days = {
        (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value)
        .astimezone(timezone.utc)
        .date()
        for value in rows
        if value is not None
    }
    if now.date() not in days:
        days.add(now.date())

    marker = recurrence_notification_marker(cluster_kind, cluster_id)
    already_notified = (
        await db.execute(
            select(Notification.id)
            .where(Notification.dedupe_key == marker)
            .limit(1)
        )
    ).scalar_one_or_none() is not None
    if not should_notify_recurrence(len(days), already_notified, threshold_days):
        return False

    subject = "person" if cluster_kind == "face" else "appearance"
    db.add(
        Notification(
            message=(
                f"The same unknown {subject} has appeared on "
                f"{len(days)} separate days. Review the linked recurrence "
                "evidence before assigning an identity."
            ),
            dedupe_key=marker,
            severity="warning",
            camera_id=camera_id,
            created_at=now,
        )
    )
    return True
