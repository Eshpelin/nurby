"""Tests for the FindAnything deep-scan job (P1).

Exercises run_scan end-to-end with a fake grounding client, a fake frame
loader, and a monkeypatched index pre-filter. No GPU, no DB.
"""

import numpy as np
import pytest

import services.search.query as query_mod
import services.search.scan as scan_mod
from services.search.scan import ScanJob, ScanRegistry, ScanRouted, classify_intent

# ── fakes ────────────────────────────────────────────────────────────────

class _Box:
    bbox_norm = (0.1, 0.1, 0.2, 0.2)
    is_point = False
    label = "thing"


class _Result:
    def __init__(self, found, *, error=None, leaves=False):
        self.found = found
        self.boxes = [_Box()] if found else []
        self.error = error
        self.leaves_privacy_boundary = leaves


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def ground(self, frame, prompt, interactive=True):
        self.calls += 1
        return self.result


def _candidate(i):
    return {
        "id": f"obs-{i}",
        "camera_id": f"cam-{i % 2}",
        "camera_name": f"Camera {i % 2}",
        "started_at": "2026-06-19T10:00:00+00:00",
        "thumbnail_path": f"/data/thumbnails/{i}.jpg",
    }


def _patch_candidates(monkeypatch, candidates):
    async def fake_search(db, **kwargs):
        return candidates

    monkeypatch.setattr(query_mod, "search_observations", fake_search)

    async def no_route(db, query):
        return None

    monkeypatch.setattr(scan_mod, "classify_intent", no_route)
    # Default the persistent cache to "miss + no-op store" so tests don't hit a
    # DB; cache-specific tests override these.
    async def _miss(obs_id, prompt, rev):
        return None

    async def _noop_store(obs_id, prompt, rev, **kwargs):
        return None

    monkeypatch.setattr(scan_mod, "get_cached_grounding", _miss)
    monkeypatch.setattr(scan_mod, "store_grounding", _noop_store)


def _frame_ok(path):
    return np.zeros((10, 10, 3), dtype=np.uint8)


# ── run_scan ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_scan_finds_boxes(monkeypatch):
    _patch_candidates(monkeypatch, [_candidate(0), _candidate(1)])
    job = ScanJob(id="j1", user_id="u1", query="red ladder")
    client = _Client(_Result(found=True))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )

    assert job.status == "done"
    assert job.total == 2
    assert job.scanned == 2
    assert job.found == 2
    assert client.calls == 2
    assert len(job.results) == 2
    assert job.results[0].boxes[0]["label"] == "thing"
    assert "Found 2" in job.summary()
    assert len(job.cameras_seen) == 2


@pytest.mark.asyncio
async def test_run_scan_no_candidates(monkeypatch):
    _patch_candidates(monkeypatch, [])
    job = ScanJob(id="j2", user_id="u1", query="unicorn")
    client = _Client(_Result(found=True))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )

    assert job.status == "done"
    assert job.total == 0
    assert client.calls == 0
    assert "No match" in job.summary()


@pytest.mark.asyncio
async def test_run_scan_no_match(monkeypatch):
    _patch_candidates(monkeypatch, [_candidate(0)])
    job = ScanJob(id="j3", user_id="u1", query="zebra")
    client = _Client(_Result(found=False))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )

    assert job.status == "done"
    assert job.scanned == 1
    assert job.found == 0
    assert job.results == []
    assert "No match" in job.summary()


@pytest.mark.asyncio
async def test_run_scan_routes_person(monkeypatch):
    async def fake_search(db, **kwargs):
        raise AssertionError("must not pre-filter when routed to person")

    monkeypatch.setattr(query_mod, "search_observations", fake_search)

    async def route(db, query):
        return ScanRouted(kind="person", name="Leo", message="Leo is a known person.")

    monkeypatch.setattr(scan_mod, "classify_intent", route)

    job = ScanJob(id="j4", user_id="u1", query="find Leo")
    client = _Client(_Result(found=True))
    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )

    assert job.status == "done"
    assert job.routed is not None
    assert job.routed.name == "Leo"
    assert client.calls == 0
    assert "known person" in job.summary()


@pytest.mark.asyncio
async def test_run_scan_skips_unloadable_frames(monkeypatch):
    _patch_candidates(monkeypatch, [_candidate(0), _candidate(1)])
    job = ScanJob(id="j5", user_id="u1", query="cat")
    client = _Client(_Result(found=True))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=lambda p: None,
    )

    assert job.status == "done"
    assert job.scanned == 2
    assert client.calls == 0  # nothing was loadable to ground
    assert job.found == 0


@pytest.mark.asyncio
async def test_run_scan_caps_max_frames(monkeypatch):
    # 100 candidates requested but the global cap clamps the pre-filter limit.
    captured = {}

    async def fake_search(db, **kwargs):
        captured["limit"] = kwargs.get("limit")
        return []

    monkeypatch.setattr(query_mod, "search_observations", fake_search)

    async def no_route(db, query):
        return None

    monkeypatch.setattr(scan_mod, "classify_intent", no_route)

    from shared.config import settings

    job = ScanJob(id="j6", user_id="u1", query="x")
    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10_000, client=_Client(_Result(False)), frame_loader=_frame_ok,
    )
    assert captured["limit"] == settings.grounding_max_frames


@pytest.mark.asyncio
async def test_run_scan_tops_up_recent_for_novel_query(monkeypatch):
    # The index knows nothing about a novel term, but recent frames exist.
    # FindAnything must still scan them (that's its whole point, §3.3).
    async def fake_search(db, query=None, **kwargs):
        return [] if query else [_candidate(0), _candidate(1)]

    monkeypatch.setattr(query_mod, "search_observations", fake_search)

    async def no_route(db, q):
        return None

    monkeypatch.setattr(scan_mod, "classify_intent", no_route)

    async def _miss(*a, **k):
        return None

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(scan_mod, "get_cached_grounding", _miss)
    monkeypatch.setattr(scan_mod, "store_grounding", _noop)

    job = ScanJob(id="t1", user_id="u1", query="chicken")
    client = _Client(_Result(found=True))
    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )
    assert job.scanned == 2  # recent frames grounded despite zero text match
    assert client.calls == 2
    assert job.found == 2


# ── persistent cache wiring ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_scan_uses_cache_hit(monkeypatch):
    _patch_candidates(monkeypatch, [_candidate(0)])

    async def hit(obs_id, prompt, rev):
        return {"found": True, "corroborated": False, "count": 1,
                "boxes": [{"bbox_norm": [0.1, 0.1, 0.2, 0.2], "is_point": False, "label": "x"}]}

    monkeypatch.setattr(scan_mod, "get_cached_grounding", hit)
    job = ScanJob(id="c1", user_id="u1", query="cat")
    client = _Client(_Result(found=True))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )
    assert job.found == 1
    assert client.calls == 0  # cache hit, GPU never touched
    assert job.results[0].boxes[0]["label"] == "x"


@pytest.mark.asyncio
async def test_run_scan_stores_on_miss(monkeypatch):
    _patch_candidates(monkeypatch, [_candidate(0)])
    stored = {}

    async def capture_store(obs_id, prompt, rev, **kwargs):
        stored["found"] = kwargs.get("found")
        stored["boxes"] = kwargs.get("boxes")

    monkeypatch.setattr(scan_mod, "store_grounding", capture_store)
    job = ScanJob(id="c2", user_id="u1", query="cat")
    client = _Client(_Result(found=True))

    await scan_mod.run_scan(
        job, camera_id=None, time_from=None, time_to=None,
        max_frames=10, client=client, frame_loader=_frame_ok,
    )
    assert client.calls == 1
    assert stored["found"] is True
    assert isinstance(stored["boxes"], list)


# ── classify_intent ───────────────────────────────────────────────────────

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _DB:
    def __init__(self, names):
        self._names = names

    async def execute(self, stmt):
        return _Rows([(n,) for n in self._names])


@pytest.mark.asyncio
async def test_classify_intent_known_person_routes():
    routed = await classify_intent(_DB(["Leo", "Mom"]), "find Leo in the backyard")
    assert routed is not None
    assert routed.kind == "person"
    assert routed.name == "Leo"


@pytest.mark.asyncio
async def test_classify_intent_thing_does_not_route():
    routed = await classify_intent(_DB(["Leo"]), "a red ladder by the shed")
    assert routed is None


@pytest.mark.asyncio
async def test_classify_intent_substring_does_not_falsematch():
    # "art" must not match inside "cart".
    routed = await classify_intent(_DB(["Art"]), "a shopping cart")
    assert routed is None


# ── registry ───────────────────────────────────────────────────────────────

def test_registry_one_active_per_user():
    reg = ScanRegistry()
    j1 = reg.create("u1", "q1")
    assert reg.active_for_user("u1") is j1
    j1.status = "done"
    assert reg.active_for_user("u1") is None


def test_registry_get_and_isolation():
    reg = ScanRegistry()
    j = reg.create("u1", "q")
    assert reg.get(j.id) is j
    assert reg.get("nope") is None
