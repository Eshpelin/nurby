"""Dashboard widgets: sources, CRUD payloads and test/data
responses.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ── Dashboard widget schemas ──

class WidgetSource(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    method: str = Field(default="GET", max_length=8)
    query: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    body: str | None = Field(default=None, max_length=8192)
    # none | bearer | header | query | basic
    auth_kind: str = Field(default="none", max_length=16)
    # header or query-param name (for auth_kind in {header, query})
    auth_name: str | None = Field(default=None, max_length=128)
    refresh_seconds: int = Field(default=60, ge=10, le=86400)

    @field_validator("method")
    @classmethod
    def _method_ok(cls, v: str) -> str:
        v = (v or "GET").upper()
        if v not in ("GET", "POST"):
            raise ValueError("method must be GET or POST")
        return v

    @field_validator("auth_kind")
    @classmethod
    def _auth_ok(cls, v: str) -> str:
        if v not in ("none", "bearer", "header", "query", "basic"):
            raise ValueError("invalid auth_kind")
        return v


class WidgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    render_kind: str = Field(default="template", max_length=16)
    source: WidgetSource
    auth_secret: str | None = Field(default=None, max_length=2048)  # write-only
    template: dict | None = None
    custom_html: str | None = Field(default=None, max_length=200_000)
    layout: dict | None = None

    @field_validator("render_kind")
    @classmethod
    def _kind_ok(cls, v: str) -> str:
        if v not in ("template", "custom"):
            raise ValueError("render_kind must be 'template' or 'custom'")
        return v


class WidgetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    render_kind: str | None = Field(default=None, max_length=16)
    source: WidgetSource | None = None
    # "" clears the stored secret; omitted leaves it unchanged.
    auth_secret: str | None = Field(default=None, max_length=2048)
    template: dict | None = None
    custom_html: str | None = Field(default=None, max_length=200_000)
    layout: dict | None = None


class WidgetResponse(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    render_kind: str
    source: dict | None
    has_auth: bool
    template: dict | None
    custom_html: str | None
    layout: dict | None
    last_fetch_at: datetime | None
    last_status: str | None
    last_error: str | None
    created_at: datetime


class WidgetTestRequest(BaseModel):
    source: WidgetSource
    auth_secret: str | None = Field(default=None, max_length=2048)
    # When testing edits to a saved widget, reuse its stored secret if no new
    # one is supplied here.
    widget_id: uuid.UUID | None = None


class WidgetDataResponse(BaseModel):
    ok: bool
    status: int | None = None
    data: object | None = None
    fetched_at: datetime | None = None
    error: str | None = None
