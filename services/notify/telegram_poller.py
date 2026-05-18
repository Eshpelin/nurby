"""Background long-poll workers for paired Telegram bots.

One asyncio task per enabled bot token. The manager scans the
``telegram_channels`` table every 30 seconds and starts, stops, or
restarts tasks to track the desired state. Each worker calls
``getUpdates`` with a 25 second long-poll, persists its update offset
cursor in Redis so restarts resume cleanly, and routes incoming
messages.

Phase 1 routed ``/start <nonce>`` and ``/pair <nonce>`` only. Phase 2
extends the allowed_updates filter to include ``callback_query`` and
dispatches inline-button presses into a small handler set
(``ack`` | ``mute_event`` | ``snooze_rule`` | ``open``). Each handler
acknowledges the callback with :meth:`TelegramAPI.answer_callback_query`
within the 15 second Telegram window even when the internal DB write
fails, so the user's spinner always clears.

Phase 3+ will replace the long-poller with a webhook receiver. The
update payload shape is the same, so the handler set defined here will
keep working without modification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select

from shared.config import settings
from shared.crypto import InvalidToken, decrypt_secret
from shared.database import async_session
from shared.models import Event, Rule, TelegramChannel, User

from services.notify.telegram import TelegramAPI, TelegramError, verify_callback

logger = logging.getLogger("nurby.notify.telegram_poller")

_OFFSET_KEY_PREFIX = "nurby:tg_offset:"
_PAIR_KEY_PREFIX = "nurby:tg_pair:"

# Phase 3. per-channel asyncio.Lock so concurrent webhook deliveries
# serialize chat-state mutations within a single channel without
# blocking unrelated channels. The long-poll worker is single-threaded
# per channel so the lock is a no-op there, but the webhook route
# may invoke handle_update from many concurrent BackgroundTasks.
_channel_locks: dict[str, asyncio.Lock] = {}


def _channel_lock(channel_id: str) -> asyncio.Lock:
    lock = _channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel_id] = lock
    return lock

# Bot menu hints. These don't wire actual slash command handlers
# (Phase 2 only needs the inline buttons). Showing them in the menu
# helps users discover the actions when buttons aren't visible in the
# chat history.
_BOT_COMMANDS = [
    ("ack", "Acknowledge latest alert"),
    ("mute", "Mute 10 minutes"),
    ("snooze", "Snooze rule 1 hour"),
]

# Allowed callback actions. Documented as an extension point. Phase 4
# household sharing + face-cluster naming will add new variants like
# ``name_cluster``; the verify -> dispatch path here keys off this
# tuple so a stray future deployment cannot replay an unknown action.
_CALLBACK_ACTIONS = ("ack", "mute_event", "snooze_rule", "open")


def offset_key(channel_id) -> str:
    return f"{_OFFSET_KEY_PREFIX}{channel_id}"


def pair_key(nonce: str) -> str:
    return f"{_PAIR_KEY_PREFIX}{nonce}"


class TelegramPollerManager:
    """Owns one long-poll task per enabled, token-bearing channel.

    Tasks are keyed by channel id. The manager re-scans the DB on a
    fixed cadence so add/remove/rename/token-rotate all eventually
    converge without explicit signalling.
    """

    REFRESH_SECONDS = 30

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        # Tracks (token, enabled, delivery_mode) so we detect token
        # rotation OR a delivery-mode flip between long_poll/webhook.
        self._signatures: dict[str, tuple[str, bool, str]] = {}
        self._stop = asyncio.Event()
        self._redis: aioredis.Redis | None = None

    async def _redis_client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def stop(self) -> None:
        self._stop.set()
        for task in self._tasks.values():
            task.cancel()

    async def run(self) -> None:
        """Main supervisor loop. Cancellation-safe."""
        try:
            while not self._stop.is_set():
                try:
                    await self._reconcile()
                except Exception:
                    logger.exception("telegram poller reconcile failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.REFRESH_SECONDS)
                except asyncio.TimeoutError:
                    pass
        finally:
            for task in list(self._tasks.values()):
                task.cancel()
            # Allow tasks to wind down so cancellation doesn't leak
            for task in list(self._tasks.values()):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            self._tasks.clear()
            if self._redis is not None:
                try:
                    await self._redis.aclose()
                except Exception:
                    pass

    async def _reconcile(self) -> None:
        """Bring the running task set in line with the DB."""
        # Phase 3. signature also tracks delivery_mode so a flip
        # between long_poll <-> webhook restarts/stops the task.
        desired: dict[str, tuple[str, bool, str]] = {}
        async with async_session() as db:
            result = await db.execute(select(TelegramChannel))
            for ch in result.scalars().all():
                if not ch.enabled:
                    continue
                # Phase 3. webhook-mode channels are owned by the
                # /api/telegram/webhook/{id} route. skip them here so
                # we never compete with Telegram's webhook delivery.
                if (ch.delivery_mode or "long_poll") != "long_poll":
                    continue
                try:
                    token = decrypt_secret(ch.bot_token_enc)
                except InvalidToken:
                    logger.warning(
                        "Telegram channel %s has unreadable token (jwt_secret rotated?)", ch.id
                    )
                    continue
                desired[str(ch.id)] = (token, ch.enabled, ch.delivery_mode or "long_poll")

        # Stop tasks whose channel was disabled, deleted, switched to
        # webhook, or whose token rotated.
        for channel_id, sig in list(self._signatures.items()):
            new_sig = desired.get(channel_id)
            if new_sig is None or new_sig != sig:
                task = self._tasks.pop(channel_id, None)
                if task is not None:
                    task.cancel()
                self._signatures.pop(channel_id, None)

        # Start tasks for newly enabled / new channels.
        for channel_id, sig in desired.items():
            if channel_id in self._tasks and not self._tasks[channel_id].done():
                continue
            token, _enabled, _mode = sig
            self._signatures[channel_id] = sig
            self._tasks[channel_id] = asyncio.create_task(
                self._worker(channel_id, token), name=f"tg-poller-{channel_id[:8]}"
            )

    async def _worker(self, channel_id: str, token: str) -> None:
        """Long-poll loop for a single bot."""
        redis = await self._redis_client()

        # Phase 3. if a webhook was registered in a prior run (or by a
        # sibling process) Telegram refuses getUpdates with 409. Clear
        # any stale registration before starting the poll loop. This
        # avoids the silent-no-updates trap users hit after toggling
        # from webhook back to long-poll while the row already had
        # delivery_mode='long_poll' but Telegram still held the URL.
        try:
            info = await TelegramAPI.get_webhook_info(token)
            if info.get("url"):
                logger.info(
                    "telegram channel=%s clearing stale webhook %s before long-poll",
                    channel_id, info.get("url"),
                )
                await TelegramAPI.delete_webhook(token, drop_pending_updates=False)
        except TelegramError as exc:
            logger.warning(
                "telegram channel=%s could not clear webhook before poll. %s",
                channel_id, exc,
            )
        except Exception:
            logger.debug(
                "telegram channel=%s getWebhookInfo raised", channel_id, exc_info=True,
            )

        try:
            raw = await redis.get(offset_key(channel_id))
            offset = int(raw) + 1 if raw else None
        except Exception:
            offset = None

        logger.info("telegram poller starting for channel=%s", channel_id)
        # Best-effort bot menu setup. Non-fatal because not every
        # Telegram bot supports setMyCommands the same way (e.g. shared
        # group bots can return BAD_REQUEST when called from a worker
        # that didn't create them).
        try:
            await TelegramAPI.set_my_commands(token, _BOT_COMMANDS)
        except TelegramError as exc:
            logger.debug(
                "telegram channel=%s setMyCommands skipped. %s", channel_id, exc.description,
            )
        except Exception:
            logger.debug("telegram channel=%s setMyCommands raised", channel_id, exc_info=True)

        backoff = 1.0
        while not self._stop.is_set():
            try:
                updates = await TelegramAPI.get_updates(
                    token,
                    offset=offset,
                    timeout=25,
                    allowed_updates=["message", "callback_query"],
                )
                backoff = 1.0
                for update in updates:
                    try:
                        await self.handle_update(channel_id, update)
                    except Exception:
                        logger.exception(
                            "telegram poller failed handling update channel=%s", channel_id
                        )
                    uid = int(update.get("update_id", 0))
                    if uid:
                        offset = uid + 1
                        try:
                            await redis.set(offset_key(channel_id), str(uid))
                        except Exception:
                            pass
            except TelegramError as exc:
                if exc.error_code == 409:
                    # Another instance is polling, or webhook is set. Back off hard.
                    logger.warning(
                        "telegram channel=%s conflict (409). %s. backing off",
                        channel_id, exc.description,
                    )
                    await asyncio.sleep(60)
                    continue
                logger.warning(
                    "telegram channel=%s getUpdates error %s. %s",
                    channel_id, exc.error_code, exc.description,
                )
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telegram channel=%s unexpected poller error", channel_id)
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    async def handle_update(self, channel_id: str, update: dict) -> None:
        """Public entry point used by both the long-poll worker and the
        Phase 3 webhook route. Wraps the dispatch in a per-channel
        :class:`asyncio.Lock` so concurrent webhook deliveries serialize
        chat-state mutations within a single channel without blocking
        unrelated channels.
        """
        async with _channel_lock(channel_id):
            await self._handle_update(channel_id, update)

    async def _handle_update(self, channel_id: str, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            await self._handle_callback_query(channel_id, callback)
            return
        message = update.get("message")
        if not message:
            return
        text = (message.get("text") or "").strip()
        if not text:
            return
        # Match `/start <nonce>` or `/pair <nonce>`. Strip optional bot
        # suffix like `/start@MyBot`.
        parts = text.split(maxsplit=1)
        if not parts:
            return
        cmd = parts[0].split("@", 1)[0].lower()
        if cmd not in ("/start", "/pair"):
            logger.debug("telegram channel=%s ignoring text. %r", channel_id, text[:80])
            return
        nonce = parts[1].strip() if len(parts) > 1 else ""
        if not nonce:
            return
        await self._try_pair(channel_id, message, nonce)

    async def _handle_callback_query(self, channel_id: str, callback: dict) -> None:
        """Dispatch an inline-button press.

        Always answers the callback within the 15s Telegram window so
        the user's spinner clears, even if internal DB work fails.
        Returns silently on any verification or ownership failure; the
        user sees a generic "expired" alert in those cases.

        Concurrency. when two users press Ack on a forwarded message,
        the second press finds ``acked_at`` already set and answers
        with "Already acknowledged by <name>" without overwriting the
        first. mute_event + snooze_rule are last-writer-wins by
        design; the user intent is "extend the silence", not "reserve
        the first slot".
        """
        cb_id = str(callback.get("id") or "")
        if not cb_id:
            return
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")

        # Load the bot token + verify the inbound chat matches the
        # channel binding. A leaked button replayed in a different
        # chat (e.g. user forwarded the message to a public group) is
        # rejected here even before HMAC verification.
        async with async_session() as db:
            ch = await db.get(TelegramChannel, _to_uuid(channel_id))
            if ch is None or not ch.bot_token_enc:
                return
            if ch.chat_id and chat_id is not None and str(chat_id) != str(ch.chat_id):
                logger.warning(
                    "telegram callback rejected. channel=%s chat mismatch (%s vs %s)",
                    channel_id, chat_id, ch.chat_id,
                )
                try:
                    token_only = decrypt_secret(ch.bot_token_enc)
                    await _safe_answer(
                        token_only, cb_id,
                        text="This alert is not bound to this chat.",
                        show_alert=True,
                    )
                except InvalidToken:
                    pass
                return
            try:
                token = decrypt_secret(ch.bot_token_enc)
            except InvalidToken:
                return
            owner_user_id = ch.user_id

        payload_str = verify_callback(data)
        if not payload_str:
            await _safe_answer(
                token, cb_id,
                text="This alert is no longer valid. Open Nurby on the web to acknowledge.",
                show_alert=True,
            )
            return
        try:
            payload = json.loads(payload_str)
        except Exception:
            await _safe_answer(token, cb_id, text="Malformed alert payload.", show_alert=True)
            return

        action = str(payload.get("a") or "")
        if action not in _CALLBACK_ACTIONS:
            await _safe_answer(token, cb_id, text="Unknown action.", show_alert=True)
            return

        if action == "open":
            # open is delivered as a URL button by the action executor
            # so reaching the callback path means a stale button or a
            # client that downgraded the URL. No state change.
            await _safe_answer(token, cb_id, text="Opening Nurby…")
            return

        event_id_raw = payload.get("e")
        rule_id_raw = payload.get("r")
        try:
            event_id = _to_uuid(event_id_raw) if event_id_raw else None
        except Exception:
            event_id = None
        try:
            rule_id = _to_uuid(rule_id_raw) if rule_id_raw else None
        except Exception:
            rule_id = None
        duration = int(payload.get("d") or 0)

        # Hand off to the per-action branch. Each branch is wrapped in
        # try/except so we still answerCallbackQuery on errors.
        text_reply: str | None = None
        show_alert = False
        new_markup: dict | None = None
        try:
            if action == "ack":
                text_reply, new_markup = await self._do_ack(event_id, owner_user_id)
            elif action == "mute_event":
                text_reply, new_markup = await self._do_mute_event(event_id, duration or 600)
            elif action == "snooze_rule":
                text_reply, new_markup = await self._do_snooze_rule(rule_id, duration or 3600)
        except Exception:
            logger.exception("telegram callback handler failed channel=%s action=%s", channel_id, action)
            text_reply = "Could not update Nurby. Try again from the web UI."
            show_alert = True

        # Step 1. Clear the spinner first (must be within 15s).
        await _safe_answer(token, cb_id, text=text_reply, show_alert=show_alert)

        # Step 2. Best-effort markup rewrite so the buttons reflect
        # the new state. Missing message_id (e.g. send failed earlier)
        # silently skips this step.
        if new_markup is not None and chat_id is not None and message_id is not None:
            try:
                await TelegramAPI.edit_message_reply_markup(
                    token, chat_id, int(message_id), new_markup,
                )
            except TelegramError as exc:
                logger.debug(
                    "telegram editMessageReplyMarkup failed channel=%s. %s",
                    channel_id, exc.description,
                )
            except Exception:
                logger.debug(
                    "telegram editMessageReplyMarkup raised channel=%s", channel_id, exc_info=True,
                )

    async def _do_ack(self, event_id, owner_user_id) -> tuple[str, dict]:
        """Set the ack triad on the event. If already acked, reply with
        the prior acker's name instead of overwriting (second-presser
        gets feedback)."""
        if event_id is None:
            return ("This alert is missing an event id.", _markup_disabled("⚠ Invalid"))
        async with async_session() as db:
            event = await db.get(Event, event_id)
            if event is None:
                return ("Event no longer exists.", _markup_disabled("⚠ Gone"))
            if event.acked_at is not None:
                prior_name = await _user_display(db, event.acked_by_user_id)
                return (
                    f"Already acknowledged by {prior_name}.",
                    _markup_disabled(f"✓ Acknowledged by {prior_name}"),
                )
            event.acked_at = datetime.now(timezone.utc)
            event.acked_by_user_id = owner_user_id
            event.acked_via = "telegram"
            # Mirror to the legacy column so existing dashboards keep
            # showing the acknowledgement.
            event.acknowledged_at = event.acked_at
            await db.commit()
            ack_name = await _user_display(db, owner_user_id)
        return (
            f"Acknowledged by {ack_name}.",
            _markup_disabled(f"✓ Acknowledged by {ack_name}"),
        )

    async def _do_mute_event(self, event_id, duration_seconds: int) -> tuple[str, dict]:
        if event_id is None:
            return ("This alert is missing an event id.", _markup_disabled("⚠ Invalid"))
        until = datetime.now(timezone.utc) + _timedelta_seconds(duration_seconds)
        async with async_session() as db:
            event = await db.get(Event, event_id)
            if event is None:
                return ("Event no longer exists.", _markup_disabled("⚠ Gone"))
            event.muted_until = until
            await db.commit()
        when = until.astimezone().strftime("%H:%M")
        return (f"Muted until {when}.", _markup_disabled(f"🔕 Muted until {when}"))

    async def _do_snooze_rule(self, rule_id, duration_seconds: int) -> tuple[str, dict]:
        if rule_id is None:
            return ("This alert is missing a rule id.", _markup_disabled("⚠ Invalid"))
        until = datetime.now(timezone.utc) + _timedelta_seconds(duration_seconds)
        async with async_session() as db:
            rule = await db.get(Rule, rule_id)
            if rule is None:
                return ("Rule no longer exists.", _markup_disabled("⚠ Gone"))
            rule.snoozed_until = until
            await db.commit()
        when = until.astimezone().strftime("%H:%M")
        return (
            f"Rule snoozed until {when}.",
            _markup_disabled(f"💤 Rule snoozed until {when}"),
        )

    async def _try_pair(self, channel_id: str, message: dict, nonce: str) -> None:
        redis = await self._redis_client()
        try:
            bound_channel = await redis.get(pair_key(nonce))
        except Exception:
            bound_channel = None
        if not bound_channel:
            logger.info("telegram pair nonce=%s expired or unknown", nonce[:8])
            return
        if bound_channel != channel_id:
            logger.warning(
                "telegram pair nonce=%s issued for channel=%s but received on channel=%s",
                nonce[:8], bound_channel, channel_id,
            )
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        chat_title = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
        chat_type = chat.get("type") or "private"

        async with async_session() as db:
            ch = await db.get(TelegramChannel, _to_uuid(channel_id))
            if ch is None:
                return
            ch.chat_id = str(chat_id)
            ch.chat_title = str(chat_title)[:255] if chat_title else None
            ch.chat_type = str(chat_type)[:16]
            ch.paired_at = datetime.now(timezone.utc)
            ch.last_error = None
            await db.commit()
            try:
                token = decrypt_secret(ch.bot_token_enc)
            except InvalidToken:
                token = None

        try:
            await redis.delete(pair_key(nonce))
        except Exception:
            pass

        if token:
            try:
                await TelegramAPI.send_message(
                    token,
                    chat_id,
                    "Paired with Nurby ✓\nThis chat will receive alerts from rules using this channel.",
                )
            except TelegramError as exc:
                logger.warning("telegram pair confirm failed channel=%s. %s", channel_id, exc)

        logger.info("telegram channel=%s paired with chat=%s (%s)", channel_id, chat_id, chat_type)


def _to_uuid(value):
    """Best-effort coerce a string id from Redis/handler payloads to a UUID."""
    import uuid

    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# Convenience helper used by routes when issuing a fresh pair nonce.
async def store_pair_nonce(redis: aioredis.Redis, nonce: str, channel_id: str, ttl: int = 300) -> None:
    await redis.set(pair_key(nonce), channel_id, ex=ttl)


# Convenience helper. JSON-safe lookup used by tests.
def encode_for_test(update: dict) -> str:  # pragma: no cover. trivial
    return json.dumps(update)


def _timedelta_seconds(seconds: int):
    from datetime import timedelta
    # Clamp to a sane window. 1 minute to 24 hours. Anything outside
    # is treated as a bad client and snapped to the default 10 min.
    if seconds < 60 or seconds > 24 * 3600:
        seconds = 600
    return timedelta(seconds=seconds)


def _markup_disabled(label: str) -> dict:
    """Build a one-button inline keyboard with a dead callback_data.
    Telegram requires *some* callback_data on each button; we use a
    constant string that the verify path rejects, so a future press
    triggers the generic "no longer valid" message instead of a stale
    handler."""
    return {"inline_keyboard": [[{"text": label, "callback_data": "__noop__"}]]}


async def _user_display(db, user_id) -> str:
    if user_id is None:
        return "someone"
    try:
        user = await db.get(User, user_id)
    except Exception:
        user = None
    if user is None:
        return "someone"
    return user.display_name or user.email or "someone"


# ── Phase 3. module-level handle_update for the webhook route ──
#
# The webhook receiver in services/api/routes/telegram.py needs to
# dispatch updates through the exact same code path as the long-poll
# worker. We expose a module-level singleton manager + thin shim so
# the receiver doesn't have to care about manager construction.
#
# Phase 4 will add new branches inside _handle_update (text-reply
# handling for note-taking, face-cluster naming). Those will be
# reachable from BOTH the poll worker AND the webhook route without
# touching this shim.

_singleton_manager: TelegramPollerManager | None = None


def _get_singleton_manager() -> TelegramPollerManager:
    global _singleton_manager
    if _singleton_manager is None:
        _singleton_manager = TelegramPollerManager()
    return _singleton_manager


async def handle_update(channel_id: str, update: dict) -> None:
    """Dispatch a single Telegram Update through the same handler set
    as the long-poll worker. Safe to call concurrently for the same
    or different channels."""
    await _get_singleton_manager().handle_update(channel_id, update)


async def _safe_answer(token: str, cb_id: str, text: str | None = None, show_alert: bool = False) -> None:
    """Wrap :meth:`TelegramAPI.answer_callback_query` so any failure is
    swallowed. We must always try to clear the spinner, but a failure
    here must not crash the worker.
    """
    try:
        await TelegramAPI.answer_callback_query(token, cb_id, text=text, show_alert=show_alert)
    except TelegramError as exc:
        logger.debug("telegram answerCallbackQuery error. %s", exc)
    except Exception:
        logger.debug("telegram answerCallbackQuery raised", exc_info=True)
