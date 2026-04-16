import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.database import get_db
from shared.models import DigestEntry, User
from shared.schemas import DigestEntryResponse

router = APIRouter()


@router.get("", response_model=list[DigestEntryResponse])
async def list_digests(
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(DigestEntry).order_by(DigestEntry.generated_at.desc()).limit(limit)
    if camera_id:
        query = query.where(DigestEntry.camera_id == camera_id)
    result = await db.execute(query)
    return result.scalars().all()
