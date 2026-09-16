import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin
from shared.database import get_db
from shared.models import Camera, User, UserCameraAccess
from shared.schemas import (
    CameraResponse,
    SetCameraAccessRequest,
    UserCameraAccessResponse,
    UserResponse,
    UserUpdate,
)

router = APIRouter()


@router.get("", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users. Admin only."""
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single user by ID. Admin only."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role, active status or explicit camera policy. Admin only."""
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updates = body.model_dump(exclude_unset=True)
    if updates.get("camera_access_mode") in {"all", "none"}:
        existing = await db.execute(select(UserCameraAccess).where(UserCameraAccess.user_id == user_id))
        for row in existing.scalars().all():
            await db.delete(row)
    for field, value in updates.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a user by setting is_active to False. Admin only."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await db.commit()


@router.get("/{user_id}/cameras", response_model=list[CameraResponse])
async def list_user_cameras(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List explicitly selected cameras (not effective all-mode access). Admin only."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(Camera)
        .join(UserCameraAccess, UserCameraAccess.camera_id == Camera.id)
        .where(UserCameraAccess.user_id == user_id)
        .order_by(Camera.created_at)
    )
    return result.scalars().all()


@router.put("/{user_id}/cameras", response_model=list[UserCameraAccessResponse])
async def set_user_cameras(
    user_id: uuid.UUID,
    body: SetCameraAccessRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Replace a user's entire camera access list. Admin only."""
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate before replacing anything. Deduplicate repeated IDs.
    camera_ids = list(dict.fromkeys(body.camera_ids))
    for camera_id in camera_ids:
        if await db.get(Camera, camera_id) is None:
            raise HTTPException(status_code=404, detail="Camera not found")

    # Remove all existing access
    existing = await db.execute(
        select(UserCameraAccess).where(UserCameraAccess.user_id == user_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)
    await db.flush()
    user.camera_access_mode = "selected" if camera_ids else "none"

    # Grant new access
    new_rows = []
    for camera_id in camera_ids:
        access = UserCameraAccess(
            user_id=user_id,
            camera_id=camera_id,
            granted_by_id=admin.id,
        )
        db.add(access)
        new_rows.append(access)

    await db.commit()

    # Refresh to get server-generated fields
    for row in new_rows:
        await db.refresh(row)

    return new_rows


@router.post("/{user_id}/cameras/{camera_id}", response_model=UserCameraAccessResponse, status_code=201)
async def grant_camera_access(
    user_id: uuid.UUID,
    camera_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grant a user access to a single camera. Admin only."""
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.camera_access_mode == "all":
        raise HTTPException(status_code=409, detail="Choose Selected cameras before editing individual cameras")

    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Check if access already exists
    existing = await db.execute(
        select(UserCameraAccess).where(
            UserCameraAccess.user_id == user_id,
            UserCameraAccess.camera_id == camera_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User already has access to this camera")

    access = UserCameraAccess(
        user_id=user_id,
        camera_id=camera_id,
        granted_by_id=admin.id,
    )
    db.add(access)
    user.camera_access_mode = "selected"
    await db.commit()
    await db.refresh(access)
    return access


@router.delete("/{user_id}/cameras/{camera_id}", status_code=204)
async def revoke_camera_access(
    user_id: uuid.UUID,
    camera_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a user's access to a single camera. Admin only."""
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.camera_access_mode == "all":
        raise HTTPException(status_code=409, detail="Choose Selected cameras before revoking an individual camera")
    result = await db.execute(
        select(UserCameraAccess).where(
            UserCameraAccess.user_id == user_id,
            UserCameraAccess.camera_id == camera_id,
        )
    )
    access = result.scalar_one_or_none()
    if access is None:
        raise HTTPException(status_code=404, detail="Camera access not found")

    await db.delete(access)
    await db.commit()
