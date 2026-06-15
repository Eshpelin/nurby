"""Deeper coverage for services/search/query.py.

Exercises the real search orchestration in ``search_observations`` with a
recording FakeDB so we cover the four-strategy fallback ladder
(vector -> label/keyword -> regex -> recent), the merge/dedup of label and
vector hits, synonym expansion, person-name canonical resolution, the
people-intent fallback in ``answer_question``, and result shaping. No real
DB, embeddings, or LLM are touched; the embedding + provider seams are
monkeypatched.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.search import query as search_query

# ── FakeDB that returns canned scalar rows per call ──
#
# search_observations issues up to four ``db.execute`` calls depending on
# which strategy fires. We hand the FakeDB an ordered list of result sets;
# each ``execute`` pops the next one. ``camera`` lookups are answered from a
# separate map so the count of "search" executes stays predictable.


def _obs(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        started_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
        object_detections={"objects": []},
        person_detections=None,
        vlm_description="a quiet porch",
        confidence=0.7,
        thumbnail_path=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class _Result:
    """Mimics the bits of a SQLAlchemy Result the search code uses."""

    def __init__(self, rows, *, pairs=None):
        # rows -> objects for .scalars().all()
        # pairs -> list of (obj, distance) tuples for .all()
        self._rows = rows
        self._pairs = pairs

    def scalars(self):
        return self

    def all(self):
        if self._pairs is not None:
            return self._pairs
        return self._rows


class _FakeDB:
    """Replays a queue of result sets and records every statement.

    Camera-name resolution is special-cased: the search code calls
    ``_resolve_camera_names`` last, and we answer it from ``camera_rows``
    regardless of the queue so the queue only models *search* executes.
    """

    def __init__(self, results, camera_rows=None):
        self._queue = list(results)
        self._camera_rows = camera_rows or []
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        text = str(stmt).lower()
        # The camera-name resolution query selects from the cameras table.
        if "from cameras" in text or "camera" in text and "observation" not in text:
            return _Result(self._camera_rows)
        if self._queue:
            return self._queue.pop(0)
        return _Result([])


def _cam(cid, name):
    return SimpleNamespace(id=cid, name=name)


@pytest.fixture(autouse=True)
def _no_embeddings(monkeypatch):
    """Default: embeddings unavailable, so vector strategy is skipped and the
    code drops to keyword/regex paths. Individual tests can override."""

    async def _none(_text):
        return None

    monkeypatch.setattr(search_query, "_embed_query", _none)
    yield


# ── _is_people_intent ──────────────────────────────────────────────


def test_people_intent_matches_varied_phrasings():
    assert search_query._is_people_intent("Who came by today?") is True
    assert search_query._is_people_intent("any visitors this morning") is True
    assert search_query._is_people_intent("Did anyone arrive?") is True
    assert search_query._is_people_intent("was an intruder spotted") is True


def test_people_intent_negative_and_word_boundaries():
    # "personnel" contains "person" as a substring but \w+ tokenizes whole
    # words, so it must NOT trigger people intent.
    assert search_query._is_people_intent("show me the personnel roster") is False
    assert search_query._is_people_intent("any motion in the garage") is False
    assert search_query._is_people_intent("") is False
    assert search_query._is_people_intent(None) is False


# ── _build_observation_dict ────────────────────────────────────────


def test_build_observation_dict_serializes_all_fields():
    cam_id = uuid.uuid4()
    oid = uuid.uuid4()
    obs = _obs(id=oid, camera_id=cam_id, vlm_description="dog on lawn")
    out = search_query._build_observation_dict(obs, {cam_id: "Backyard"})
    assert out["id"] == str(oid)
    assert out["camera_id"] == str(cam_id)
    assert out["camera_name"] == "Backyard"
    assert out["vlm_description"] == "dog on lawn"
    assert out["started_at"].startswith("2026-06-11T12:00")


def test_build_observation_dict_unknown_camera():
    obs = _obs()
    assert search_query._build_observation_dict(obs, {})["camera_name"] == "Unknown"


# ── _resolve_camera_names ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_camera_names_empty_set_short_circuits():
    db = _FakeDB([], camera_rows=[_cam(uuid.uuid4(), "X")])
    out = await search_query._resolve_camera_names(db, set())
    assert out == {}
    # No DB call when the id set is empty.
    assert db.calls == 0


@pytest.mark.asyncio
async def test_resolve_camera_names_builds_id_to_name_map():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    db = _FakeDB([], camera_rows=[_cam(c1, "Front"), _cam(c2, "Garage")])
    out = await search_query._resolve_camera_names(db, {c1, c2})
    assert out == {c1: "Front", c2: "Garage"}


# ── search_observations: keyword strategy ──────────────────────────


@pytest.mark.asyncio
async def test_search_observations_keyword_strategy_returns_label_hits():
    cam = uuid.uuid4()
    hit = _obs(camera_id=cam, vlm_description="a dog runs by")
    db = _FakeDB(
        results=[_Result([hit])],  # label/keyword strategy result
        camera_rows=[_cam(cam, "Yard")],
    )
    out = await search_query.search_observations(db, query="dog", limit=10)
    assert len(out) == 1
    assert out[0]["camera_name"] == "Yard"
    assert out[0]["vlm_description"] == "a dog runs by"


@pytest.mark.asyncio
async def test_search_observations_dedups_label_and_vector(monkeypatch):
    """A row found by both vector and label search appears once, label-first."""

    async def _embed(_text):
        return [0.1] * 8  # any non-zero vector enables the vector strategy

    monkeypatch.setattr(search_query, "_embed_query", _embed)

    cam = uuid.uuid4()
    shared = _obs(camera_id=cam, vlm_description="cat naps")
    vector_only = _obs(camera_id=cam, vlm_description="bird flies")

    db = _FakeDB(
        results=[
            # Strategy 1: vector results as (obj, distance) pairs.
            _Result([], pairs=[(shared, 0.10), (vector_only, 0.20)]),
            # Strategy 2: label results, scalars().all().
            _Result([shared]),
        ],
        camera_rows=[_cam(cam, "Den")],
    )
    out = await search_query.search_observations(db, query="cat", limit=10)
    ids = [o["id"] for o in out]
    # shared appears once and first (label hits rank ahead of vector).
    assert ids == [str(shared.id), str(vector_only.id)]


@pytest.mark.asyncio
async def test_search_observations_vector_drops_low_similarity(monkeypatch):
    """Rows past the 0.85 cosine-distance threshold are filtered out."""

    async def _embed(_text):
        return [0.5] * 8

    monkeypatch.setattr(search_query, "_embed_query", _embed)

    cam = uuid.uuid4()
    good = _obs(camera_id=cam, vlm_description="close match")
    far = _obs(camera_id=cam, vlm_description="far match")

    db = _FakeDB(
        results=[
            _Result([], pairs=[(good, 0.30), (far, 0.95)]),  # far > 0.85
            _Result([]),  # label strategy finds nothing
        ],
        camera_rows=[_cam(cam, "Cam")],
    )
    out = await search_query.search_observations(db, query="match", limit=10)
    assert [o["id"] for o in out] == [str(good.id)]


@pytest.mark.asyncio
async def test_search_observations_regex_fallback_when_nothing_found():
    """When vector+label produce nothing, the broad regex fallback runs and
    its rows are returned."""
    cam = uuid.uuid4()
    fallback_hit = _obs(camera_id=cam, vlm_description="unusual term")
    db = _FakeDB(
        results=[
            _Result([]),  # label strategy: empty
            _Result([fallback_hit]),  # regex fallback: hit
        ],
        camera_rows=[_cam(cam, "Side")],
    )
    out = await search_query.search_observations(db, query="zylophone", limit=10)
    assert [o["id"] for o in out] == [str(fallback_hit.id)]


@pytest.mark.asyncio
async def test_search_observations_no_query_returns_recent():
    """With no query at all, only the recent-with-filters branch runs."""
    cam = uuid.uuid4()
    recent = [_obs(camera_id=cam), _obs(camera_id=cam)]
    db = _FakeDB(
        results=[_Result(recent)],
        camera_rows=[_cam(cam, "Hall")],
    )
    out = await search_query.search_observations(db, query=None, limit=10)
    assert len(out) == 2
    assert all(o["camera_name"] == "Hall" for o in out)


@pytest.mark.asyncio
async def test_search_observations_person_name_resolves_canonical(monkeypatch):
    """A typed nickname is reverse-mapped to canonical names before the JSON
    person_detections filter is built."""
    seen = {}

    async def _resolve(_db, name):
        seen["name"] = name
        return ["Salma Bekom"]

    monkeypatch.setattr(
        "shared.person_alias.resolve_name_to_canonical", _resolve
    )

    cam = uuid.uuid4()
    db = _FakeDB(
        results=[_Result([_obs(camera_id=cam)])],
        camera_rows=[_cam(cam, "Door")],
    )
    out = await search_query.search_observations(db, query=None, person_name="mommy", limit=10)
    assert seen["name"] == "mommy"
    assert len(out) == 1


# ── _recent_people_observations ────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_people_observations_returns_rows():
    cam = uuid.uuid4()
    rows = [_obs(camera_id=cam, person_detections={"faces": [{"cluster_id": "c1"}]})]
    db = _FakeDB(results=[_Result(rows)])
    out = await search_query._recent_people_observations(db, hours=24, limit=30)
    assert out == rows


# ── answer_question: short-circuits without heavy mocking ──────────


@pytest.mark.asyncio
async def test_answer_question_no_results_returns_helpful_message(monkeypatch):
    db = _FakeDB(results=[_Result([])])  # search finds nothing

    out = await search_query.answer_question(db, "what happened?")
    assert out["sources"] == []
    assert "No matching observations" in out["answer"]


@pytest.mark.asyncio
async def test_answer_question_people_intent_appends_recent(monkeypatch):
    """A people-intent question with no keyword hits still surfaces recent
    person observations via the fallback, and with no provider configured it
    returns sources + a 'no VLM' note rather than calling an LLM."""
    cam = uuid.uuid4()
    recent_obs = _obs(
        camera_id=cam,
        person_detections={"faces": []},
        object_detections={"objects": [{"label": "person"}]},
    )

    db = _FakeDB(
        results=[
            _Result([]),  # search_observations label strategy: empty
            _Result([]),  # regex fallback: empty
            _Result([recent_obs]),  # _recent_people_observations
            _Result([], pairs=[]),  # Person alias rows (display_name, nickname)
        ],
        camera_rows=[_cam(cam, "Porch")],
    )

    # Force "no provider" so answer_question returns the sources envelope
    # instead of attempting an LLM call.
    async def _no_vlm():
        return None

    monkeypatch.setattr(
        "services.perception.vlm.get_active_provider", _no_vlm, raising=False
    )

    async def _no_embed_provider():
        return None

    monkeypatch.setattr(search_query, "get_embedding_provider", _no_embed_provider, raising=False)
    monkeypatch.setattr(
        "services.search.embeddings.get_embedding_provider",
        _no_embed_provider,
        raising=False,
    )

    out = await search_query.answer_question(db, "who came by?")
    assert out["answer"] is None
    assert out["sources"], "expected the recent person observation surfaced"
    assert out["sources"][0]["id"] == str(recent_obs.id)
    assert "No VLM provider" in out.get("note", "")
