"""Storage profile management (issue #251, native FTP #269, S3 #270).

A profile is a named media-storage location cameras can record into, or
the archive destination old recordings move to. Three kinds are
implemented:

- ``local``: an absolute directory on a filesystem the backend can see
  (a second drive, or a mount of an FTP/SMB/S3 remote).
- ``ftp``: a native FTP/FTPS server. Segments buffer locally and upload
  through the ingestion worker (buffer-then-upload — see
  docs/storage-architecture.md); ``root`` is the remote base directory
  and ``config`` carries host/port/credentials (password Fernet-sealed,
  never echoed back).
- ``s3``: an S3-compatible bucket (AWS, R2, B2, Wasabi, MinIO). Same
  buffer-then-upload pipeline; ``root`` is the key prefix and ``config``
  carries bucket/region/endpoint/keys/storage class (secret sealed).

Any change invalidates the per-process root cache; the camera PATCH route
restarts affected workers so segments move immediately.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.routes.system import validate_storage_dir
from shared.auth import require_admin
from shared.database import get_db
from shared.models import StorageProfile, User
from shared.remote_storage import (
    REMOTE_KINDS,
    parse_remote_config,
    remote_probe,
    seal_remote_config,
)
from shared.schemas import (
    StorageProfileCreate,
    StorageProfileResponse,
    StorageProfileStats,
    StorageProfileUpdate,
)
from shared.storage_paths import invalidate as invalidate_storage_cache

router = APIRouter()
logger = logging.getLogger("nurby.api.storage-profiles")

SUPPORTED_KINDS = ("local", *REMOTE_KINDS)


def _normalize_remote_root(kind: str, root: str | None) -> str:
    """FTP roots are remote directories and must be absolute. An S3 root
    is a key prefix; stored with a leading slash for one path shape."""
    root = (root or "").strip()
    if kind == "s3":
        return "/" + root.strip("/")
    root = root or "/"
    if not root.startswith("/"):
        raise HTTPException(
            status_code=400,
            detail="The FTP root is a remote directory and must start with / (e.g. /nurby).",
        )
    return root


def _serialize(profile: StorageProfile, stats: StorageProfileStats | None = None) -> StorageProfileResponse:
    config = None
    has_password = False
    if profile.kind in REMOTE_KINDS:
        cfg = parse_remote_config(profile.kind, profile.config_enc)
        if cfg is not None:
            config = cfg.public_dict()
            has_password = bool(
                getattr(cfg, "password", "") or getattr(cfg, "secret_access_key", "")
            )
    return StorageProfileResponse(
        id=profile.id,
        name=profile.name,
        kind=profile.kind,
        root=profile.root,
        enabled=profile.enabled,
        created_at=profile.created_at,
        config=config,
        has_password=has_password,
        stats=stats or StorageProfileStats(),
    )


async def _profile_stats(db: AsyncSession, profiles: list[StorageProfile]) -> dict[uuid.UUID, StorageProfileStats]:
    """One grouped query over Recording.remote_* columns (issue #276).
    Recordings count toward the profile snapshot that uploaded them, even
    if the camera has since moved to a different profile."""
    from sqlalchemy import func

    from shared.models import Recording

    out = {p.id: StorageProfileStats() for p in profiles}
    if not profiles:
        return out
    rows = await db.execute(
        select(
            Recording.remote_profile_id,
            Recording.remote_state,
            func.count().label("n"),
            func.coalesce(func.sum(Recording.file_size_bytes), 0).label("bytes"),
            func.max(Recording.ended_at).label("last"),
        )
        .where(Recording.remote_profile_id.in_([p.id for p in profiles]))
        .where(Recording.remote_state.is_not(None))
        .group_by(Recording.remote_profile_id, Recording.remote_state)
    )
    for pid, state, n, total, last in rows.all():
        stats = out.get(pid)
        if stats is None:
            stats = out[pid] = StorageProfileStats()
        if state not in ("pending", "failed", "uploaded"):
            continue  # unknown future state — don't explode the schema
        setattr(stats, state, n)
        if state == "uploaded":
            stats.uploaded_bytes = int(total)
            stats.last_upload_at = last
    return out


async def _load_profile(profile_id: uuid.UUID, db: AsyncSession) -> StorageProfile:
    profile = await db.get(StorageProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Storage profile not found")
    return profile


class RemoteProbeRequest(BaseModel):
    config: dict
    root: str = "/"
    kind: str = "ftp"


async def _probe_request(body: RemoteProbeRequest) -> dict:
    if body.kind not in REMOTE_KINDS:
        return {"ok": False, "detail": f"{body.kind!r} is not a remote storage kind"}
    try:
        sealed = seal_remote_config(body.kind, body.config)
        root = _normalize_remote_root(body.kind, body.root)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    except HTTPException as exc:
        return {"ok": False, "detail": exc.detail}
    cfg = parse_remote_config(body.kind, sealed)
    ok, detail = await remote_probe(body.kind, cfg, root)
    return {"ok": ok, "detail": detail}


@router.post("/storage-profiles/validate-remote")
async def validate_remote(
    body: RemoteProbeRequest, _current_user: User = Depends(require_admin)
):
    """Connection probe for the FTP / S3 profile form. FTP connects, logs in
    and creates the remote root; S3 writes and deletes a tiny marker object.
    Never stores anything."""
    return await _probe_request(body)


@router.post("/storage-profiles/validate-ftp")
async def validate_ftp(
    body: RemoteProbeRequest, _current_user: User = Depends(require_admin)
):
    """Pre-S3 path for the FTP probe, kept for existing clients."""
    return await _probe_request(RemoteProbeRequest(config=body.config, root=body.root, kind="ftp"))


@router.get("/storage-profiles", response_model=list[StorageProfileResponse])
async def list_profiles(
    _current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    rows = await db.execute(select(StorageProfile).order_by(StorageProfile.name))
    profiles = list(rows.scalars().all())
    stats = await _profile_stats(db, profiles)
    return [_serialize(p, stats.get(p.id)) for p in profiles]


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
                f"Storage kind {body.kind!r} is not implemented yet. Use 'local', 'ftp' or 's3'."
            ),
        )

    config_enc = None
    if body.kind == "local":
        probe = validate_storage_dir(body.root)
        if not probe.ok:
            raise HTTPException(status_code=400, detail=probe.detail)
        root = probe.path
    else:
        root = _normalize_remote_root(body.kind, body.root)
        try:
            config_enc = seal_remote_config(body.kind, body.config or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        cfg = parse_remote_config(body.kind, config_enc)
        ok, detail = await remote_probe(body.kind, cfg, root)
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
    return _serialize(profile, StorageProfileStats())


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
            profile.root = _normalize_remote_root(profile.kind, new_root)
    if "config" in updates and updates["config"] is not None:
        if profile.kind not in REMOTE_KINDS:
            raise HTTPException(status_code=400, detail="Only FTP and S3 profiles take a config")
        new_cfg = dict(updates["config"])
        # A blank S3 secret on edit means "keep the stored one". (A blank FTP
        # password stays meaningful: anonymous login.)
        old = parse_remote_config(profile.kind, profile.config_enc)
        secret_field = "secret_access_key"
        if profile.kind == "s3" and old is not None and not new_cfg.get(secret_field):
            new_cfg[secret_field] = getattr(old, secret_field)
        try:
            profile.config_enc = seal_remote_config(profile.kind, new_cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if "name" in updates and updates["name"] is not None:
        profile.name = str(updates["name"])
    if "enabled" in updates and updates["enabled"] is not None:
        profile.enabled = bool(updates["enabled"])

    # Re-probe after any connection-affecting change so a saved profile is
    # a known-good profile ("failed validation leaves config unchanged" —
    # the probe runs before commit via the exception below).
    if profile.kind in REMOTE_KINDS:
        cfg = parse_remote_config(profile.kind, profile.config_enc)
        if cfg is None:
            raise HTTPException(status_code=400, detail="Profile has no valid connection config")
        ok, detail = await remote_probe(profile.kind, cfg, profile.root)
        if not ok:
            await db.rollback()
            raise HTTPException(status_code=400, detail=detail)

    await db.commit()
    await db.refresh(profile)
    invalidate_storage_cache()
    stats_map = await _profile_stats(db, [profile])
    return _serialize(profile, stats_map.get(profile.id))


@router.delete("/storage-profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    profile = await _load_profile(profile_id, db)
    from shared.app_settings import get_setting
    from shared.archive import SETTING_PROFILE

    if str(await get_setting(SETTING_PROFILE, None) or "") == str(profile.id):
        raise HTTPException(
            status_code=409,
            detail="This location is where old recordings are archived. Turn off archiving "
            "or pick another destination first.",
        )
    await db.delete(profile)  # cameras.storage_profile_id is ON DELETE SET NULL
    await db.commit()
    invalidate_storage_cache()
    return None


# ── Archive tier (issue #270) ───────────────────────────────────────────


class ArchiveSettingsUpdate(BaseModel):
    # None turns archiving off. Must name an enabled FTP or S3 profile.
    profile_id: uuid.UUID | None = None
    # How long the archive keeps a recording. 0 = forever.
    retention_days: int = Field(default=0, ge=0, le=3650)


async def _archive_payload(db: AsyncSession) -> dict:
    from sqlalchemy import func

    from shared.app_settings import get_setting
    from shared.archive import SETTING_PROFILE, SETTING_RETENTION
    from shared.models import Camera

    raw_id = await get_setting(SETTING_PROFILE, None)
    days = int(await get_setting(SETTING_RETENTION, 0) or 0)
    profile = None
    if raw_id:
        try:
            profile = await db.get(StorageProfile, uuid.UUID(str(raw_id)))
        except ValueError:
            profile = None
    cams = (await db.execute(
        select(Camera.id, Camera.name, Camera.retention_mode, Camera.retention_days, Camera.retention_gb)
    )).all()
    # Archiving moves what local retention would delete, so a camera that
    # keeps everything forever never archives anything. Say so.
    cameras = [
        {
            "id": str(cid),
            "name": name,
            "retention_mode": mode or "none",
            "retention_days": rdays,
            "retention_gb": rgb,
        }
        for cid, name, mode, rdays, rgb in cams
    ]
    stats = StorageProfileStats()
    if profile is not None:
        stats = (await _profile_stats(db, [profile])).get(profile.id, stats)
    active = profile is not None and profile.enabled and profile.kind in REMOTE_KINDS
    storage_class = None
    if profile is not None and profile.kind == "s3":
        cfg = parse_remote_config("s3", profile.config_enc)
        storage_class = cfg.storage_class if cfg else None
    remote_profiles = (await db.execute(
        select(func.count()).select_from(StorageProfile).where(StorageProfile.kind.in_(REMOTE_KINDS))
    )).scalar() or 0
    return {
        "profile_id": str(profile.id) if profile else None,
        "profile_name": profile.name if profile else None,
        "kind": profile.kind if profile else None,
        "storage_class": storage_class,
        "retention_days": days,
        "active": active,
        # The setting names a profile that was deleted or disabled.
        "broken": bool(raw_id) and not active,
        "remote_profiles": int(remote_profiles),
        "stats": stats.model_dump(),
        "cameras": cameras,
    }


@router.get("/storage/archive")
async def get_archive_settings(
    _current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Where old recordings go when they leave this machine, how long the
    archive keeps them, and what is in flight."""
    return await _archive_payload(db)


@router.put("/storage/archive")
async def put_archive_settings(
    body: ArchiveSettingsUpdate,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from shared.app_settings import set_setting
    from shared.archive import SETTING_PROFILE, SETTING_RETENTION

    if body.profile_id is not None:
        profile = await _load_profile(body.profile_id, db)
        if profile.kind not in REMOTE_KINDS:
            raise HTTPException(
                status_code=400,
                detail="The archive must be an S3 bucket or FTP server, not a local folder.",
            )
        if not profile.enabled:
            raise HTTPException(status_code=400, detail="That location is disabled.")
    await set_setting(SETTING_PROFILE, str(body.profile_id) if body.profile_id else None)
    await set_setting(SETTING_RETENTION, int(body.retention_days))
    return await _archive_payload(db)
