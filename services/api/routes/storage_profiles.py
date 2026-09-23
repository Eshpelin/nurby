"""Storage profile management (issue #251, native FTP per issue #269).

A profile is a named media-storage location cameras can record into.
Two kinds are implemented:

- ``local``: an absolute directory on a filesystem the backend can see
  (a second drive, or a mount of an FTP/SMB/S3 remote).
- ``ftp``: a native FTP/FTPS server. Segments buffer locally and upload
  through the ingestion worker (buffer-then-upload — see
  docs/storage-architecture.md); ``root`` is the remote base directory
  and ``config`` carries host/port/credentials (password Fernet-sealed,
  never echoed back).

Any change invalidates the per-process root cache; the camera PATCH route
restarts affected workers so segments move immediately.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin
from shared.database import get_db
from shared.models import StorageProfile, User
from shared.remote_storage import parse_ftp_config, probe_ftp, seal_ftp_config
from shared.schemas import (
    StorageProfileCreate,
    StorageProfileResponse,
    StorageProfileUpdate,
)
from shared.storage_paths import invalidate as invalidate_storage_cache
from services.api.routes.system import validate_storage_dir

router = APIRouter()
logger = logging.getLogger("nurby.api.storage-profiles")

SUPPORTED_KINDS = ("local", "ftp")


def _serialize(profile: StorageProfile) -> StorageProfileResponse:
    config = None
    has_password = False
    if profile.kind == "ftp":
        cfg = parse_ftp_config(profile.config_enc)
        if cfg is not None:
            config = cfg.public_dict()
            has_password = bool(cfg.password)
    return StorageProfileResponse(
        id=profile.id,
        name=profile.name,
        kind=profile.kind,
        root=profile.root,
        enabled=profile.enabled,
        created_at=profile.created_at,
        config=config,
        has_password=has_password,
    )


async def _load_profile(profile_id: uuid.UUID, db: AsyncSession) -> StorageProfile:
    profile = await db.get(StorageProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Storage profile not found")
    return profile


class FtpProbeRequest(BaseModel):
    config: dict
    root: str = "/"


@router.post("/storage-profiles/validate-ftp")
async def validate_ftp(
    body: FtpProbeRequest, _current_user: User = Depends(require_admin)
):
    """Connection probe for the FTP profile form (issue #269). Connects,
    logs in, and creates/enters the remote root. Never stores anything."""
    try:
        sealed = seal_ftp_config(body.config)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    cfg = parse_ftp_config(sealed)
    ok, detail = await probe_ftp(cfg, body.root or "/")
    return {"ok": ok, "detail": detail}


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
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Storage kind {body.kind!r} is not implemented yet. Use 'local' or 'ftp'."
            ),
        )

    config_enc = None
    if body.kind == "local":
        probe = validate_storage_dir(body.root)
        if not probe.ok:
            raise HTTPException(status_code=400, detail=probe.detail)
        root = probe.path
    else:
        root = body.root.strip() or "/"
        if not root.startswith("/"):
            raise HTTPException(
                status_code=400,
                detail="The FTP root is a remote directory and must start with / (e.g. /nurby).",
            )
        try:
            config_enc = seal_ftp_config(body.config or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        cfg = parse_ftp_config(config_enc)
        ok, detail = await probe_ftp(cfg, root)
        if not ok:
            raise HTTPException(status_code=400, detail=detail)

    existing = await db.execute(
        select(StorageProfile).where(StorageProfile.name == body.name)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=409, detail="A profile with that name exists")
    profile = StorageProfile(name=body.name, kind=body.kind, root=root, config_enc=config_enc)
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
        new_root = str(updates["root"]).strip()
        if profile.kind == "local":
            probe = validate_storage_dir(new_root)
            if not probe.ok:
                raise HTTPException(status_code=400, detail=probe.detail)
            profile.root = probe.path
        else:
            if not new_root.startswith("/"):
                raise HTTPException(
                    status_code=400, detail="The FTP root must start with /."
                )
            profile.root = new_root
    if "config" in updates and updates["config"] is not None:
        if profile.kind != "ftp":
            raise HTTPException(status_code=400, detail="Only FTP profiles take a config")
        try:
            profile.config_enc = seal_ftp_config(updates["config"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if "name" in updates and updates["name"] is not None:
        profile.name = str(updates["name"])
    if "enabled" in updates and updates["enabled"] is not None:
        profile.enabled = bool(updates["enabled"])

    # Re-probe after any connection-affecting change so a saved profile is
    # a known-good profile ("failed validation leaves config unchanged" —
    # the probe runs before commit via the exception below).
    if profile.kind == "ftp":
        cfg = parse_ftp_config(profile.config_enc)
        if cfg is None:
            raise HTTPException(status_code=400, detail="FTP profile has no valid connection config")
        ok, detail = await probe_ftp(cfg, profile.root)
        if not ok:
            await db.rollback()
            raise HTTPException(status_code=400, detail=detail)

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
