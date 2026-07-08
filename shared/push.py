"""Mobile push dispatch over FCM HTTP v1.

The service-account JSON an admin pastes into the app settings key
``push_fcm_service_account`` (PATCH /api/system/settings) is the only
configuration. Unconfigured installs no-op: every caller gets
``{"sent": 0, "skipped": True}`` and nothing else happens, so push stays
a strictly additive channel.

Dispatch is best-effort by design. ``send_push_to_user`` never raises
into the caller path (rule firing, report delivery, guardian alerts must
not break because a push could not go out). Tokens FCM reports as dead
(HTTP 404 / UNREGISTERED) are deleted so the registry self-heals.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from shared.app_settings import get_setting
from shared.models import PushDevice

logger = logging.getLogger("nurby.push")

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# OAuth2 access-token microcache. FCM tokens live ~1h; minting one per
# send would add a round-trip to Google on every notification.
_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _reset_token_cache() -> None:
    """Test helper. Forget the cached FCM access token."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


def _mint_access_token(service_account: dict) -> tuple[str, float]:
    """Blocking google-auth call. Runs inside asyncio.to_thread.

    Returns (access_token, unix_expiry). Raises on any failure; the async
    wrapper turns that into a logged no-op.
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account as gsa

    creds = gsa.Credentials.from_service_account_info(service_account, scopes=[FCM_SCOPE])
    creds.refresh(Request())
    expiry = creds.expiry.timestamp() if creds.expiry else time.time() + 300
    return creds.token, expiry


async def _access_token(service_account: dict) -> str | None:
    now = time.time()
    if _token_cache["token"] and now < float(_token_cache["expires_at"]) - 60:
        return _token_cache["token"]
    try:
        token, expires_at = await asyncio.to_thread(_mint_access_token, service_account)
    except ImportError:
        logger.warning("push: google-auth is not installed; cannot mint an FCM token")
        return None
    except Exception:
        logger.exception("push: minting the FCM access token failed")
        return None
    _token_cache["token"] = token
    _token_cache["expires_at"] = expires_at
    return token


async def _fcm_send(access_token: str, project_id: str, message: dict) -> tuple[int, dict]:
    """One FCM HTTP v1 send. Returns (status_code, response_body).

    Kept as a module-level seam so tests monkeypatch it instead of
    mocking httpx internals (mirrors the deliver_signed seam in the
    webhook tests).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            FCM_SEND_URL.format(project_id=project_id),
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": message},
        )
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


def _is_unregistered(status_code: int, body: dict) -> bool:
    """True when FCM says this registration token no longer exists."""
    if status_code == 404:
        return True
    err = body.get("error") or {}
    if err.get("status") == "NOT_FOUND":
        return True
    for detail in err.get("details") or []:
        if isinstance(detail, dict) and detail.get("errorCode") == "UNREGISTERED":
            return True
    return False


async def send_push_to_user(
    session,
    user_id: uuid.UUID | None,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    """Send a push notification to every registered device of ``user_id``.

    ``user_id=None`` fans out to every registered device, matching the
    Notification.user_id semantics (null = household-wide). ``data``
    values are stringified because FCM only accepts string-to-string
    data payloads. Returns ``{"sent": n, "errors": [...]}`` (plus
    ``"skipped": True`` when push is unconfigured). Never raises.
    """
    try:
        return await _dispatch(session, user_id, title, body, data or {})
    except Exception:
        logger.exception("push: dispatch failed for user %s", user_id)
        return {"sent": 0, "errors": ["push dispatch crashed; see logs"]}


async def _dispatch(session, user_id, title: str, body: str, data: dict) -> dict:
    service_account = await get_setting("push_fcm_service_account")
    if not isinstance(service_account, dict) or not service_account.get("project_id"):
        return {"sent": 0, "skipped": True}

    query = select(PushDevice)
    if user_id is not None:
        query = query.where(PushDevice.user_id == user_id)
    devices = (await session.execute(query)).scalars().all()
    if not devices:
        return {"sent": 0, "errors": []}

    access_token = await _access_token(service_account)
    if access_token is None:
        return {"sent": 0, "errors": ["could not mint an FCM access token"]}

    project_id = service_account["project_id"]
    sent = 0
    errors: list[str] = []
    stale: list[PushDevice] = []
    for device in devices:
        message = {
            "token": device.token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in data.items()},
        }
        try:
            status_code, resp_body = await _fcm_send(access_token, project_id, message)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{device.id}: {exc}")
            continue
        if 200 <= status_code < 300:
            sent += 1
        elif _is_unregistered(status_code, resp_body):
            # FCM says the token is dead (app uninstalled, token rotated).
            # Prune the row so we stop paying for it on every send.
            stale.append(device)
        else:
            detail = (resp_body.get("error") or {}).get("message") or f"status {status_code}"
            errors.append(f"{device.id}: {detail}")

    if stale:
        try:
            for device in stale:
                await session.delete(device)
            await session.commit()
        except Exception:
            logger.exception("push: pruning %d unregistered device(s) failed", len(stale))

    return {"sent": sent, "errors": errors}
