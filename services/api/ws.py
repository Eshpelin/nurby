import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from shared.auth import decode_access_token
from shared.camera_access import ALL, AllowedCameras, allowed_camera_ids
from shared.database import async_session
from shared.models import User

logger = logging.getLogger("nurby.api.ws")

router = APIRouter()

# In-memory registry of connected clients, each mapped to the per-user
# camera ACL resolved at connect time (issue #40). The value is either the
# ``ALL`` sentinel (admin / zero-grant user, sees everything) or a concrete
# ``set[UUID]`` allowlist. ``_deliver_local`` consults this to drop
# camera-specific messages a given recipient may not see.
_connections: dict[WebSocket, AllowedCameras] = {}


def _coerce_camera_id(raw) -> uuid.UUID | None:
    """Best-effort parse of a broadcast payload's ``camera_id`` into a UUID.

    Broadcasts carry ``camera_id`` as a string most of the time, but some
    call sites pass a raw UUID or ``None`` (system-wide notices). Returns
    ``None`` when there is no usable camera id, which the caller treats as
    "deliver to everyone"."""
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _allowed_to_receive(allowed: AllowedCameras, message: dict) -> bool:
    """Per-recipient fan-out gate for one socket and one decoded message.

    Always deliver when the recipient is unrestricted (``ALL``), or when the
    message is not camera-specific (no usable top-level ``camera_id``, e.g.
    a system notice). Otherwise deliver only when the message's camera is in
    the recipient's allowlist. An empty allowlist therefore drops every
    camera-tagged message (fail-closed)."""
    if allowed is ALL:
        return True
    if not isinstance(message, dict):
        return True
    camera_id = _coerce_camera_id(message.get("camera_id"))
    if camera_id is None:
        return True
    return camera_id in allowed

# ── Cross-process relay ─────────────────────────────────────────────
#
# Browsers hold their WebSocket against the API process, but most live
# pushes originate elsewhere: vlm_status and incidents in perception,
# person_actions in ingestion, notify actions in whichever process runs
# the rule engine. A process-local connection set silently no-ops for
# all of those under Docker, which is exactly the "dashboard is static"
# experience. broadcast() therefore also publishes every message to a
# Redis channel, and the API process runs relay_loop() to fan messages
# from other processes out to its local browsers. The src token stops
# the API process re-delivering its own messages.

WS_RELAY_CHANNEL = "nurby:ws:broadcast"
_PROCESS_SRC = uuid.uuid4().hex
_relay_redis = None


async def _get_relay_redis():
    global _relay_redis
    if _relay_redis is None:
        import redis.asyncio as aioredis

        from shared.config import settings

        _relay_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _relay_redis


async def _deliver_local(payload: str) -> None:
    # Decode once so each socket's ACL can be checked against the message's
    # camera_id without re-parsing. A non-JSON / non-dict payload is treated
    # as a system message and delivered to everyone (the gate is a no-op for
    # it). The cross-process relay reinjects here, so relayed messages are
    # scoped automatically.
    try:
        message = json.loads(payload)
    except (TypeError, ValueError):
        message = None
    dead = set()
    for ws, allowed in list(_connections.items()):
        if message is not None and not _allowed_to_receive(allowed, message):
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connections.pop(ws, None)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    """Live dashboard fan-out socket.

    Token-authenticated (issue #40): the JWT rides as ``?token=`` exactly
    like the mic socket, since browsers cannot set an Authorization header
    on a WebSocket handshake. The per-user camera ACL is resolved once at
    connect time and cached alongside the socket; ``_deliver_local`` then
    drops camera-tagged messages this recipient may not see.
    """
    user_id = decode_access_token(token)
    if user_id is None:
        await ws.close(code=4401)
        return
    # Resolve the user and their allowed-camera set once, before accepting,
    # so an invalid/deactivated user is rejected and the ACL is fixed for
    # the life of the connection.
    async with async_session() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            await ws.close(code=4401)
            return
        allowed = await allowed_camera_ids(user, db)

    await ws.accept()
    _connections[ws] = allowed
    try:
        while True:
            # Keep connection alive, handle incoming messages if needed
            data = await ws.receive_text()
            # Echo back for now, will be replaced with proper message handling
            await ws.send_text(json.dumps({"type": "ack", "data": data}))
    except WebSocketDisconnect:
        _connections.pop(ws, None)
    finally:
        _connections.pop(ws, None)


async def broadcast(message: dict):
    """Broadcast a message to every connected browser, in every process.

    Delivers to this process's own connections, then publishes to the
    Redis relay channel so the API process forwards it to browsers when
    the caller lives in another container. Redis being down degrades to
    local-only delivery, never an exception for the caller.
    """
    payload = json.dumps(message, default=str)
    await _deliver_local(payload)
    try:
        r = await _get_relay_redis()
        await r.publish(
            WS_RELAY_CHANNEL,
            json.dumps({"src": _PROCESS_SRC, "msg": message}, default=str),
        )
    except Exception:
        logger.debug("ws relay publish failed", exc_info=True)


def relay_envelope_payload(raw: str, own_src: str = _PROCESS_SRC) -> str | None:
    """Decode a relay envelope. Returns the JSON payload to deliver to
    local connections, or None when the message originated here (already
    delivered) or is malformed. Pure, for tests."""
    try:
        env = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(env, dict) or env.get("src") == own_src:
        return None
    msg = env.get("msg")
    if not isinstance(msg, dict):
        return None
    return json.dumps(msg, default=str)


async def relay_loop(stop_event: asyncio.Event | None = None) -> None:
    """Run in the API process: forward other processes' broadcasts to the
    browsers connected here. Reconnects on Redis hiccups."""
    while stop_event is None or not stop_event.is_set():
        try:
            r = await _get_relay_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(WS_RELAY_CHANNEL)
            logger.info("WS relay listening on %s", WS_RELAY_CHANNEL)
            while stop_event is None or not stop_event.is_set():
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                payload = relay_envelope_payload(msg.get("data"))
                if payload is not None:
                    await _deliver_local(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            global _relay_redis
            _relay_redis = None
            logger.exception("ws relay loop error; reconnecting in 5s")
            await asyncio.sleep(5)


async def broadcast_person_actions(
    camera_id, people: list[dict], width: int | None = None, height: int | None = None
):
    """Push current per-person actions for a camera (HAR live overlay).

    ``people`` is a list of ``{track_id, person_id?, person_name?, action, confidence}``.
    The HAR ingestion runner calls this on each sampled update. Clients subscribe with
    ``useWSSubscribe("person_actions", handler, cameraId)`` and filter by camera, matching
    the existing transcript_created / vlm_status pattern (single global socket, client-side
    camera filter). Identity is already gated upstream: only person-state tracks carry a
    name; unknown/body tracks are sent without identity or omitted by the runner for
    guardian-facing cameras."""
    await broadcast(
        {
            "type": "person_actions",
            "camera_id": str(camera_id),
            "people": people or [],
            "width": width,
            "height": height,
        }
    )


# ── Phone-as-mic ────────────────────────────────────────────────────────

# Live browser-mic sessions. one per audio_only camera. Each session
# owns an ffmpeg subprocess that decodes incoming webm/opus chunks
# into a TCP RTSP-like stream that the AudioWorker can av.open().
_mic_sessions: dict[str, "_MicSession"] = {}


class _MicSession:
    """Bridges a browser MediaRecorder stream into a TCP listener that
    the existing AudioWorker can consume.

    Browser publishes opus chunks (webm container) via WebSocket. The
    session writes those bytes to ffmpeg stdin. ffmpeg muxes the
    chunks into a continuous RTP/MPEG-TS stream and serves it over
    TCP on 127.0.0.1:<port>. The camera row's ``stream_url`` is
    expected to be ``tcp://127.0.0.1:<port>`` so the AudioWorker
    pulls from this session.

    The port is derived deterministically from the camera id so a
    reconnect after a tab refresh always hits the same listener.
    """

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.port = _port_for_camera(camera_id)
        self.process: asyncio.subprocess.Process | None = None
        self._stdin_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.process is not None and self.process.returncode is None:
            return
        # webm/opus in on stdin, mpegts mux out to a TCP listen socket.
        # AudioWorker av.open("tcp://127.0.0.1:<port>?listen=0") connects
        # to this. listen=1 on ffmpeg makes it the server.
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts",
            "-i", "pipe:0",
            "-acodec", "libopus", "-b:a", "32k",
            "-f", "mpegts",
            f"tcp://127.0.0.1:{self.port}?listen=1",
        ]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(
                "mic session ffmpeg up camera=%s port=%d pid=%s",
                self.camera_id, self.port, getattr(self.process, "pid", "?"),
            )
        except FileNotFoundError:
            logger.error("ffmpeg not on PATH. browser-mic disabled.")
            self.process = None

    async def write(self, data: bytes) -> bool:
        if self.process is None or self.process.stdin is None:
            return False
        if self.process.returncode is not None:
            return False
        async with self._stdin_lock:
            try:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False
            except Exception:
                logger.exception("mic write failed camera=%s", self.camera_id)
                return False

    async def stop(self) -> None:
        proc = self.process
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
        self.process = None


def _port_for_camera(camera_id: str) -> int:
    """Deterministic local port in 19000-19999 derived from camera id.
    Avoids collisions with common service ports."""
    h = uuid.UUID(camera_id).int
    return 19000 + (h % 1000)


def mic_stream_url(camera_id: uuid.UUID) -> str:
    """Public helper. cameras that use browser-mic publishing point
    their ``stream_url`` at this. The ingestion AudioWorker av.opens
    the TCP listener.
    """
    return f"tcp://127.0.0.1:{_port_for_camera(str(camera_id))}"


@router.websocket("/ws/mic/{camera_id}")
async def mic_websocket(
    ws: WebSocket,
    camera_id: str,
    token: str = Query(...),
):
    """Browser-mic publisher endpoint.

    Phone visits ``/mic/{camera_id}``, the page captures audio with
    MediaRecorder (webm/opus), and posts each chunk as a binary
    frame here. The session writes them to ffmpeg which serves the
    decoded audio on the deterministic camera-mic TCP port. The
    existing AudioWorker for an audio_only camera with stream_url
    set to that tcp:// URL pulls from there.
    """
    if not decode_access_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    session = _mic_sessions.get(camera_id)
    if session is None:
        session = _MicSession(camera_id)
        _mic_sessions[camera_id] = session
    await session.start()
    if session.process is None:
        await ws.send_text(json.dumps({"type": "error", "message": "ffmpeg missing"}))
        await ws.close(code=4500)
        return
    await ws.send_text(json.dumps({"type": "ready", "port": session.port}))
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue
            ok = await session.write(data)
            if not ok:
                await ws.send_text(
                    json.dumps({"type": "error", "message": "encoder closed"})
                )
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("mic ws error camera=%s", camera_id)
    finally:
        # Keep the ffmpeg session alive on disconnect. The next browser
        # reconnect will rejoin the same TCP listener so the audio
        # worker never sees a gap.
        try:
            await ws.close()
        except Exception:
            pass
