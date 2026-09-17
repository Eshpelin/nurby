"""Telegram channels, delivery updates, webhook info and
pairing/test payloads.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# -- Telegram channel schemas --

class TelegramChannelCreate(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    bot_token: str = Field(min_length=20, max_length=512)


class TelegramChannelUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    default_silent: bool | None = None
    enabled: bool | None = None
    # Phase 3 settings. delivery_mode is NOT settable here. use the
    # dedicated /delivery endpoint so we can call setWebhook /
    # deleteWebhook atomically.
    media_quality: str | None = Field(default=None, pattern=r"^(off|low|high)$")
    rate_limit_per_chat_qps: float | None = Field(default=None, ge=0.05, le=10.0)
    rate_limit_per_chat_burst: int | None = Field(default=None, ge=1, le=20)
    dedupe_window_seconds: int | None = Field(default=None, ge=0, le=600)
    # Phase 4. Household sharing. Owner-only; the route rejects PATCH
    # by non-owners. ``share_permissions`` is 'use' or 'use_and_test'.
    shared_with_household: bool | None = None
    share_permissions: str | None = Field(default=None, pattern=r"^(use|use_and_test)$")


class TelegramChannelResponse(BaseModel):
    id: uuid.UUID
    label: str
    bot_username: str | None
    chat_id: str | None
    chat_title: str | None
    chat_type: str | None
    default_silent: bool
    enabled: bool
    paired_at: datetime | None
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_error: str | None
    pairing_status: str  # pending | paired | blocked | disabled | error
    # Phase 3 fields. webhook_secret is intentionally never exposed.
    delivery_mode: str  # long_poll | webhook
    webhook_url: str | None
    media_quality: str  # off | low | high
    rate_limit_per_chat_qps: float
    rate_limit_per_chat_burst: int
    dedupe_window_seconds: int
    # Phase 4. Household sharing. ``owned_by_me`` is computed by the
    # route per-request so a non-owner sees the channel as
    # "shared by <Other>". ``owner_display_name`` is best-effort.
    shared_with_household: bool = False
    share_permissions: str = "use"
    owned_by_me: bool = True
    owner_display_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TelegramDeliveryUpdate(BaseModel):
    """Request body for POST /channels/{id}/delivery."""

    mode: str = Field(pattern=r"^(long_poll|webhook)$")
    # When flipping webhook -> long_poll. ask Telegram to discard
    # pending updates instead of replaying them on the next poll.
    drop_pending_updates: bool = False


class TelegramWebhookInfoResponse(BaseModel):
    """Passthrough of Telegram getWebhookInfo for the settings UI."""

    url: str | None = None
    has_custom_certificate: bool = False
    pending_update_count: int = 0
    last_error_date: int | None = None
    last_error_message: str | None = None
    ip_address: str | None = None
    max_connections: int | None = None
    # Backend reachability check. None means we did not attempt the
    # probe. true/false reflects an HTTP GET from the backend to
    # ``public_base_url + /api/health``.
    backend_reachable: bool | None = None
    backend_probe_error: str | None = None


class TelegramPairInitResponse(BaseModel):
    nonce: str
    deep_link: str
    qr_payload: str
    expires_in_seconds: int


class TelegramTestResponse(BaseModel):
    ok: bool
    message_id: int | None = None
    error: str | None = None
