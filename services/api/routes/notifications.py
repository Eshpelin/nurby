import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import allowed_camera_ids, apply_camera_filter, require_camera_in_scope
from shared.database import get_db
from shared.models import Camera, Notification, User
from shared.schemas import NotificationResponse

router = APIRouter()


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(_current_user, db)
    query = apply_camera_filter(
        select(Notification, Camera.name.label("camera_name"))
        .outerjoin(Camera, Camera.id == Notification.camera_id),
        allowed,
        Notification.camera_id,
    ).order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    if unread_only:
        query = query.where(Notification.read == False)  # noqa: E712
    result = await db.execute(query)
    return [
        {**notification.__dict__, "camera_name": camera_name}
        for notification, camera_name in result.all()
    ]


@router.get("/count")
async def unread_count(_current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    allowed = await allowed_camera_ids(_current_user, db)
    query = select(func.count()).select_from(Notification).where(Notification.read.is_(False))
    result = await db.execute(apply_camera_filter(query, allowed, Notification.camera_id))
    return {"unread": result.scalar_one()}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notif = await db.get(Notification, notification_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    await require_camera_in_scope(_current_user, db, notif.camera_id, detail="Notification not found")
    notif.read = True
    await db.commit()
    await db.refresh(notif)
    return notif


@router.post("/read-all")
async def mark_all_read(_current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    allowed = await allowed_camera_ids(_current_user, db)
    query = update(Notification).where(Notification.read.is_(False)).values(read=True)
    await db.execute(apply_camera_filter(query, allowed, Notification.camera_id))
    await db.commit()
    return {"status": "ok"}
