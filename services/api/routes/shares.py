"""Anonymous, scoped, revocable share links (see models.ResourceShare).

Two routers:
  * ``router``        — authed, mounted at ``/api/shares``   (create / list / revoke)
  * ``public_router`` — UNAUTHENTICATED, mounted at ``/api/share`` (resolve / media)

Security posture:
  * Only the SHA-256 hash of the token is stored; the raw token lives only in
    the URL and is returned to the creator exactly once.
  * A share always has an expiry (default 7d, max 30d) — there are no
    never-expiring links. Ongoing/live access is an account + camera ACL, not a
    link, so ``kind`` never includes anything live.
  * Operators can only share a resource on a camera they can already see.
  * A "view" is counted once on the resolve/metadata call, NOT per media
    byte-range request, so one watch of a clip does not burn the whole
    ``max_views`` allowance. Media sub-requests still re-validate the share.
  * Media reuses the normal recording/observation serve paths, so the share
    inherits the system's selective privacy blur automatically.
"""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.routes.recordings import _get_disk_path_or_404
from shared.auth import get_current_user
from shared.camera_access import ALL, AllowedCameras, allowed_camera_ids
from shared.config import settings
from shared.database import get_db
from shared.models import Camera, Event, Observation, Recording, ResourceShare, User
from shared.paths import resolve_inside

router = APIRouter()          # authed → /api/shares
public_router = APIRouter()   # unauthenticated → /api/share

# Phase A ships the three concrete single-resource kinds. camera_events /
# person_events (read-only feeds) are Phase B; the model already carries the
# columns for them.
_KINDS = {"recording", "observation", "event"}
_DEFAULT_EXPIRY_DAYS = 7
_MAX_EXPIRY_DAYS = 30


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_camera_access(allowed: AllowedCameras, camera_id: uuid.UUID | None) -> None:
    """Operators may only share resources on cameras they can already see."""
    if allowed is ALL:
        return
    if camera_id is None or camera_id not in allowed:
        raise HTTPException(
            status_code=403, detail="You can only share resources on cameras you can access"
        )


# ── create / manage (authed) ──────────────────────────────────────────────

class ShareCreate(BaseModel):
    kind: str
    resource_id: uuid.UUID
    expires_in_days: int | None = None  # clamped to [1, 30]; None → default 7
    max_views: int | None = None        # None → unlimited; else >= 1
    label: str | None = None


class ShareResponse(BaseModel):
    id: uuid.UUID
    kind: str
    label: str | None
    max_views: int | None
    view_count: int
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    last_accessed_at: datetime | None
    status: str  # active | expired | revoked | exhausted


def _share_status(s: ResourceShare) -> str:
    if s.revoked_at is not None:
        return "revoked"
    if s.expires_at is not None and _now() > s.expires_at:
        return "expired"
    if s.max_views is not None and s.view_count >= s.max_views:
        return "exhausted"
    return "active"


def _to_response(s: ResourceShare) -> ShareResponse:
    return ShareResponse(
        id=s.id, kind=s.kind, label=s.label, max_views=s.max_views, view_count=s.view_count,
        expires_at=s.expires_at, revoked_at=s.revoked_at, created_at=s.created_at,
        last_accessed_at=s.last_accessed_at, status=_share_status(s),
    )


@router.post("", status_code=201)
async def create_share(
    body: ShareCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a scoped share link for one recorded resource. Returns the raw
    share URL exactly once (only its hash is stored)."""
    if body.kind not in _KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported share kind '{body.kind}'. Supported: {sorted(_KINDS)}.",
        )
    allowed = await allowed_camera_ids(current_user, db)
    share = ResourceShare(kind=body.kind, created_by_id=current_user.id, label=body.label)

    if body.kind == "recording":
        rec = await db.get(Recording, body.resource_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Recording not found")
        _require_camera_access(allowed, rec.camera_id)
        share.recording_id = rec.id
    elif body.kind == "observation":
        obs = await db.get(Observation, body.resource_id)
        if not obs:
            raise HTTPException(status_code=404, detail="Observation not found")
        _require_camera_access(allowed, obs.camera_id)
        share.observation_id = obs.id
    else:  # event
        ev = await db.get(Event, body.resource_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")
        cam_id = ev.camera_id
        if cam_id is None and ev.observation_id is not None:
            obs = await db.get(Observation, ev.observation_id)
            cam_id = obs.camera_id if obs else None
        _require_camera_access(allowed, cam_id)
        share.event_id = ev.id

    # Always expire. None → default; otherwise clamp to [1, MAX].
    days = _DEFAULT_EXPIRY_DAYS if body.expires_in_days is None else max(1, min(body.expires_in_days, _MAX_EXPIRY_DAYS))
    share.expires_at = _now() + timedelta(days=days)
    if body.max_views is not None:
        share.max_views = max(1, body.max_views)

    raw = secrets.token_urlsafe(32)
    share.token_hash = _hash_token(raw)
    db.add(share)
    await db.commit()
    await db.refresh(share)

    base = (settings.public_base_url or "").rstrip("/")
    return {
        "id": str(share.id),
        "url": f"{base}/share/{raw}",
        "path": f"/share/{raw}",       # relative, for same-origin UIs
        "token": raw,                  # shown once; never stored
        "kind": share.kind,
        "expires_at": share.expires_at,
        "max_views": share.max_views,
    }


@router.get("", response_model=list[ShareResponse])
async def list_shares(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List share links. Admins see all; others see the ones they created."""
    q = select(ResourceShare).order_by(ResourceShare.created_at.desc())
    if current_user.role != "admin":
        q = q.where(ResourceShare.created_by_id == current_user.id)
    rows = (await db.execute(q)).scalars().all()
    return [_to_response(s) for s in rows]


@router.post("/{share_id}/revoke", response_model=ShareResponse)
async def revoke_share(
    share_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kill a share link immediately. Creator or admin only. Idempotent."""
    share = await db.get(ResourceShare, share_id)
    if not share or (current_user.role != "admin" and share.created_by_id != current_user.id):
        raise HTTPException(status_code=404, detail="Share not found")
    if share.revoked_at is None:
        share.revoked_at = _now()
        await db.commit()
        await db.refresh(share)
    return _to_response(share)


# ── public resolve / media (UNAUTHENTICATED) ──────────────────────────────

async def _load_valid_share(
    token: str, db: AsyncSession, *, count_view: bool, request: Request | None = None
) -> ResourceShare:
    """Resolve a raw token to an active share, or raise. When ``count_view`` is
    set, records one view (and enforces the cap on the NEXT resolve). Media
    sub-requests pass ``count_view=False`` so a single watch is one view."""
    share = (
        await db.execute(select(ResourceShare).where(ResourceShare.token_hash == _hash_token(token)))
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="This link is not valid")
    if share.revoked_at is not None:
        raise HTTPException(status_code=410, detail="This link has been revoked")
    if share.expires_at is not None and _now() > share.expires_at:
        raise HTTPException(status_code=410, detail="This link has expired")
    if share.max_views is not None and share.view_count >= share.max_views:
        raise HTTPException(status_code=410, detail="This link has reached its view limit")
    if count_view:
        share.view_count += 1
        share.last_accessed_at = _now()
        if request is not None and request.client is not None:
            share.last_accessed_ip = request.client.host
        await db.commit()
        await db.refresh(share)
    return share


async def _camera_name(db: AsyncSession, camera_id: uuid.UUID | None) -> str | None:
    if camera_id is None:
        return None
    cam = await db.get(Camera, camera_id)
    return cam.name if cam else None


@public_router.get("/{token}")
async def resolve_share(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """The viewer page loads this once. Counts a view, enforces expiry / revoke
    / view-cap, and returns just enough to render the shared item plus the
    media sub-path to fetch. Never leaks sibling resources."""
    share = await _load_valid_share(token, db, count_view=True, request=request)
    views_left = None if share.max_views is None else max(0, share.max_views - share.view_count)
    out: dict = {
        "kind": share.kind,
        "label": share.label,
        "expires_at": share.expires_at,
        "views_left": views_left,
        "media_path": f"/api/share/{token}/media",
    }

    if share.kind == "recording":
        rec = await db.get(Recording, share.recording_id)
        if not rec:
            raise HTTPException(status_code=410, detail="The shared recording is no longer available")
        out.update({
            "media_type": "video",
            "camera_name": await _camera_name(db, rec.camera_id),
            "started_at": rec.started_at,
            "duration_seconds": rec.duration_seconds,
        })
    elif share.kind == "observation":
        obs = await db.get(Observation, share.observation_id)
        if not obs:
            raise HTTPException(status_code=410, detail="The shared observation is no longer available")
        out.update({
            "media_type": "image" if obs.thumbnail_path else "none",
            "camera_name": await _camera_name(db, obs.camera_id),
            "started_at": obs.started_at,
            "description": obs.vlm_description,
        })
    else:  # event
        ev = await db.get(Event, share.event_id)
        if not ev:
            raise HTTPException(status_code=410, detail="The shared event is no longer available")
        obs = await db.get(Observation, ev.observation_id) if ev.observation_id else None
        out.update({
            "media_type": "image" if (obs and obs.thumbnail_path) else "none",
            "camera_name": await _camera_name(db, ev.camera_id or (obs.camera_id if obs else None)),
            "started_at": ev.fired_at,
            "severity": ev.severity,
            "description": (obs.vlm_description if obs else None),
        })
    return out


@public_router.get("/{token}/media")
async def share_media(token: str, db: AsyncSession = Depends(get_db)):
    """Serve the shared item's media. Re-validates the share but does NOT count
    a view (it is a sub-request of an already-counted page load). Reuses the
    normal serve paths, so the system's selective privacy blur is inherited."""
    share = await _load_valid_share(token, db, count_view=False)

    if share.kind == "recording":
        rec = await db.get(Recording, share.recording_id)
        if not rec:
            raise HTTPException(status_code=410, detail="No longer available")
        path = _get_disk_path_or_404(rec)  # resolves inside recordings root; already privacy-blurred if configured
        return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))

    # observation or event → serve the observation thumbnail (frame)
    obs: Observation | None = None
    if share.kind == "observation":
        obs = await db.get(Observation, share.observation_id)
    else:
        ev = await db.get(Event, share.event_id)
        if ev and ev.observation_id:
            obs = await db.get(Observation, ev.observation_id)
    if not obs or not obs.thumbnail_path:
        raise HTTPException(status_code=404, detail="No media for this share")
    path = resolve_inside(obs.thumbnail_path, settings.thumbnails_path)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(path, media_type="image/jpeg")
