"""Persistence adapter for the package lifecycle reducer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.package_lifecycle import (
    PackageEvidence,
    PackageLifecycle,
    PackageState,
    RemovalKind,
    advance,
)
from shared.models import Notification, PackageLifecycleRecord, Person


DEFAULT_TRACKING_KEY = "camera-default"
PACKAGE_LABELS = frozenset({"package", "parcel", "box", "cardboard box"})


def _package_present(object_detections: dict | None) -> bool:
    objects = (object_detections or {}).get("objects") or []
    return any(str(item.get("label", "")).strip().lower() in PACKAGE_LABELS for item in objects)


def _known_person_id(person_detections: dict | None) -> UUID | None:
    for face in ((person_detections or {}).get("faces") or []):
        value = face.get("person_id") or face.get("personId")
        if value:
            try:
                return UUID(str(value))
            except (TypeError, ValueError):
                continue
    return None


def _to_reducer(row: PackageLifecycleRecord) -> PackageLifecycle:
    return PackageLifecycle(
        state=PackageState(row.state),
        last_present_at=row.last_present_at,
        absent_checks=row.absent_checks,
        gone_at=row.gone_at,
        removal_kind=RemovalKind(row.removal_kind) if row.removal_kind else None,
        remover_person_id=row.remover_person_id,
        last_observation_id=row.last_observation_id,
    )


async def apply_package_check(
    db: AsyncSession,
    *,
    camera_id: UUID,
    evidence: PackageEvidence,
    tracking_key: str = DEFAULT_TRACKING_KEY,
    required_absent_checks: int = 2,
    minimum_absence: timedelta = timedelta(minutes=2),
) -> PackageLifecycleRecord:
    """Upsert one camera-local candidate and return its durable state."""
    row = (
        await db.execute(
            select(PackageLifecycleRecord)
            .where(
                PackageLifecycleRecord.camera_id == camera_id,
                PackageLifecycleRecord.tracking_key == tracking_key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    is_new = row is None
    previous_state = row.state if row is not None else None
    if row is None:
        row = PackageLifecycleRecord(
            camera_id=camera_id,
            tracking_key=tracking_key,
            state=PackageState.DELIVERED.value,
            started_at=evidence.observed_at,
        )
        db.add(row)
        await db.flush()

    next_state = advance(
        _to_reducer(row), evidence,
        required_absent_checks=required_absent_checks,
        minimum_absence=minimum_absence,
    )
    if evidence.present and row.last_present_at is None:
        row.started_at = evidence.observed_at
    row.state = next_state.state.value
    row.last_present_at = next_state.last_present_at
    row.absent_checks = next_state.absent_checks
    row.gone_at = next_state.gone_at
    row.removal_kind = next_state.removal_kind.value if next_state.removal_kind else None
    row.remover_person_id = next_state.remover_person_id
    row.last_observation_id = next_state.last_observation_id
    row.evidence = {
        "present": evidence.present,
        "confidence": evidence.confidence,
        "observation_id": str(evidence.observation_id) if evidence.observation_id else None,
        "remover_person_id": str(evidence.remover_person_id) if evidence.remover_person_id else None,
    }
    row.updated_at = datetime.now(timezone.utc)
    await _emit_transition_notification(
        db,
        row=row,
        previous_state=previous_state,
        is_new=is_new,
        evidence=evidence,
    )
    return row


async def _emit_transition_notification(
    db: AsyncSession,
    *,
    row: PackageLifecycleRecord,
    previous_state: str | None,
    is_new: bool,
    evidence: PackageEvidence,
) -> None:
    """Write one household notification per delivery/removal transition."""
    if is_new and evidence.present:
        dedupe_key = f"package_lifecycle:{row.id}:delivered"
        message = "A package was detected at the camera."
        severity = "info"
    elif previous_state != PackageState.GONE.value and row.state == PackageState.GONE.value:
        dedupe_key = f"package_lifecycle:{row.id}:gone"
        if row.removal_kind == "picked_up_by_person":
            message = "A package appears to have been picked up by a recognized person."
            severity = "info"
        else:
            message = "A package is no longer visible and no recognized pickup was observed."
            severity = "warning"
    else:
        return
    exists = (
        await db.execute(
            select(Notification.id).where(Notification.dedupe_key == dedupe_key).limit(1)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(Notification(
            message=message,
            dedupe_key=dedupe_key,
            severity=severity,
            camera_id=row.camera_id,
            observation_id=evidence.observation_id,
            created_at=evidence.observed_at,
        ))


async def apply_package_observation(
    db: AsyncSession,
    *,
    camera_id: UUID,
    observation_id: UUID,
    observed_at: datetime,
    object_detections: dict | None,
    person_detections: dict | None,
    pickup_policy: str = "recognized_person",
) -> PackageLifecycleRecord | None:
    """Feed an observation into the active camera-local delivery candidate.

    A non-package frame is ignored until a candidate exists, so ordinary
    cameras do not accumulate empty delivery rows. Once a candidate exists,
    subsequent keyframes provide absence checks. A new package after a gone
    lifecycle starts a new key, preserving the previous delivery history.
    """
    present = _package_present(object_detections)
    rows = (
        await db.execute(
            select(PackageLifecycleRecord)
            .where(PackageLifecycleRecord.camera_id == camera_id)
            .order_by(PackageLifecycleRecord.updated_at.desc())
        )
    ).scalars().all()
    current = next((row for row in rows if row.state != PackageState.GONE.value), None)
    if current is None and not present:
        return None
    tracking_key = DEFAULT_TRACKING_KEY
    if rows and rows[0].state == PackageState.GONE.value and present:
        tracking_key = f"delivery-{observation_id}"
    remover_person_id = None if present else _known_person_id(person_detections)
    if not present and pickup_policy == "resident_only" and remover_person_id is not None:
        resident = await db.scalar(
            select(Person.id)
            .where(Person.id == remover_person_id)
            .where(Person.is_household_member.is_(True))
        )
        if resident is None:
            remover_person_id = None
    return await apply_package_check(
        db,
        camera_id=camera_id,
        tracking_key=tracking_key,
        evidence=PackageEvidence(
            observed_at=observed_at,
            present=present,
            observation_id=observation_id,
            remover_person_id=remover_person_id,
        ),
    )
