"""System doctor: one endpoint that answers "why isn't this working?".

Runs every check concurrently with a per-check timeout and returns
structured verdicts with actionable hints, instead of making the user
piece the same picture together from docker logs.
"""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.camera_probe import ERROR_HINTS, parse_target, probe_tcp
from shared.auth import require_admin
from shared.config import settings
from shared.database import get_db
from shared.models import Camera, Provider, User

logger = logging.getLogger("nurby.api.doctor")

router = APIRouter()

_CHECK_TIMEOUT = 8.0
_CAMERA_CONCURRENCY = 4
# Stream types that have no network endpoint to probe.
_UNPROBEABLE_TYPES = {"file", "usb", "webcam", "browser_mic"}


class DoctorCheck(BaseModel):
    id: str
    label: str
    status: str  # ok | warn | fail | skip
    detail: str
    hint: str | None = None
    latency_ms: int | None = None


def _timed(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


async def _check_db(db: AsyncSession) -> DoctorCheck:
    start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        return DoctorCheck(
            id="db", label="Database", status="ok", detail="Postgres answered",
            latency_ms=_timed(start),
        )
    except Exception as exc:
        return DoctorCheck(
            id="db", label="Database", status="fail", detail=str(exc)[:200],
            hint="Check the postgres container: docker compose logs postgres",
            latency_ms=_timed(start),
        )


async def _check_redis() -> DoctorCheck:
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return DoctorCheck(
            id="redis", label="Redis", status="ok", detail="Redis answered",
            latency_ms=_timed(start),
        )
    except Exception as exc:
        return DoctorCheck(
            id="redis", label="Redis", status="fail", detail=str(exc)[:200],
            hint=(
                "Rule cooldowns degrade to per-process memory and live updates "
                "stop relaying. Check the redis container: docker compose logs redis"
            ),
            latency_ms=_timed(start),
        )


async def _check_mediamtx() -> DoctorCheck:
    start = time.monotonic()
    url = settings.mediamtx_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/v3/paths/list")
        if resp.status_code == 200:
            return DoctorCheck(
                id="mediamtx", label="Stream relay (mediamtx)", status="ok",
                detail="mediamtx API answered", latency_ms=_timed(start),
            )
        return DoctorCheck(
            id="mediamtx", label="Stream relay (mediamtx)", status="warn",
            detail=f"mediamtx returned {resp.status_code}",
            hint="Live view (WebRTC/HLS) may be down. Recording still works.",
            latency_ms=_timed(start),
        )
    except Exception as exc:
        return DoctorCheck(
            id="mediamtx", label="Stream relay (mediamtx)", status="fail",
            detail=str(exc)[:200],
            hint=(
                "Live view is down; recording to disk still works. "
                "Check: docker compose logs mediamtx"
            ),
            latency_ms=_timed(start),
        )


async def _check_camera(camera, sem: asyncio.Semaphore) -> DoctorCheck:
    cid = f"camera:{camera.id}"
    label = f"Camera: {camera.name}"
    if camera.stream_type in _UNPROBEABLE_TYPES:
        return DoctorCheck(
            id=cid, label=label, status="skip",
            detail=f"{camera.stream_type} source has no network endpoint to probe",
        )
    host, port = parse_target(camera.stream_url or "")
    if not host:
        return DoctorCheck(
            id=cid, label=label, status="fail", detail="Stream URL has no hostname",
            hint="Edit the camera and fix the stream URL.",
        )
    start = time.monotonic()
    async with sem:
        result = await asyncio.to_thread(probe_tcp, host, port, 4.0)
    if result.get("ok"):
        return DoctorCheck(
            id=cid, label=label, status="ok", detail=f"{host}:{port} reachable",
            latency_ms=_timed(start),
        )
    code = result.get("error_code", "unknown")
    return DoctorCheck(
        id=cid, label=label, status="fail",
        detail=result.get("detail") or "Unreachable",
        hint=ERROR_HINTS.get(code),
        latency_ms=_timed(start),
    )


async def _check_provider(provider) -> DoctorCheck:
    from services.api.routes.providers import run_provider_test

    cid = f"provider:{provider.id}"
    label = f"AI provider: {provider.name}"
    start = time.monotonic()
    result = await run_provider_test(provider)
    return DoctorCheck(
        id=cid, label=label, status="ok" if result.ok else "fail",
        detail=result.message,
        hint=None if result.ok else "Open Settings → AI Providers to fix or re-test.",
        latency_ms=result.latency_ms if result.latency_ms is not None else _timed(start),
    )


async def _check_smtp() -> DoctorCheck:
    from shared.email import resolve_smtp

    cfg = await resolve_smtp()
    if cfg.get("host") and cfg.get("from_addr"):
        return DoctorCheck(
            id="smtp", label="Email (SMTP)", status="ok",
            detail=f"Configured via {cfg['host']}",
        )
    if cfg.get("host") or cfg.get("user") or cfg.get("from_addr"):
        return DoctorCheck(
            id="smtp", label="Email (SMTP)", status="warn",
            detail="Partially configured. sends will fail silently",
            hint="Fill in host, from-address (and credentials if needed) in Settings.",
        )
    return DoctorCheck(
        id="smtp", label="Email (SMTP)", status="skip",
        detail="Not configured. Email actions are unavailable",
    )


async def _check_disk() -> DoctorCheck:
    try:
        import psutil

        usage = await asyncio.to_thread(psutil.disk_usage, "/")
        free_gb = usage.free / (1024 ** 3)
        pct = usage.percent
        detail = f"{free_gb:.1f} GB free ({pct:.0f}% used)"
        if free_gb < 10 or pct > 90:
            return DoctorCheck(
                id="disk", label="Disk space", status="warn", detail=detail,
                hint="Recordings stop when the disk fills. Lower retention in Settings or free up space.",
            )
        return DoctorCheck(id="disk", label="Disk space", status="ok", detail=detail)
    except Exception as exc:
        return DoctorCheck(
            id="disk", label="Disk space", status="skip", detail=str(exc)[:100],
        )


async def _run_with_timeout(coro, check_id: str, label: str) -> DoctorCheck:
    try:
        return await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        return DoctorCheck(
            id=check_id, label=label, status="fail",
            detail=f"Check timed out after {_CHECK_TIMEOUT:.0f}s",
            hint="The service is not answering at all. Check its container logs.",
        )
    except Exception as exc:  # a broken check is itself a finding
        logger.exception("doctor check %s crashed", check_id)
        return DoctorCheck(id=check_id, label=label, status="fail", detail=str(exc)[:200])


@router.get("/system/doctor", response_model=list[DoctorCheck])
async def run_doctor(
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run all health checks concurrently and return structured verdicts."""
    cameras = (await db.execute(select(Camera))).scalars().all()
    providers = (
        (await db.execute(select(Provider).where(Provider.active.is_(True)))).scalars().all()
    )

    sem = asyncio.Semaphore(_CAMERA_CONCURRENCY)
    jobs = [
        _run_with_timeout(_check_db(db), "db", "Database"),
        _run_with_timeout(_check_redis(), "redis", "Redis"),
        _run_with_timeout(_check_mediamtx(), "mediamtx", "Stream relay (mediamtx)"),
        _run_with_timeout(_check_smtp(), "smtp", "Email (SMTP)"),
        _run_with_timeout(_check_disk(), "disk", "Disk space"),
    ]
    jobs += [
        _run_with_timeout(_check_camera(c, sem), f"camera:{c.id}", f"Camera: {c.name}")
        for c in cameras
    ]
    jobs += [
        _run_with_timeout(_check_provider(p), f"provider:{p.id}", f"AI provider: {p.name}")
        for p in providers
    ]
    return list(await asyncio.gather(*jobs))
