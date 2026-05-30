"""Standing webhook subscriptions.

A subscription receives every fired event (optionally filtered by rule
or camera) at its URL, signed with HMAC when a secret is set. This is
the system-wide complement to per-rule webhook actions. Admin-managed.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user, require_admin
from shared.database import get_db
from shared.models import User, WebhookSubscription

router = APIRouter()


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=1024)
    secret: str | None = Field(default=None, max_length=255)
    active: bool = True
    rule_ids: list[uuid.UUID] | None = None
    camera_ids: list[uuid.UUID] | None = None


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=1024)
    secret: str | None = Field(default=None, max_length=255)
    active: bool | None = None
    rule_ids: list[uuid.UUID] | None = None
    camera_ids: list[uuid.UUID] | None = None


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    active: bool
    # secret is write-only. expose only whether one is set.
    has_secret: bool
    rule_ids: list[uuid.UUID] | None
    camera_ids: list[uuid.UUID] | None
    last_delivery_at: datetime | None
    last_status: str | None
    created_at: datetime


def _to_response(row: WebhookSubscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=row.id,
        name=row.name,
        url=row.url,
        active=row.active,
        has_secret=bool(row.secret),
        rule_ids=row.rule_ids,
        camera_ids=row.camera_ids,
        last_delivery_at=row.last_delivery_at,
        last_status=row.last_status,
        created_at=row.created_at,
    )


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionResponse]:
    rows = (
        await db.execute(
            select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc())
        )
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.post("", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: SubscriptionCreate,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    row = WebhookSubscription(
        name=body.name.strip(),
        url=body.url.strip(),
        secret=body.secret or None,
        active=body.active,
        rule_ids=[str(r) for r in body.rule_ids] if body.rule_ids else None,
        camera_ids=[str(c) for c in body.camera_ids] if body.camera_ids else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.patch("/{sub_id}", response_model=SubscriptionResponse)
async def update_subscription(
    sub_id: uuid.UUID,
    body: SubscriptionUpdate,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    row = await db.get(WebhookSubscription, sub_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    updates = body.model_dump(exclude_unset=True)
    for key, val in updates.items():
        if key in ("rule_ids", "camera_ids") and val is not None:
            val = [str(v) for v in val]
        setattr(row, key, val)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: uuid.UUID,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.get(WebhookSubscription, sub_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(row)
    await db.commit()
