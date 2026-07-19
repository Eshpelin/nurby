import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin
from shared.database import get_db
from shared.models import InviteKey, User
from shared.schemas import (
    InviteCreatorInfo,
    InviteKeyCreate,
    InviteKeyResponse,
    InviteRedemptionInfo,
)

router = APIRouter()


@router.get("", response_model=list[InviteKeyResponse])
async def list_invites(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all invite keys with audit context. Admin only.

    Each key carries who created it and the roster of accounts that redeemed
    it (name, email, role, and when), so the Settings UI can show usage at a
    glance instead of a bare ``used 2/5`` counter.
    """
    result = await db.execute(select(InviteKey).order_by(InviteKey.created_at.desc()))
    keys = result.scalars().all()
    if not keys:
        return []

    # Resolve creators and redeemers in two batched queries rather than N
    # lazy loads (async sessions can't lazy-load relationships anyway).
    creator_ids = {k.created_by_id for k in keys}
    creators = (
        await db.execute(select(User).where(User.id.in_(creator_ids)))
    ).scalars().all()
    creator_by_id = {u.id: u for u in creators}

    key_ids = [k.id for k in keys]
    redeemers = (
        await db.execute(
            select(User)
            .where(User.invite_key_id.in_(key_ids))
            .order_by(User.created_at.asc())
        )
    ).scalars().all()
    redemptions_by_key: dict[uuid.UUID, list[InviteRedemptionInfo]] = {}
    for u in redeemers:
        redemptions_by_key.setdefault(u.invite_key_id, []).append(
            InviteRedemptionInfo(
                user_id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=u.role,
                is_active=u.is_active,
                redeemed_at=u.created_at,
            )
        )

    out: list[InviteKeyResponse] = []
    for k in keys:
        creator = creator_by_id.get(k.created_by_id)
        out.append(
            InviteKeyResponse(
                id=k.id,
                key=k.key,
                role=k.role,
                camera_ids=k.camera_ids,
                max_uses=k.max_uses,
                use_count=k.use_count,
                expires_at=k.expires_at,
                created_at=k.created_at,
                created_by=(
                    InviteCreatorInfo(
                        id=creator.id,
                        email=creator.email,
                        display_name=creator.display_name,
                    )
                    if creator
                    else None
                ),
                redemptions=redemptions_by_key.get(k.id, []),
            )
        )
    return out


@router.post("", response_model=InviteKeyResponse, status_code=201)
async def create_invite(
    body: InviteKeyCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new invite key. Admin only. The key string is auto-generated."""
    # Convert camera_ids to JSON-serialisable list of strings
    camera_ids_json = None
    if body.camera_ids:
        camera_ids_json = [str(cid) for cid in body.camera_ids]

    invite = InviteKey(
        key=secrets.token_hex(16),
        created_by_id=admin.id,
        role=body.role,
        camera_ids=camera_ids_json,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


@router.delete("/{invite_id}", status_code=204)
async def delete_invite(
    invite_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an invite key. Admin only."""
    invite = await db.get(InviteKey, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite key not found")

    await db.delete(invite)
    await db.commit()
