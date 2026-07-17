"""Tests for the system doctor checks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.api.routes.doctor as doctor


@pytest.mark.asyncio
async def test_check_db_ok():
    db = AsyncMock()
    result = await doctor._check_db(db)
    assert result.status == "ok"
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_check_db_fail():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
    result = await doctor._check_db(db)
    assert result.status == "fail"
    assert "connection lost" in result.detail
    assert result.hint


@pytest.mark.asyncio
async def test_check_smtp_partial_warns():
    with patch(
        "shared.email.resolve_smtp",
        new=AsyncMock(return_value={"host": "smtp.x.io", "from_addr": None, "user": None}),
    ):
        result = await doctor._check_smtp()
    assert result.status == "warn"


@pytest.mark.asyncio
async def test_check_smtp_unconfigured_skips():
    with patch(
        "shared.email.resolve_smtp",
        new=AsyncMock(return_value={"host": None, "from_addr": None, "user": None}),
    ):
        result = await doctor._check_smtp()
    assert result.status == "skip"


@pytest.mark.asyncio
async def test_check_camera_skips_file_type():
    cam = MagicMock()
    cam.id = "x"
    cam.name = "Demo"
    cam.stream_type = "file"
    result = await doctor._check_camera(cam, asyncio.Semaphore(1), True)
    assert result.status == "skip"


@pytest.mark.asyncio
async def test_check_camera_unreachable():
    cam = MagicMock()
    cam.id = "x"
    cam.name = "Front"
    cam.stream_type = "rtsp"
    cam.stream_url = "rtsp://front.local/stream"
    with patch.object(
        doctor, "probe_tcp",
        return_value={"ok": False, "error_code": "dns", "detail": "Could not resolve front.local"},
    ):
        result = await doctor._check_camera(cam, asyncio.Semaphore(1), True)
    assert result.status == "fail"
    assert "resolve" in result.detail
    assert result.hint  # dns hint from ERROR_HINTS


@pytest.mark.asyncio
async def test_run_with_timeout_flags_hang():
    async def hang():
        await asyncio.sleep(60)

    with patch.object(doctor, "_CHECK_TIMEOUT", 0.05):
        result = await doctor._run_with_timeout(hang(), "redis", "Redis")
    assert result.status == "fail"
    assert "timed out" in result.detail


@pytest.mark.asyncio
async def test_check_provider_uses_shared_test():
    provider = MagicMock()
    provider.id = "p1"
    provider.name = "Ollama"
    fake = MagicMock(ok=False, message="model missing", latency_ms=12)
    with patch(
        "services.api.routes.providers.run_provider_test",
        new=AsyncMock(return_value=fake),
    ):
        result = await doctor._check_provider(provider)
    assert result.status == "fail"
    assert result.detail == "model missing"
    assert result.latency_ms == 12


@pytest.mark.asyncio
async def test_check_worker_reports_not_running():
    with patch.object(doctor.heartbeat, "last_beat", new=AsyncMock(return_value=None)):
        result = await doctor._check_worker(doctor.heartbeat.INGESTION)
    assert result.status == "fail"
    assert "Not running" in result.detail
    # The hint must name the thing to start, not send the user to their camera.
    assert "docker compose up -d ingestion" in result.hint


@pytest.mark.asyncio
async def test_check_worker_ok_when_beating():
    with patch.object(
        doctor.heartbeat, "last_beat", new=AsyncMock(return_value="2026-07-17T04:00:00+00:00")
    ):
        result = await doctor._check_worker(doctor.heartbeat.PERCEPTION)
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_check_worker_warns_when_redis_unreachable():
    # Can't-tell must not read as "the worker is dead".
    with patch.object(
        doctor.heartbeat, "last_beat", new=AsyncMock(side_effect=RuntimeError("no redis"))
    ):
        result = await doctor._check_worker(doctor.heartbeat.INGESTION)
    assert result.status == "warn"


@pytest.mark.asyncio
async def test_offline_camera_does_not_blame_user_when_ingestion_down():
    """The regression that made margaret's run untestable: with ingestion
    stopped, the doctor told the user to check their stream URL and
    credentials for a camera that was perfectly fine."""
    cam = MagicMock()
    cam.id = "x"
    cam.name = "Front Door"
    cam.stream_type = "rtsp"
    cam.stream_url = "rtsp://localhost:8554/front-door"
    cam.enabled = True
    cam.status = "offline"
    with patch.object(doctor, "probe_tcp", return_value={"ok": True}):
        result = await doctor._check_camera(cam, asyncio.Semaphore(1), ingestion_alive=False)
    assert result.status == "warn"
    assert "ingestion is not running" in result.detail
    assert "credentials" not in (result.hint or "")


@pytest.mark.asyncio
async def test_offline_camera_still_blames_camera_when_ingestion_up():
    """The flip side: with ingestion alive, an offline camera really is
    the camera's problem and should still say so."""
    cam = MagicMock()
    cam.id = "x"
    cam.name = "Front Door"
    cam.stream_type = "rtsp"
    cam.stream_url = "rtsp://localhost:8554/front-door"
    cam.enabled = True
    cam.status = "offline"
    with patch.object(doctor, "probe_tcp", return_value={"ok": True}):
        result = await doctor._check_camera(cam, asyncio.Semaphore(1), ingestion_alive=True)
    assert result.status == "fail"
    assert "credentials" in result.hint
