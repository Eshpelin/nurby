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
    result = await doctor._check_camera(cam, asyncio.Semaphore(1))
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
        result = await doctor._check_camera(cam, asyncio.Semaphore(1))
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
