"""Tests for the job-based Ollama deploy flow (preflight, progress, cancel)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

import services.api.routes.ollama_deploy as od


@pytest.fixture(autouse=True)
def reset_job():
    od._current_job = None
    yield
    od._current_job = None


def make_user():
    class U:
        role = "admin"

    return U()


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_preflight_unknown_model_skips():
    assert od._preflight("some-custom-model") is None


def test_preflight_insufficient_ram():
    with patch.object(od, "_get_system_ram_gb", return_value=4.0), \
         patch.object(od, "_get_disk_free_gb", return_value=500.0):
        result = od._preflight("gemma3:27b")
    assert result is not None
    assert result.code == "insufficient_ram"
    assert "4 GB" in result.message


def test_preflight_insufficient_disk():
    with patch.object(od, "_get_system_ram_gb", return_value=64.0), \
         patch.object(od, "_get_disk_free_gb", return_value=3.0):
        result = od._preflight("gemma3:27b")
    assert result is not None
    assert result.code == "insufficient_disk"


def test_preflight_ok():
    with patch.object(od, "_get_system_ram_gb", return_value=64.0), \
         patch.object(od, "_get_disk_free_gb", return_value=500.0):
        assert od._preflight("gemma3:4b") is None


def test_preflight_unknown_sensors_pass():
    # When RAM/disk cannot be read, do not block the deploy.
    with patch.object(od, "_get_system_ram_gb", return_value=None), \
         patch.object(od, "_get_disk_free_gb", return_value=None):
        assert od._preflight("gemma3:27b") is None


def test_all_curated_models_have_disk_gb():
    for m in od.VISION_MODELS:
        assert isinstance(m.get("disk_gb"), (int, float)), m["name"]


# ---------------------------------------------------------------------------
# HTTP pull streaming progress
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self._status = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, json=None):
        return _FakeStreamResponse(self._lines, self._status)


@pytest.mark.asyncio
async def test_pull_via_http_updates_progress():
    lines = [
        json.dumps({"status": "pulling manifest"}),
        json.dumps({"status": "downloading", "total": 1000, "completed": 250}),
        json.dumps({"status": "downloading", "total": 1000, "completed": 1000}),
        json.dumps({"status": "success"}),
    ]
    job = od.DeployJob("gemma3:4b")
    with patch.object(od.httpx, "AsyncClient", return_value=_FakeClient(lines)):
        ok, msg = await od._pull_via_http("http://fake:11434", "gemma3:4b", job)
    assert ok is True
    assert job.progress == 100.0


@pytest.mark.asyncio
async def test_pull_via_http_error_line():
    lines = [json.dumps({"error": "manifest unknown"})]
    job = od.DeployJob("nope:1b")
    with patch.object(od.httpx, "AsyncClient", return_value=_FakeClient(lines)):
        ok, msg = await od._pull_via_http("http://fake:11434", "nope:1b", job)
    assert ok is False
    assert "manifest unknown" in msg


@pytest.mark.asyncio
async def test_pull_via_http_non_200():
    job = od.DeployJob("gemma3:4b")
    with patch.object(od.httpx, "AsyncClient", return_value=_FakeClient([], status_code=500)):
        ok, msg = await od._pull_via_http("http://fake:11434", "gemma3:4b", job)
    assert ok is False


# ---------------------------------------------------------------------------
# Job state machine via the endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_starts_background_job_and_completes():
    async def fake_pull(base_url, model, job):
        job.progress = 50.0
        return True, "ok"

    with patch.object(od, "_find_ollama_binary", return_value=None), \
         patch.object(od, "_detect_running", new=AsyncMock(return_value=("http://fake:11434", []))), \
         patch.object(od, "_pull_via_http", new=fake_pull), \
         patch.object(od, "_register_provider", new=AsyncMock(return_value="ready")), \
         patch.object(od, "_get_system_ram_gb", return_value=64.0), \
         patch.object(od, "_get_disk_free_gb", return_value=500.0):
        first = await od.deploy_model(od.DeployRequest(model="gemma3:4b"), make_user())
        assert first.stage == "pulling"
        await od._current_job.task
        status = await od.get_deploy_status(make_user())
    assert status.stage == "done"
    assert status.progress == 100.0


@pytest.mark.asyncio
async def test_deploy_already_installed_registers_synchronously():
    with patch.object(od, "_find_ollama_binary", return_value=None), \
         patch.object(
             od, "_detect_running",
             new=AsyncMock(return_value=("http://fake:11434", ["gemma3:4b"])),
         ), \
         patch.object(od, "_register_provider", new=AsyncMock(return_value="ready")):
        result = await od.deploy_model(od.DeployRequest(model="gemma3:4b"), make_user())
    assert result.stage == "done"
    assert od._current_job is None


@pytest.mark.asyncio
async def test_deploy_conflict_on_different_model():
    job = od.DeployJob("gemma3:12b")
    job.stage = "pulling"
    od._current_job = job
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await od.deploy_model(od.DeployRequest(model="gemma3:4b"), make_user())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deploy_same_model_returns_snapshot():
    job = od.DeployJob("gemma3:4b")
    job.stage = "pulling"
    job.progress = 42.0
    od._current_job = job
    result = await od.deploy_model(od.DeployRequest(model="gemma3:4b"), make_user())
    assert result.stage == "pulling"
    assert result.progress == 42.0


@pytest.mark.asyncio
async def test_deploy_preflight_blocks_pull():
    with patch.object(od, "_find_ollama_binary", return_value=None), \
         patch.object(od, "_detect_running", new=AsyncMock(return_value=("http://fake:11434", []))), \
         patch.object(od, "_get_system_ram_gb", return_value=2.0), \
         patch.object(od, "_get_disk_free_gb", return_value=500.0):
        result = await od.deploy_model(od.DeployRequest(model="gemma3:27b"), make_user())
    assert result.stage == "error"
    assert result.code == "insufficient_ram"
    assert od._current_job is None


@pytest.mark.asyncio
async def test_cancel_deploy():
    started = asyncio.Event()

    async def slow_pull(base_url, model, job):
        started.set()
        await asyncio.sleep(60)
        return True, "ok"

    with patch.object(od, "_find_ollama_binary", return_value=None), \
         patch.object(od, "_detect_running", new=AsyncMock(return_value=("http://fake:11434", []))), \
         patch.object(od, "_pull_via_http", new=slow_pull), \
         patch.object(od, "_get_system_ram_gb", return_value=64.0), \
         patch.object(od, "_get_disk_free_gb", return_value=500.0):
        first = await od.deploy_model(od.DeployRequest(model="gemma3:4b"), make_user())
        assert first.stage == "pulling"
        await started.wait()
        result = await od.cancel_deploy(make_user())
    assert result.stage == "cancelled"


@pytest.mark.asyncio
async def test_cancel_when_idle():
    result = await od.cancel_deploy(make_user())
    assert result.stage == "idle"


@pytest.mark.asyncio
async def test_status_when_idle():
    result = await od.get_deploy_status(make_user())
    assert result.stage == "idle"


@pytest.mark.asyncio
async def test_invalid_model_name():
    result = await od.deploy_model(od.DeployRequest(model="../evil"), make_user())
    assert result.stage == "error"
    assert result.code == "invalid_model"
