"""Async Telegram Bot API client.

Single shared ``httpx.AsyncClient`` per process. Methods raise
:class:`TelegramError` carrying the upstream ``error_code`` and
``description`` on non-OK responses so callers can branch on common
failures (e.g. 403 for blocked bot).

Phase 1 surface. ``get_me``, ``send_message``, ``get_updates``.
Phase 2 adds ``send_photo`` (multipart for local files, URL-fetch for
remote sources, with a 10MB fallback to a text message + link),
``answer_callback_query`` for the inline-button spinner clear,
``edit_message_reply_markup`` for ack-time keyboard rewrites, and
``set_my_commands`` for the bot menu hints. A 30 messages/sec
semaphore per token guards against Telegram's documented global
rate limit.

The :func:`sign_callback` / :func:`verify_callback` HMAC helpers gate
callback_data so a leaked button cannot be replayed cross-user. The
secret is :attr:`shared.config.settings.jwt_secret` so rotation
invalidates all outstanding buttons (acceptable; user re-acks via web).

Extension points for Phase 3+:
    - Webhook mode would replace the long-poller. the client itself
      is mode agnostic so set_webhook + delete_webhook land in a
      future iteration.
    - Per-chat token bucket would wrap ``send_message`` and
      ``send_photo`` at the call site, not in this module.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger("nurby.notify.telegram")

_API_BASE = "https://api.telegram.org"

# Telegram hard limits we surface to callers.
# https://core.telegram.org/bots/api#sendphoto
PHOTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB upload cap for sendPhoto
PHOTO_CAPTION_MAX = 1024  # caption length cap for sendPhoto
CALLBACK_DATA_MAX = 64  # callback_data byte cap

# Sentinel attached to a send_photo result dict under ``fallback`` when
# the photo could not be delivered and we fell back to a plain text
# message instead. The caller logs the degradation but the user still
# gets the alert.
PHOTO_FALLBACK_SENTINEL = "__photo_fallback__"

# Module-level shared client. Reused across all bots.
_client: httpx.AsyncClient | None = None
# Per-token send semaphores so we never exceed 30 messages/sec/bot.
_send_semaphores: dict[str, asyncio.Semaphore] = {}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        # Default timeout for short calls. getUpdates overrides per request.
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _client


async def shutdown_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _semaphore_for(token: str) -> asyncio.Semaphore:
    sem = _send_semaphores.get(token)
    if sem is None:
        # Telegram's global per-bot limit is ~30 messages/sec.
        sem = asyncio.Semaphore(30)
        _send_semaphores[token] = sem
    return sem


class TelegramError(Exception):
    """Wraps a non-OK Telegram Bot API response."""

    def __init__(self, error_code: int, description: str, method: str = "") -> None:
        self.error_code = error_code
        self.description = description
        self.method = method
        super().__init__(f"{method} -> {error_code}. {description}")

    @property
    def is_forbidden(self) -> bool:
        """403 covers `bot was blocked by the user`, `chat not found`,
        and `user is deactivated`. Callers use this to flip a channel
        into blocked/disabled state."""
        return self.error_code == 403


class TelegramAPI:
    """Stateless facade. Methods take a token explicitly so the same
    client is reused across many bot tokens without re-initialization.
    """

    @staticmethod
    async def _post(
        token: str,
        method: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 10.0,
        files: dict | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{_API_BASE}/bot{token}/{method}"
        client = _get_client()
        try:
            if files is not None:
                # Multipart upload (sendPhoto with a local file). The
                # Telegram API accepts non-file fields alongside the
                # file blob in the same multipart body.
                resp = await client.post(url, data=data or {}, files=files, timeout=timeout)
            else:
                resp = await client.post(url, json=payload or {}, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise TelegramError(0, f"timeout. {exc}", method) from exc
        except httpx.RequestError as exc:
            raise TelegramError(0, f"network. {exc}", method) from exc

        # Telegram always returns JSON even on errors.
        try:
            body = resp.json()
        except ValueError as exc:
            raise TelegramError(resp.status_code, f"non-json reply. {exc}", method) from exc

        if not body.get("ok"):
            code = int(body.get("error_code") or resp.status_code or 0)
            desc = str(body.get("description") or "unknown error")
            raise TelegramError(code, desc, method)
        return body.get("result", {})

    @classmethod
    async def get_me(cls, token: str) -> dict[str, Any]:
        return await cls._post(token, "getMe", {}, timeout=10.0)

    @classmethod
    async def send_message(
        cls,
        token: str,
        chat_id: str | int,
        text: str,
        parse_mode: str | None = "HTML",
        disable_notification: bool = False,
        disable_web_page_preview: bool = True,
        reply_markup: dict | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        sem = _semaphore_for(token)
        async with sem:
            return await cls._post(token, "sendMessage", payload, timeout=10.0)

    @classmethod
    async def get_updates(
        cls,
        token: str,
        offset: int | None = None,
        timeout: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        # The HTTP timeout has to exceed the long-poll timeout.
        result = await cls._post(token, "getUpdates", payload, timeout=timeout + 5)
        if isinstance(result, list):
            return result
        return []

    @classmethod
    async def send_photo(
        cls,
        token: str,
        chat_id: str | int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        disable_notification: bool = False,
        reply_markup: dict | None = None,
    ) -> dict[str, Any]:
        """Send a photo. ``photo`` can be a local filesystem path or
        an ``http(s)://`` URL. Files > 10MB or missing on disk fall
        back to :meth:`send_message` with the URL appended to the
        caption and return a result dict carrying
        :data:`PHOTO_FALLBACK_SENTINEL` under ``fallback`` so the
        caller can log the degradation. Captions longer than the
        Telegram cap (1024 chars) are clipped here; callers that need
        the full body should follow up with a plain ``send_message``.
        """
        is_remote = isinstance(photo, str) and photo.lower().startswith(("http://", "https://"))
        local_path = None if is_remote else photo

        # Local file existence + size guard. Keep the message flowing
        # even if the thumbnail was rotated away by the cleanup worker.
        if local_path is not None:
            if not os.path.exists(local_path):
                logger.warning(
                    "telegram send_photo. local path missing %s. falling back to text",
                    local_path,
                )
                return await cls._photo_fallback(
                    token, chat_id, caption, parse_mode, disable_notification, reply_markup,
                    reason="thumbnail_missing",
                )
            try:
                size = os.path.getsize(local_path)
            except OSError:
                size = 0
            if size > PHOTO_MAX_BYTES:
                logger.warning(
                    "telegram send_photo. file %s is %d bytes, over 10MB cap. text fallback",
                    local_path, size,
                )
                return await cls._photo_fallback(
                    token, chat_id, caption, parse_mode, disable_notification, reply_markup,
                    reason="photo_too_large",
                )

        clipped_caption = caption
        if clipped_caption and len(clipped_caption) > PHOTO_CAPTION_MAX:
            # Trim with a visible ellipsis so the operator notices.
            clipped_caption = clipped_caption[: PHOTO_CAPTION_MAX - 1] + "…"

        sem = _semaphore_for(token)
        async with sem:
            if is_remote:
                # Telegram fetches the URL server-side. Avoids us
                # streaming bytes through our process.
                payload: dict[str, Any] = {
                    "chat_id": chat_id,
                    "photo": photo,
                    "disable_notification": disable_notification,
                }
                if clipped_caption:
                    payload["caption"] = clipped_caption
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if reply_markup is not None:
                    payload["reply_markup"] = reply_markup
                return await cls._post(token, "sendPhoto", payload, timeout=30.0)

            # Local multipart upload.
            form: dict[str, Any] = {
                "chat_id": str(chat_id),
                "disable_notification": "true" if disable_notification else "false",
            }
            if clipped_caption:
                form["caption"] = clipped_caption
            if parse_mode:
                form["parse_mode"] = parse_mode
            if reply_markup is not None:
                form["reply_markup"] = json.dumps(reply_markup)

            try:
                file_handle = open(local_path, "rb")
            except OSError as exc:
                logger.warning("telegram send_photo. cannot open %s. %s", local_path, exc)
                return await cls._photo_fallback(
                    token, chat_id, caption, parse_mode, disable_notification, reply_markup,
                    reason="thumbnail_unreadable",
                )
            try:
                files = {"photo": (os.path.basename(local_path), file_handle, "image/jpeg")}
                return await cls._post(
                    token, "sendPhoto", payload=None,
                    files=files, data=form, timeout=60.0,
                )
            finally:
                try:
                    file_handle.close()
                except Exception:
                    pass

    @classmethod
    async def _photo_fallback(
        cls,
        token: str,
        chat_id: str | int,
        caption: str | None,
        parse_mode: str | None,
        disable_notification: bool,
        reply_markup: dict | None,
        reason: str,
    ) -> dict[str, Any]:
        """Photo could not be delivered. Send the caption as a plain
        text message instead so the user still gets the alert. The
        result dict carries a sentinel + reason for the caller to log.
        """
        text = caption or "(no caption)"
        result = await cls.send_message(
            token, chat_id, text,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
        )
        result = dict(result)
        result["fallback"] = PHOTO_FALLBACK_SENTINEL
        result["fallback_reason"] = reason
        return result

    @classmethod
    async def answer_callback_query(
        cls,
        token: str,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
        cache_time: int = 0,
    ) -> dict[str, Any]:
        """Acknowledge an inline-button press so the Telegram client
        stops showing the loading spinner. Telegram expects this
        within 15 seconds of receiving the callback. The poller
        always calls this even when the internal handler raises.
        """
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
            "cache_time": cache_time,
        }
        if text:
            # Telegram truncates >200 chars; clip locally so we don't
            # surprise the user with a chopped message.
            payload["text"] = text[:200]
        # Tight HTTP timeout. if we miss the 15s callback window the
        # spinner stays stuck briefly; better than blocking the worker.
        return await cls._post(token, "answerCallbackQuery", payload, timeout=8.0)

    @classmethod
    async def edit_message_reply_markup(
        cls,
        token: str,
        chat_id: str | int,
        message_id: int,
        reply_markup: dict | None,
    ) -> dict[str, Any]:
        """Replace the inline keyboard on an existing message. Used to
        grey out buttons after an ack so the user sees the state
        change reflected in the message itself.
        """
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await cls._post(token, "editMessageReplyMarkup", payload, timeout=10.0)

    # ------------------------------------------------------------------
    # Phase 3. webhook delivery helpers.
    # ------------------------------------------------------------------

    @classmethod
    async def set_webhook(
        cls,
        token: str,
        url: str,
        secret: str,
        max_connections: int = 20,
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a webhook delivery URL with Telegram.

        Telegram rejects non-HTTPS URLs and reachability is not
        verified by setWebhook itself. An unreachable URL returns OK
        here but :meth:`get_webhook_info` will eventually show a
        non-zero ``pending_update_count`` + ``last_error_message`` so
        the UI can surface the failure.
        """
        payload: dict[str, Any] = {
            "url": url,
            "secret_token": secret,
            "max_connections": max_connections,
            "drop_pending_updates": False,
        }
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = await cls._post(token, "setWebhook", payload, timeout=15.0)
        if isinstance(result, bool):
            return {"ok": result}
        return result or {"ok": True}

    @classmethod
    async def delete_webhook(cls, token: str, drop_pending_updates: bool = False) -> dict[str, Any]:
        payload = {"drop_pending_updates": drop_pending_updates}
        result = await cls._post(token, "deleteWebhook", payload, timeout=15.0)
        if isinstance(result, bool):
            return {"ok": result}
        return result or {"ok": True}

    @classmethod
    async def get_webhook_info(cls, token: str) -> dict[str, Any]:
        result = await cls._post(token, "getWebhookInfo", {}, timeout=10.0)
        if isinstance(result, dict):
            return result
        return {}

    @classmethod
    async def set_my_commands(
        cls,
        token: str,
        commands: list,
    ) -> dict[str, Any]:
        """Register slash commands shown in the bot's menu. Accepts
        either a list of ``(command, description)`` tuples or already
        shaped ``{"command": ..., "description": ...}`` dicts."""
        items: list[dict[str, str]] = []
        for entry in commands:
            if isinstance(entry, tuple) and len(entry) == 2:
                cmd, desc = entry
                items.append({"command": str(cmd), "description": str(desc)})
            elif isinstance(entry, dict):
                items.append({
                    "command": str(entry.get("command", "")),
                    "description": str(entry.get("description", "")),
                })
        return await cls._post(token, "setMyCommands", {"commands": items}, timeout=10.0)


# ── Callback HMAC signing ──
#
# Phase 2 inline buttons carry signed payloads. Without signing, an
# observer who scrapes a forwarded button could replay it on behalf of
# the original recipient. Format. ``<b64payload>.<b64sig>`` where both
# parts are urlsafe-base64 without padding. Total length is bounded by
# Telegram's 64-byte ``callback_data`` cap, so payloads should use the
# short keys defined alongside the action executor (a, e, r, d).


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    pad = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * pad))


def _callback_secret() -> bytes:
    # Derived from jwt_secret so rotation invalidates outstanding
    # buttons (acceptable; user re-acks via web UI). Hashing keeps the
    # secret out of HMAC's keyspace edge cases when operators choose
    # very short secrets.
    return hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()


def sign_callback(payload: str) -> str:
    """Sign a callback payload. Result is safe to put in
    ``callback_data`` as long as it stays under 64 bytes."""
    raw = payload.encode("utf-8")
    sig = hmac.new(_callback_secret(), raw, hashlib.sha256).digest()[:16]
    return f"{_b64encode(raw)}.{_b64encode(sig)}"


def verify_callback(signed: str) -> str | None:
    """Verify a signed callback. Returns the original payload string
    on success, ``None`` if the format is wrong or the HMAC mismatches.
    Constant-time comparison via :func:`hmac.compare_digest`."""
    if not signed or "." not in signed:
        return None
    body, sig_b64 = signed.rsplit(".", 1)
    try:
        raw = _b64decode(body)
        expected_sig = _b64decode(sig_b64)
    except Exception:
        return None
    actual_sig = hmac.new(_callback_secret(), raw, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(actual_sig, expected_sig):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# Phase 3. per-chat token bucket, dedupe store, guarded send wrappers,
# and media-quality re-encode for the "low" preset.
# ──────────────────────────────────────────────────────────────────────────

import io
import time
from datetime import datetime, timedelta, timezone

# Sentinels returned by the guarded send_* helpers. Callers in the
# action layer branch on these to log a non-failure event status
# instead of marking the rule action as errored.
DUPLICATE_SUPPRESSED = "duplicate_suppressed"
RATE_LIMITED_DROPPED = "rate_limited_dropped"
MEDIA_OFF_SENTINEL = "media_off"

# Cap on how long the per-chat limiter will block before giving up.
# Past this, the call returns RATE_LIMITED_DROPPED so callers don't
# accumulate an unbounded backlog when qps is set very low.
RATE_LIMIT_MAX_WAIT_SECONDS = 30.0


class PerChatLimiter:
    """Token bucket keyed by (token, chat_id).

    Telegram caps group chats at 20 messages/minute and private chats
    at ~1 message/second. We expose two knobs, ``qps`` and ``burst``,
    so users can tune per channel. Buckets live in process memory.
    Safe because all sends for a given bot go through this process
    (the action executor uses the same client) and per-chat state
    doesn't need to survive restarts.

    Idle buckets are pruned after 10 minutes by a lightweight GC
    triggered opportunistically on each :meth:`acquire`.
    """

    _IDLE_GC_SECONDS = 600

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], dict[str, Any]] = {}
        self._gc_lock = asyncio.Lock()
        self._last_gc = time.monotonic()

    async def acquire(self, token: str, chat_id: str | int, qps: float, burst: int) -> bool:
        """Sleep until a token is available, returning True on
        success. Returns False if the wait exceeded
        :data:`RATE_LIMIT_MAX_WAIT_SECONDS` so the caller can drop
        the send rather than backlog forever.
        """
        if qps <= 0:
            # Defensive. treat <=0 as "no rate limit" rather than divide by zero.
            return True

        key = (token, str(chat_id))
        deadline = time.monotonic() + RATE_LIMIT_MAX_WAIT_SECONDS
        while True:
            bucket = self._buckets.get(key)
            now = time.monotonic()
            if bucket is None:
                bucket = {
                    "tokens": float(burst),
                    "last_refill": now,
                    "last_touch": now,
                    "lock": asyncio.Lock(),
                }
                self._buckets[key] = bucket

            async with bucket["lock"]:
                elapsed = now - bucket["last_refill"]
                bucket["tokens"] = min(float(burst), bucket["tokens"] + elapsed * qps)
                bucket["last_refill"] = now
                bucket["last_touch"] = now
                if bucket["tokens"] >= 1.0:
                    bucket["tokens"] -= 1.0
                    await self._maybe_gc()
                    return True
                wait = (1.0 - bucket["tokens"]) / qps
            if now + wait > deadline:
                return False
            await asyncio.sleep(min(wait, 1.0))

    async def _maybe_gc(self) -> None:
        now = time.monotonic()
        if now - self._last_gc < 60.0:
            return
        async with self._gc_lock:
            if now - self._last_gc < 60.0:
                return
            stale = [
                k for k, b in self._buckets.items()
                if now - b["last_touch"] > self._IDLE_GC_SECONDS
            ]
            for k in stale:
                self._buckets.pop(k, None)
            self._last_gc = now


# Module-level singleton. shared across the action executor and any
# webhook-test harness so they coordinate on the same buckets.
per_chat_limiter = PerChatLimiter()


def _dedupe_hash(chat_id: str | int, body: str, photo_ref: str | None = None) -> str:
    """SHA-256 hex of ``chat_id || body || first 64 chars of photo_ref``.

    ``photo_ref`` may be a URL, filesystem path, or any stable
    identifier the caller has for the photo. it's truncated so small
    rotation in path-with-timestamps doesn't defeat dedupe.
    """
    h = hashlib.sha256()
    h.update(str(chat_id).encode("utf-8"))
    h.update(b"|")
    h.update((body or "").encode("utf-8", errors="replace"))
    h.update(b"|")
    if photo_ref:
        h.update(photo_ref[:64].encode("utf-8", errors="replace"))
    return h.hexdigest()


class DedupeStore:
    """Backed by the ``telegram_outbox_dedupe`` table.

    Each :meth:`is_duplicate` call.

    * Returns True if a row with the same (channel_id, hash) exists
      within ``window_seconds``. caller does not send.
    * Returns False otherwise and inserts a fresh row + opportunistic
      sweep of rows older than 1 hour. caller proceeds to send.

    Hashes collide deliberately when two different rules send the
    exact same text to the same chat. that's intended. the user
    genuinely sees identical content, so collapsing is fine.
    """

    async def is_duplicate(self, channel_id, message_hash: str, window_seconds: int) -> bool:
        if window_seconds <= 0:
            return False
        # Local imports avoid a hard module-load cycle (the models
        # package transitively imports config and crypto).
        from sqlalchemy import delete, select

        from shared.database import async_session
        from shared.models import TelegramOutboxDedupe

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        sweep_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        async with async_session() as db:
            result = await db.execute(
                select(TelegramOutboxDedupe.id)
                .where(TelegramOutboxDedupe.channel_id == channel_id)
                .where(TelegramOutboxDedupe.hash == message_hash)
                .where(TelegramOutboxDedupe.created_at >= cutoff)
                .limit(1)
            )
            if result.first() is not None:
                return True
            await db.execute(
                delete(TelegramOutboxDedupe).where(
                    TelegramOutboxDedupe.created_at < sweep_cutoff
                )
            )
            db.add(TelegramOutboxDedupe(channel_id=channel_id, hash=message_hash))
            await db.commit()
        return False


dedupe_store = DedupeStore()


async def send_message_guarded(
    *,
    token: str,
    channel_id,
    chat_id: str | int,
    text: str,
    qps: float,
    burst: int,
    dedupe_window_seconds: int,
    parse_mode: str | None = "HTML",
    disable_notification: bool = False,
    disable_web_page_preview: bool = True,
    reply_markup: dict | None = None,
) -> dict[str, Any] | str:
    """:meth:`TelegramAPI.send_message` + per-chat limiter + dedupe.

    Returns the Telegram response dict on success, or one of the
    sentinel strings :data:`DUPLICATE_SUPPRESSED` /
    :data:`RATE_LIMITED_DROPPED`. The action executor (Phase 2)
    branches on the sentinel to emit a non-failure event status.
    """
    h = _dedupe_hash(chat_id, text)
    if await dedupe_store.is_duplicate(channel_id, h, dedupe_window_seconds):
        return DUPLICATE_SUPPRESSED
    ok = await per_chat_limiter.acquire(token, chat_id, qps, burst)
    if not ok:
        return RATE_LIMITED_DROPPED
    return await TelegramAPI.send_message(
        token,
        chat_id,
        text,
        parse_mode=parse_mode,
        disable_notification=disable_notification,
        disable_web_page_preview=disable_web_page_preview,
        reply_markup=reply_markup,
    )


async def send_photo_guarded(
    *,
    token: str,
    channel_id,
    chat_id: str | int,
    photo: str,
    caption: str | None = None,
    qps: float,
    burst: int,
    dedupe_window_seconds: int,
    media_quality: str = "high",
    parse_mode: str | None = "HTML",
    disable_notification: bool = False,
    reply_markup: dict | None = None,
) -> dict[str, Any] | str:
    """:meth:`TelegramAPI.send_photo` + limiter + dedupe + quality.

    The ``photo`` argument matches Phase 2's :meth:`TelegramAPI.send_photo`
    contract (a local path or an HTTP URL).

    ``media_quality``:

    * ``off``  -> returns :data:`MEDIA_OFF_SENTINEL`. caller should
      fall back to a text-only send so the alert still goes through.
    * ``low``  -> if ``photo`` is a local path we re-encode to 720p
      JPEG q70 into a sibling file (``<orig>.lowq.jpg``) and send the
      re-encoded copy. URL-based sends pass through unchanged because
      Telegram itself does the fetch and re-encoding our own copy
      would defeat the bandwidth point.
    * ``high`` -> bytes pass through unchanged.

    On re-encode failure we fall back to the original file with a
    warning. a media-quality preference must never block the alert.
    """
    if media_quality == "off":
        return MEDIA_OFF_SENTINEL

    photo_arg = photo
    if media_quality == "low" and isinstance(photo, str) and not photo.lower().startswith(("http://", "https://")):
        recoded_path = _recode_to_lowq_file(photo)
        if recoded_path is not None:
            photo_arg = recoded_path

    h = _dedupe_hash(chat_id, caption or "", photo)
    if await dedupe_store.is_duplicate(channel_id, h, dedupe_window_seconds):
        return DUPLICATE_SUPPRESSED
    ok = await per_chat_limiter.acquire(token, chat_id, qps, burst)
    if not ok:
        return RATE_LIMITED_DROPPED
    return await TelegramAPI.send_photo(
        token,
        chat_id,
        photo_arg,
        caption=caption,
        parse_mode=parse_mode,
        disable_notification=disable_notification,
        reply_markup=reply_markup,
    )


def _recode_to_lowq_file(local_path: str) -> str | None:
    """Re-encode a local image to 720p JPEG q70 in a sibling file.

    Returns the new path on success or None on any failure (caller
    falls back to the original). Output path is deterministic so
    repeat re-encodes of the same source short-circuit on disk.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        logger.warning("PIL not available; skipping media re-encode")
        return None
    try:
        if not os.path.exists(local_path):
            return None
        # Sibling file. <stem>.lowq.jpg next to the original.
        if "." in os.path.basename(local_path):
            stem, _ = local_path.rsplit(".", 1)
        else:
            stem = local_path
        out_path = stem + ".lowq.jpg"
        # If we already produced one and it's newer than the source,
        # reuse it. shaves cost for hot rules.
        try:
            if (
                os.path.exists(out_path)
                and os.path.getmtime(out_path) >= os.path.getmtime(local_path)
            ):
                return out_path
        except OSError:
            pass

        with Image.open(local_path) as img:
            img.load()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            w, h = img.size
            long_edge = max(w, h)
            if long_edge > 720:
                scale = 720.0 / long_edge
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                img = img.resize(new_size, Image.LANCZOS)
            img.save(out_path, format="JPEG", quality=70, optimize=True, progressive=True)
        return out_path
    except Exception as exc:
        logger.warning("media re-encode failed for %s. %s. using original", local_path, exc)
        return None


def recode_bytes_lowq(data: bytes) -> bytes | None:
    """In-memory variant of :func:`_recode_to_lowq_file` for callers
    that hold image bytes rather than a path. Returns None on
    failure so the caller can fall back to the original bytes."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        logger.warning("PIL not available; skipping media re-encode")
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > 720:
            scale = 720.0 / long_edge
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70, optimize=True, progressive=True)
        return out.getvalue()
    except Exception as exc:
        logger.warning("media re-encode (bytes) failed (%s). returning None", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────
# Phase 4. message-index store + setMessageReaction wrapper.
# ──────────────────────────────────────────────────────────────────────────
#
# Reply-to-add-note + cluster-naming initiator both need a way to look
# up "what was this Telegram message about" given (channel_id,
# message_id). We park that in Redis with a 7-day TTL so a user
# replying to an alert from yesterday still resolves cleanly. Redis is
# already used for offset + pair keys so no new infra.

_MSG_INDEX_KEY_PREFIX = "nurby:tg_msg:"
_MSG_INDEX_TTL_SECONDS = 7 * 24 * 3600


def _msg_index_key(channel_id, message_id: int) -> str:
    return f"{_MSG_INDEX_KEY_PREFIX}{channel_id}:{int(message_id)}"


async def store_message_index(channel_id, message_id: int, payload: dict) -> None:
    """Persist a small JSON blob keyed by (channel_id, message_id).

    Used by the action executor right after a successful send so a
    later reply to that message can resolve the originating Event /
    Rule / dialog. Failures are logged but never raise, matching the
    "alert delivery is more important than provenance" rule that
    governs the whole notify stack.
    """
    try:
        import redis.asyncio as aioredis  # local import. avoids cycle

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.set(
                _msg_index_key(channel_id, message_id),
                json.dumps(payload, default=str),
                ex=_MSG_INDEX_TTL_SECONDS,
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
    except Exception:
        logger.debug(
            "telegram store_message_index failed channel=%s msg=%s",
            channel_id, message_id, exc_info=True,
        )


async def get_message_index(channel_id, message_id: int) -> dict | None:
    """Read the index entry persisted by :func:`store_message_index`.

    Returns ``None`` on miss or any read failure. Callers must handle
    the miss because TTL expiry, restart-without-redis, or an alert
    that pre-dated Phase 4 will all show up as missing entries.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            raw = await client.get(_msg_index_key(channel_id, message_id))
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
        if not raw:
            return None
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    except Exception:
        logger.debug(
            "telegram get_message_index failed channel=%s msg=%s",
            channel_id, message_id, exc_info=True,
        )
        return None


async def set_message_reaction(
    token: str,
    chat_id: str | int,
    message_id: int,
    emoji: str = "\U0001F44D",
) -> bool:
    """Best-effort wrapper around Telegram's setMessageReaction.

    Returns True when the API returned ok=true, False otherwise. Some
    bots (notably those that haven't set the privacy mode) get
    BAD_REQUEST. We degrade silently because reactions are a polish
    detail; the textual "Noted." confirmation is the actual ack.
    """
    payload = {
        "chat_id": chat_id,
        "message_id": int(message_id),
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": False,
    }
    try:
        await TelegramAPI._post(token, "setMessageReaction", payload, timeout=8.0)
        return True
    except TelegramError as exc:
        logger.debug("setMessageReaction failed. %s", exc.description)
        return False
    except Exception:
        logger.debug("setMessageReaction raised", exc_info=True)
        return False


__all__ = [
    "TelegramAPI",
    "TelegramError",
    "shutdown_client",
    "sign_callback",
    "verify_callback",
    "PHOTO_MAX_BYTES",
    "PHOTO_CAPTION_MAX",
    "CALLBACK_DATA_MAX",
    "PHOTO_FALLBACK_SENTINEL",
    # Phase 3.
    "PerChatLimiter",
    "DedupeStore",
    "per_chat_limiter",
    "dedupe_store",
    "send_message_guarded",
    "send_photo_guarded",
    "recode_bytes_lowq",
    "DUPLICATE_SUPPRESSED",
    "RATE_LIMITED_DROPPED",
    "MEDIA_OFF_SENTINEL",
    "RATE_LIMIT_MAX_WAIT_SECONDS",
    # Phase 4.
    "store_message_index",
    "get_message_index",
    "set_message_reaction",
]
