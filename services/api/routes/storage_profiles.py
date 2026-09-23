"""Storage profile management (issue #251).

A profile is a named media-storage location cameras can record into.
v1 supports kind="local" — an absolute directory on a filesystem the
backend can see (a second drive, or a mount of an FTP/SMB/S3 remote;
see docs/storage-architecture.md for the remote-backend story). Any
change invalidates the per-process root cache; the camera PATCH route
restarts affected workers so segments move immediately.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin
from shared.database import get_db
from shared.models import StorageProfile, User
from shared.schemas import (
    StorageProfileCreate,
    StorageProfileResponse,
    StorageProfileUpdate,
)
from shared.storage_paths import invalidate as invalidate_storage_cache
from services.api.routes.system import validate_storage_dir

router = APIRouter()
logger = logging.getLogger("nurby.api.storage-profiles")


def _serialize(profile: StorageProfile) -> StorageProfileResponse:
    return StorageProfileResponse.model_validate(profile)


async def _load_profile(profile_id: uuid.UUID, db: AsyncSession) -> StorageProfile:
    profile = await db.get(StorageProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Storage profile not found")
    return profile


@router.get("/storage-profiles", response_model=list[StorageProfileResponse])
async def list_profiles(
    _current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    rows = await db.execute(select(StorageProfile).order_by(StorageProfile.name))
    return [_serialize(p) for p in rows.scalars().all()]


@router.post("/storage-profiles", response_model=StorageProfileResponse, status_code=201)
async def create_profile(
    body: StorageProfileCreate,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.kind != "local":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Storage kind {body.kind!r} is not implemented yet. Use 'local' and "
                "point it at a mount of the remote (see docs/storage-architecture.md)."
            ),
        )
    probe = validate_storage_dir(body.root)
    if not probe.ok:
        raise HTTPException(status_code=400, detail=probe.detail)
    existing = await db.execute(
        select(StorageProfile).where(StorageProfile.name == body.name)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=409, detail="A profile with that name exists")
    profile = StorageProfile(name=body.name, kind="local", root=probe.path)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    invalidate_storage_cache()
    return _serialize(profile)


@router.patch("/storage-profiles/{profile_id}", response_model=StorageProfileResponse)
async def update_profile(
    profile_id: uuid.UUID,
    body: StorageProfileUpdate,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    profile = await _load_profile(profile_id, db)
    updates = body.model_dump(exclude_unset=True)
    if "root" in updates and updates["root"] != profile.root:
        probe = validate_storage_dir(str(updates["root"]))
        if not probe.ok:
            raise HTTPException(status_code=400, detail=probe.detail)
        profile.root = probe.path
    if "name" in updates and updates["name"] is not None:
        profile.name = str(updates["name"])
    if "enabled" in updates and updates["enabled"] is not None:
        profile.enabled = bool(updates["enabled"])
    await db.commit()
    await db.refresh(profile)
    invalidate_storage_cache()
    return _serialize(profile)


@router.delete("/storage-profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    profile = await _load_profile(profile_id, db)
    await db.delete(profile)  # cameras.storage_profile_id is ON DELETE SET NULL
    await db.commit()
    invalidate_storage_cache()
    return None
