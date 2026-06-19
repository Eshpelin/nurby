"""Tests for the FindAnything / visual grounding core (P0).

No GPU is touched: the parser, rescale, priority gate, and HTTP-seam client
are all exercised with canned ``<box>`` strings through the fakeable
``GroundingClient`` responder (design §10).
"""

import asyncio

import numpy as np
import pytest

from services.grounding import client as client_mod
from services.grounding.config import GroundingBackend
from services.grounding.gate import PriorityGate
from services.grounding.parse import parse_grounding_output

# ── parser ──────────────────────────────────────────────────────────────

def test_parse_basic_box():
    boxes = parse_grounding_output(
        "<box>100,200,300,400</box>", 1000, 1000, label="chicken", max_boxes=50
    )
    assert len(boxes) == 1
    b = boxes[0]
    assert b.bbox_px == (100, 200, 300, 400)
    assert b.bbox_norm == (0.1, 0.2, 0.3, 0.4)
    assert b.label == "chicken"
    assert b.is_point is False
    assert b.confidence is None  # never a fake score


def test_parse_reorders_swapped_corners():
    boxes = parse_grounding_output(
        "<box>300,400,100,200</box>", 1000, 1000, label="x", max_boxes=50
    )
    assert boxes[0].bbox_px == (100, 200, 300, 400)


def test_parse_clamps_out_of_range():
    boxes = parse_grounding_output(
        "<box>-50,0,2000,500</box>", 1000, 1000, label="x", max_boxes=50
    )
    assert boxes[0].bbox_px == (0, 0, 1000, 500)


def test_parse_drops_zero_area_box():
    boxes = parse_grounding_output(
        "<box>100,100,100,400</box>", 1000, 1000, label="x", max_boxes=50
    )
    assert boxes == []


def test_parse_point():
    boxes = parse_grounding_output(
        "<box>500,250</box>", 1000, 1000, label="dot", max_boxes=50
    )
    assert len(boxes) == 1
    assert boxes[0].is_point is True
    assert boxes[0].bbox_px == (500, 250, 500, 250)


def test_parse_multiple_and_max_cap():
    raw = "".join(f"<box>{i},{i},{i+10},{i+10}</box>" for i in range(10, 100, 10))
    boxes = parse_grounding_output(raw, 1000, 1000, label="x", max_boxes=3)
    assert len(boxes) == 3  # hard cap


def test_parse_truncated_token_dropped():
    # Output hit the token cap mid-box: 3 numbers, no close tag.
    boxes = parse_grounding_output(
        "<box>100,200,300", 1000, 1000, label="x", max_boxes=50
    )
    assert boxes == []


def test_parse_empty_is_not_found():
    assert parse_grounding_output("", 1000, 1000, label="x", max_boxes=50) == []
    assert parse_grounding_output(
        "I could not find anything.", 1000, 1000, label="x", max_boxes=50
    ) == []


def test_parse_prose_mixed_with_box():
    raw = "The chicken is over here <box>100,100,200,200</box> near the fence."
    boxes = parse_grounding_output(raw, 1000, 1000, label="chicken", max_boxes=50)
    assert len(boxes) == 1


def test_parse_rescales_to_image_dims():
    boxes = parse_grounding_output(
        "<box>0,0,1000,1000</box>", 1280, 720, label="x", max_boxes=50
    )
    assert boxes[0].bbox_px == (0, 0, 1280, 720)
    assert boxes[0].bbox_norm == (0.0, 0.0, 1.0, 1.0)


def test_parse_bad_dims_returns_empty():
    assert parse_grounding_output("<box>1,1,2,2</box>", 0, 0, label="x", max_boxes=5) == []


# ── priority gate ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_priority_gate_interactive_preempts_background():
    """Even when a background caller queues first, a later interactive caller
    is admitted ahead of it."""
    gate = PriorityGate(concurrency=1)
    order: list[str] = []
    release = asyncio.Event()

    async def hold():
        async with gate.slot(interactive=False):
            await release.wait()

    async def bg():
        async with gate.slot(interactive=False):
            order.append("bg")

    async def interactive():
        async with gate.slot(interactive=True):
            order.append("inter")

    ht = asyncio.create_task(hold())
    await asyncio.sleep(0.02)          # hold owns the only slot
    bt = asyncio.create_task(bg())     # background queues first
    await asyncio.sleep(0.02)
    it = asyncio.create_task(interactive())  # interactive queues second
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(ht, bt, it)

    assert order == ["inter", "bg"]


# ── client (HTTP seam, faked) ───────────────────────────────────────────

def _patch_enabled(monkeypatch, *, enabled=True, backend=None, mode="hybrid"):
    async def _is_enabled():
        return enabled

    async def _resolve_backend():
        return backend or GroundingBackend("http://grounding:8800", "local")

    async def _resolve_mode(override=None):
        return override or mode

    monkeypatch.setattr(client_mod, "is_enabled", _is_enabled)
    monkeypatch.setattr(client_mod, "resolve_backend", _resolve_backend)
    monkeypatch.setattr(client_mod, "resolve_mode", _resolve_mode)


def _frame():
    return np.zeros((120, 160, 3), dtype=np.uint8)


@pytest.mark.asyncio
async def test_client_disabled_returns_error(monkeypatch):
    _patch_enabled(monkeypatch, enabled=False)
    c = client_mod.GroundingClient(responder=lambda p, f: "<box>1,1,2,2</box>")
    res = await c.ground(_frame(), "chicken")
    assert res.found is False
    assert res.error and "disabled" in res.error


@pytest.mark.asyncio
async def test_client_grounds_via_responder(monkeypatch):
    _patch_enabled(monkeypatch)
    c = client_mod.GroundingClient(
        responder=lambda prompt, frame: "<box>100,100,500,500</box>"
    )
    res = await c.ground(_frame(), "a red chicken")
    assert res.found is True
    assert len(res.boxes) == 1
    assert res.boxes[0].label == "a red chicken"
    assert res.error is None
    assert res.backend == "local"


@pytest.mark.asyncio
async def test_client_empty_output_is_found_false_no_error(monkeypatch):
    _patch_enabled(monkeypatch)
    c = client_mod.GroundingClient(responder=lambda p, f: "nothing here")
    res = await c.ground(_frame(), "unicorn")
    assert res.found is False
    assert res.error is None  # a trustworthy "not found"


@pytest.mark.asyncio
async def test_client_caches_identical_request(monkeypatch):
    _patch_enabled(monkeypatch)
    calls = {"n": 0}

    def responder(prompt, frame):
        calls["n"] += 1
        return "<box>10,10,20,20</box>"

    c = client_mod.GroundingClient(responder=responder)
    frame = _frame()
    first = await c.ground(frame, "cat")
    second = await c.ground(frame, "cat")
    assert calls["n"] == 1
    assert first.cached is False
    assert second.cached is True
    assert second.found is True


@pytest.mark.asyncio
async def test_client_propagates_backend_error(monkeypatch):
    bad = GroundingBackend("", "remote", error="remote grounding URL refused: metadata")
    _patch_enabled(monkeypatch, backend=bad)
    c = client_mod.GroundingClient(responder=lambda p, f: "<box>1,1,2,2</box>")
    res = await c.ground(_frame(), "chicken")
    assert res.found is False
    assert "refused" in (res.error or "")


# ── config.resolve_backend SSRF + local default ─────────────────────────

@pytest.mark.asyncio
async def test_resolve_backend_remote_metadata_refused(monkeypatch):
    from services.grounding import config as cfg

    async def fake_get(key, default=None):
        return {
            "grounding_backend": "remote",
            "grounding_remote_url": "http://169.254.169.254/latest/meta-data/",
        }.get(key, default)

    monkeypatch.setattr("shared.app_settings.get_setting", fake_get)
    backend = await cfg.resolve_backend()
    assert backend.error is not None
    assert "refused" in backend.error


@pytest.mark.asyncio
async def test_resolve_backend_local_default(monkeypatch):
    from services.grounding import config as cfg
    from shared.config import settings

    async def fake_get(key, default=None):
        return {"grounding_backend": "local"}.get(key, default)

    monkeypatch.setattr("shared.app_settings.get_setting", fake_get)
    backend = await cfg.resolve_backend()
    assert backend.error is None
    assert backend.kind == "local"
    assert backend.base_url == settings.grounding_service_url.rstrip("/")
