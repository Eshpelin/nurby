"""Dashboard widget CRUD + proxied data fetch.

Widgets are per-user custom dashboard tiles that pull from an external HTTP
API. The auth secret is sealed at rest and injected server-side only; the
browser sees ``has_auth`` but never the key. See services/api/widget_proxy.py
for the egress-guarded fetch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.widget_proxy import cache_clear, cache_get, cache_put, fetch_widget_data
from shared.auth import get_current_user
from shared.camera_secrets import seal, unseal
from shared.database import get_db
from shared.models import DashboardWidget, User
from shared.schemas import (
    WidgetCreate,
    WidgetDataResponse,
    WidgetResponse,
    WidgetTestRequest,
    WidgetUpdate,
)

router = APIRouter()


def _to_response(row: DashboardWidget) -> WidgetResponse:
    return WidgetResponse(
        id=row.id,
        name=row.name,
        enabled=row.enabled,
        render_kind=row.render_kind,
        source=row.source,
        has_auth=bool(row.auth_secret),
        template=row.template,
        custom_html=row.custom_html,
        layout=row.layout,
        last_fetch_at=row.last_fetch_at,
        last_status=row.last_status,
        last_error=row.last_error,
        created_at=row.created_at,
    )


async def _owned(widget_id: uuid.UUID, user: User, db: AsyncSession) -> DashboardWidget:
    row = await db.get(DashboardWidget, widget_id)
    if row is None or row.created_by_user_id != user.id:
        # Same 404 whether absent or another user's, so ownership is not probeable.
        raise HTTPException(status_code=404, detail="Widget not found")
    return row


@router.get("", response_model=list[WidgetResponse])
async def list_widgets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WidgetResponse]:
    rows = (
        await db.execute(
            select(DashboardWidget)
            .where(DashboardWidget.created_by_user_id == user.id)
            .order_by(DashboardWidget.created_at.asc())
        )
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.post("", response_model=WidgetResponse, status_code=201)
async def create_widget(
    body: WidgetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetResponse:
    row = DashboardWidget(
        created_by_user_id=user.id,
        name=body.name.strip(),
        enabled=body.enabled,
        render_kind=body.render_kind,
        source=body.source.model_dump(),
        auth_secret=seal(body.auth_secret) if body.auth_secret else None,
        template=body.template,
        custom_html=body.custom_html,
        layout=body.layout,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.patch("/{widget_id}", response_model=WidgetResponse)
async def update_widget(
    widget_id: uuid.UUID,
    body: WidgetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetResponse:
    row = await _owned(widget_id, user, db)
    updates = body.model_dump(exclude_unset=True)
    if "source" in updates and updates["source"] is not None:
        row.source = updates.pop("source")
    else:
        updates.pop("source", None)
    if "auth_secret" in updates:
        # Empty string clears the stored secret; a value re-seals it.
        val = updates.pop("auth_secret")
        row.auth_secret = seal(val) if val else None
    for key, val in updates.items():
        setattr(row, key, val)
    cache_clear(str(row.id))
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.delete("/{widget_id}", status_code=204)
async def delete_widget(
    widget_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _owned(widget_id, user, db)
    cache_clear(str(row.id))
    await db.delete(row)
    await db.commit()


@router.get("/{widget_id}/data", response_model=WidgetDataResponse)
async def get_widget_data(
    widget_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    row = await _owned(widget_id, user, db)
    source = row.source or {}

    cached = cache_get(str(row.id))
    if cached is not None:
        return WidgetDataResponse(**cached)

    result = await fetch_widget_data(source, unseal(row.auth_secret))
    refresh = int(source.get("refresh_seconds") or 60)
    cache_put(str(row.id), result, ttl=max(10, refresh))

    row.last_fetch_at = datetime.now(timezone.utc)
    row.last_status = "ok" if result.get("ok") else "error"
    row.last_error = result.get("error")
    await db.commit()

    return WidgetDataResponse(
        ok=bool(result.get("ok")),
        status=result.get("status"),
        data=result.get("data"),
        fetched_at=row.last_fetch_at,
        error=result.get("error"),
    )


@router.post("/test", response_model=WidgetDataResponse)
async def test_widget(
    body: WidgetTestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    """Dry-run a draft source for the builder preview. No DB write, no cache.
    Reuses the saved secret when editing and none is supplied."""
    secret = body.auth_secret or None
    if secret is None and body.widget_id is not None:
        row = await db.get(DashboardWidget, body.widget_id)
        if row is not None and row.created_by_user_id == user.id:
            secret = unseal(row.auth_secret)
    result = await fetch_widget_data(body.source.model_dump(), secret)
    return WidgetDataResponse(
        ok=bool(result.get("ok")),
        status=result.get("status"),
        data=result.get("data"),
        fetched_at=datetime.now(timezone.utc),
        error=result.get("error"),
    )
