"""Regression tests for the search digest fallback and period label.

F37: when the VLM provider is unreachable the fallback summary must say
AI descriptions are unavailable instead of "Quiet period. nothing
notable" while detections exist.

F39: a 24h digest crossing midnight must include the end date in
period_label instead of rendering a zero-width range like
"Jul 11 15:59 to 15:59".

No real DB. a FakeDB replays the query results generate_digest asks for,
in order: observations, cameras, person aliases, (optional cluster
names), pending unknown clusters.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.search import digest as digest_mod


class _Result:
    """Supports both .all() and .scalars().all()."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)

    async def execute(self, stmt):
        return _Result(self._queue.pop(0))


CAM_ID = uuid.uuid4()
NOW = datetime(2026, 7, 12, 15, 59, tzinfo=timezone.utc)


def _obs(started_at, labels=("car", "person")):
    return SimpleNamespace(
        camera_id=CAM_ID,
        started_at=started_at,
        ended_at=None,
        object_detections={"objects": [{"label": lb} for lb in labels]},
        person_detections=None,
        vlm_description=None,
    )


def _db_with_observations(observations):
    camera = SimpleNamespace(id=CAM_ID, name="Front Door")
    return _FakeDB([
        observations,      # observations query
        [camera],          # cameras query
        [],                # person alias rows
        [],                # pending unknown clusters
    ])


@pytest.mark.asyncio
async def test_provider_error_fallback_names_detections(monkeypatch):
    async def _boom(provider, system_prompt, user_prompt):
        raise ConnectionError("provider offline")

    monkeypatch.setattr(digest_mod, "_call_text_llm", _boom)

    observations = [_obs(NOW - timedelta(hours=2)) for _ in range(30)]
    result = await digest_mod.generate_digest(
        _db_with_observations(observations),
        period="24h",
        target_time=NOW,
        provider=SimpleNamespace(kind="openai"),
    )

    assert result["ai_unavailable_reason"] == "provider_error"
    summary = result["summary"]
    assert "Quiet period" not in summary
    assert "could not be reached" in summary
    assert "Front Door" in summary
    assert "car" in summary


@pytest.mark.asyncio
async def test_no_provider_fallback_says_not_configured():
    observations = [_obs(NOW - timedelta(hours=3))]
    result = await digest_mod.generate_digest(
        _db_with_observations(observations),
        period="24h",
        target_time=NOW,
        provider=None,
    )

    assert result["ai_unavailable_reason"] == "no_provider"
    assert "No AI provider is configured" in result["summary"]
    assert "Quiet period" not in result["summary"]


@pytest.mark.asyncio
async def test_period_label_includes_end_date_across_midnight():
    observations = [_obs(NOW - timedelta(hours=1))]
    result = await digest_mod.generate_digest(
        _db_with_observations(observations),
        period="24h",
        target_time=NOW,
        provider=None,
    )
    assert result["period_label"] == "Jul 11 15:59 to Jul 12 15:59"


@pytest.mark.asyncio
async def test_period_label_same_day_keeps_short_form():
    now = datetime(2026, 7, 12, 15, 59, tzinfo=timezone.utc)
    observations = [_obs(now - timedelta(minutes=30))]
    result = await digest_mod.generate_digest(
        _db_with_observations(observations),
        period="1h",
        target_time=now,
        provider=None,
    )
    assert result["period_label"] == "14:59 to 15:59"
