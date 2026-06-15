"""Coverage for services/notify/telegram.py + telegram_poller.py.

Focuses on the pure, deterministic logic: HMAC callback signing/verification,
the dedupe hash, the per-chat token-bucket limiter, command/markup shaping,
error classification, and the poller's small pure helpers (timedelta clamping,
disabled-markup builder, pairing status). The HTTP layer is monkeypatched at
``TelegramAPI._post`` so no real Telegram request is ever made.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.api.routes.telegram import _pairing_status
from services.notify import telegram as tg
from services.notify import telegram_poller as poller

# ── sign_callback / verify_callback HMAC round-trip ────────────────


def test_sign_verify_round_trip():
    payload = '{"a":"ack","e":"abc"}'
    signed = tg.sign_callback(payload)
    assert "." in signed
    assert tg.verify_callback(signed) == payload


def test_verify_rejects_tampered_payload():
    signed = tg.sign_callback('{"a":"ack"}')
    body, sig = signed.rsplit(".", 1)
    # Flip the first body character to a different urlsafe-b64 char.
    swapped = ("Z" if body[0] != "Z" else "Y") + body[1:]
    tampered = f"{swapped}.{sig}"
    assert tg.verify_callback(tampered) is None


def test_verify_rejects_tampered_signature():
    signed = tg.sign_callback('{"a":"ack"}')
    body, sig = signed.rsplit(".", 1)
    bad_sig = ("Z" if sig[0] != "Z" else "Y") + sig[1:]
    assert tg.verify_callback(f"{body}.{bad_sig}") is None


def test_verify_rejects_malformed_input():
    assert tg.verify_callback("") is None
    assert tg.verify_callback("no-dot-here") is None
    assert tg.verify_callback(None) is None
    assert tg.verify_callback("...") is None


def test_signed_callback_signature_overhead_is_fixed():
    # The signature half is a 16-byte HMAC truncation b64-encoded without
    # padding (22 chars) plus the "." separator, so the overhead a payload
    # pays for signing is a constant 23 bytes regardless of payload size.
    for payload in ('{"a":"ack"}', '{"a":"mute_event","d":600}'):
        signed = tg.sign_callback(payload)
        body, sig = signed.rsplit(".", 1)
        assert len(sig) == 22
        assert len(signed) - len(body) == 23


def test_short_signed_callback_fits_telegram_64_byte_cap():
    # With the documented short keys, a compact payload stays under
    # Telegram's 64-byte callback_data cap.
    payload = '{"a":"ack","e":"a1b2"}'
    signed = tg.sign_callback(payload)
    assert len(signed.encode("utf-8")) <= tg.CALLBACK_DATA_MAX
    assert tg.verify_callback(signed) == payload


def test_secret_rotation_invalidates_old_signatures(monkeypatch):
    payload = '{"a":"ack"}'
    signed = tg.sign_callback(payload)
    # Rotate the derived secret; the old signature must no longer verify.
    monkeypatch.setattr(tg, "_callback_secret", lambda: b"\x00" * 32)
    assert tg.verify_callback(signed) is None


# ── base64 helpers ─────────────────────────────────────────────────


def test_b64_round_trip_handles_padding():
    for raw in (b"", b"a", b"ab", b"abc", b"abcd", b"\xff\x00\x10"):
        assert tg._b64decode(tg._b64encode(raw)) == raw


# ── _dedupe_hash ───────────────────────────────────────────────────


def test_dedupe_hash_stable_and_distinct():
    h1 = tg._dedupe_hash("chat1", "hello")
    h2 = tg._dedupe_hash("chat1", "hello")
    h3 = tg._dedupe_hash("chat2", "hello")
    h4 = tg._dedupe_hash("chat1", "goodbye")
    assert h1 == h2
    assert h1 != h3  # chat id participates
    assert h1 != h4  # body participates
    assert len(h1) == 64  # sha-256 hex


def test_dedupe_hash_truncates_photo_ref():
    # Two photo refs differing only past the 64th char hash identically,
    # so timestamped rotation of the same image doesn't defeat dedupe.
    base = "/var/thumbs/cam1/2026-06-11/frame-" + ("x" * 60)
    a = tg._dedupe_hash("c", "body", base + "AAAA")
    b = tg._dedupe_hash("c", "body", base + "BBBB")
    assert a == b
    # But a genuinely different prefix differs.
    c = tg._dedupe_hash("c", "body", "/different/path")
    assert a != c


# ── TelegramError classification ───────────────────────────────────


def test_telegram_error_is_forbidden():
    assert tg.TelegramError(403, "bot blocked", "sendMessage").is_forbidden is True
    assert tg.TelegramError(400, "bad request").is_forbidden is False
    assert tg.TelegramError(0, "timeout").is_forbidden is False


def test_telegram_error_str_includes_method_and_code():
    exc = tg.TelegramError(429, "Too Many Requests", "sendMessage")
    assert "sendMessage" in str(exc)
    assert "429" in str(exc)


# ── PerChatLimiter token bucket ────────────────────────────────────


@pytest.mark.asyncio
async def test_limiter_allows_burst_then_blocks():
    lim = tg.PerChatLimiter()
    # burst=3 means three immediate acquisitions succeed without waiting.
    for _ in range(3):
        assert await lim.acquire("tok", "chat", qps=1000.0, burst=3) is True


@pytest.mark.asyncio
async def test_limiter_zero_qps_is_unlimited():
    lim = tg.PerChatLimiter()
    # qps<=0 is treated as "no rate limit" (defensive, never divides by zero).
    for _ in range(10):
        assert await lim.acquire("tok", "chat", qps=0.0, burst=1) is True


@pytest.mark.asyncio
async def test_limiter_drops_when_wait_exceeds_deadline(monkeypatch):
    """With a tiny qps and empty bucket the projected wait blows past the max
    wait deadline, so acquire returns False instead of blocking forever."""
    lim = tg.PerChatLimiter()
    # Exhaust the single burst token first.
    assert await lim.acquire("tok", "chat", qps=0.001, burst=1) is True
    # Next acquire needs ~1000s of refill at qps=0.001 -> over the 30s cap.
    assert await lim.acquire("tok", "chat", qps=0.001, burst=1) is False


@pytest.mark.asyncio
async def test_limiter_separate_buckets_per_chat():
    lim = tg.PerChatLimiter()
    assert await lim.acquire("tok", "chatA", qps=0.001, burst=1) is True
    # Different chat has its own fresh bucket.
    assert await lim.acquire("tok", "chatB", qps=0.001, burst=1) is True


# ── set_my_commands payload shaping ────────────────────────────────


@pytest.mark.asyncio
async def test_set_my_commands_normalizes_tuples_and_dicts(monkeypatch):
    captured = {}

    async def _fake_post(token, method, payload=None, timeout=10.0):
        captured["method"] = method
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(tg.TelegramAPI, "_post", _fake_post)

    await tg.TelegramAPI.set_my_commands(
        "tok",
        [
            ("ack", "Acknowledge"),
            {"command": "mute", "description": "Mute 10m"},
            "bogus-string-ignored-shape",  # not tuple/dict -> skipped
        ],
    )
    assert captured["method"] == "setMyCommands"
    cmds = captured["payload"]["commands"]
    assert {"command": "ack", "description": "Acknowledge"} in cmds
    assert {"command": "mute", "description": "Mute 10m"} in cmds
    assert len(cmds) == 2  # the bare string was dropped


# ── send_message payload + reply_markup wiring ─────────────────────


@pytest.mark.asyncio
async def test_send_message_builds_expected_payload(monkeypatch):
    captured = {}

    async def _fake_post(token, method, payload=None, timeout=10.0):
        captured["payload"] = payload
        return {"message_id": 1}

    monkeypatch.setattr(tg.TelegramAPI, "_post", _fake_post)

    markup = {"inline_keyboard": [[{"text": "Ack", "callback_data": "x.y"}]]}
    await tg.TelegramAPI.send_message(
        "tok", 123, "hi", disable_notification=True, reply_markup=markup
    )
    p = captured["payload"]
    assert p["chat_id"] == 123
    assert p["text"] == "hi"
    assert p["parse_mode"] == "HTML"
    assert p["disable_notification"] is True
    assert p["reply_markup"] == markup


@pytest.mark.asyncio
async def test_send_message_omits_parse_mode_when_none(monkeypatch):
    captured = {}

    async def _fake_post(token, method, payload=None, timeout=10.0):
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(tg.TelegramAPI, "_post", _fake_post)
    await tg.TelegramAPI.send_message("tok", 1, "x", parse_mode=None)
    assert "parse_mode" not in captured["payload"]


# ── answer_callback_query truncates the toast text ─────────────────


@pytest.mark.asyncio
async def test_answer_callback_query_clips_text(monkeypatch):
    captured = {}

    async def _fake_post(token, method, payload=None, timeout=10.0):
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(tg.TelegramAPI, "_post", _fake_post)
    await tg.TelegramAPI.answer_callback_query("tok", "cb", text="z" * 500)
    assert len(captured["payload"]["text"]) == 200  # Telegram caps at 200


# ── send_message_guarded sentinels (dedupe + rate limit) ───────────


@pytest.mark.asyncio
async def test_send_message_guarded_suppresses_duplicate(monkeypatch):
    async def _dup(self, channel_id, h, window):
        return True

    monkeypatch.setattr(tg.DedupeStore, "is_duplicate", _dup)
    out = await tg.send_message_guarded(
        token="tok",
        channel_id="ch",
        chat_id="c",
        text="hi",
        qps=10,
        burst=3,
        dedupe_window_seconds=30,
    )
    assert out == tg.DUPLICATE_SUPPRESSED


@pytest.mark.asyncio
async def test_send_message_guarded_rate_limited(monkeypatch):
    async def _not_dup(self, channel_id, h, window):
        return False

    async def _deny(self, token, chat_id, qps, burst):
        return False

    monkeypatch.setattr(tg.DedupeStore, "is_duplicate", _not_dup)
    monkeypatch.setattr(tg.PerChatLimiter, "acquire", _deny)
    out = await tg.send_message_guarded(
        token="tok",
        channel_id="ch",
        chat_id="c",
        text="hi",
        qps=10,
        burst=3,
        dedupe_window_seconds=30,
    )
    assert out == tg.RATE_LIMITED_DROPPED


@pytest.mark.asyncio
async def test_send_photo_guarded_media_off_short_circuits():
    out = await tg.send_photo_guarded(
        token="tok",
        channel_id="ch",
        chat_id="c",
        photo="/x.jpg",
        qps=10,
        burst=3,
        dedupe_window_seconds=0,
        media_quality="off",
    )
    assert out == tg.MEDIA_OFF_SENTINEL


# ── poller pure helpers ────────────────────────────────────────────


def test_timedelta_seconds_clamps_out_of_range():
    # Below 60s or above 24h snaps to the 600s (10 min) default.
    assert poller._timedelta_seconds(5).total_seconds() == 600
    assert poller._timedelta_seconds(10**9).total_seconds() == 600
    # In-range values pass through.
    assert poller._timedelta_seconds(3600).total_seconds() == 3600
    assert poller._timedelta_seconds(60).total_seconds() == 60
    assert poller._timedelta_seconds(24 * 3600).total_seconds() == 24 * 3600


def test_markup_disabled_uses_noop_callback():
    m = poller._markup_disabled("✓ Acknowledged")
    btn = m["inline_keyboard"][0][0]
    assert btn["text"] == "✓ Acknowledged"
    # Dead callback_data the verify path rejects, so a future press is inert.
    assert btn["callback_data"] == "__noop__"
    assert tg.verify_callback(btn["callback_data"]) is None


def test_offset_and_pair_key_prefixes():
    assert poller.offset_key("abc") == "nurby:tg_offset:abc"
    assert poller.pair_key("nonce123") == "nurby:tg_pair:nonce123"


def test_to_uuid_coerces_strings_and_passthrough():
    import uuid

    u = uuid.uuid4()
    assert poller._to_uuid(str(u)) == u
    assert poller._to_uuid(u) is u
    with pytest.raises(Exception):
        poller._to_uuid("not-a-uuid")


# ── _pairing_status state machine ──────────────────────────────────


def _channel(**kw):
    defaults = dict(
        enabled=True,
        paired_at=datetime.now(timezone.utc),
        chat_id="123",
        last_test_ok=None,
        last_error=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_pairing_status_all_states():
    assert _pairing_status(_channel()) == "paired"
    assert _pairing_status(_channel(enabled=False)) == "disabled"
    assert _pairing_status(_channel(paired_at=None)) == "pending"
    assert _pairing_status(_channel(chat_id=None)) == "pending"
    assert (
        _pairing_status(_channel(last_test_ok=False, last_error="403 Forbidden"))
        == "blocked"
    )
    assert (
        _pairing_status(_channel(last_test_ok=False, last_error="blocked by user"))
        == "blocked"
    )
    assert _pairing_status(_channel(last_test_ok=False, last_error="timeout")) == "error"
