"""Programmatic API key management.

Each user mints their own long-lived keys for scripts and integrations.
The plaintext is returned once at creation and never again. Lookups,
revocation, and listing operate on metadata only.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import generate_api_key, get_current_user
from shared.database import get_db
from shared.models import ApiKey, User

router = APIRouter()


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default="read")  # "read" or "write"
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scope: str
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyResponse):
    # Plaintext key. shown exactly once.
    key: str


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreated:
    if body.scope not in ("read", "write"):
        raise HTTPException(status_code=400, detail="scope must be 'read' or 'write'")
    plaintext, key_hash, prefix = generate_api_key()
    row = ApiKey(
        user_id=current_user.id,
        name=body.name.strip(),
        key_hash=key_hash,
        prefix=prefix,
        scope=body.scope,
        expires_at=body.expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiKeyCreated(key=plaintext, **ApiKeyResponse.model_validate(row).model_dump())


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKey]:
    rows = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == current_user.id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.get(ApiKey, key_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    if row.revoked_at is None:
        from datetime import timezone

        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
