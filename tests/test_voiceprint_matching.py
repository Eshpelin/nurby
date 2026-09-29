from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import services.perception.audio.voiceprint as voiceprint
from services.perception.audio.voiceprint import select_voiceprint_match


def test_voiceprint_match_requires_threshold():
    person_id = uuid4()
    assert select_voiceprint_match([(person_id, [1.0, 0.0])], [0.7, 0.7], threshold=0.99) is None


def test_voiceprint_match_rejects_ambiguous_top_two_profiles():
    first, second = uuid4(), uuid4()
    result = select_voiceprint_match(
        [(first, [1.0, 0.0]), (second, [0.99, 0.1])],
        [1.0, 0.0],
        threshold=0.8,
        margin=0.05,
    )
    assert result is None


def test_voiceprint_match_returns_separated_best_profile():
    first, second = uuid4(), uuid4()
    result = select_voiceprint_match(
        [(first, [1.0, 0.0]), (second, [0.0, 1.0])],
        [1.0, 0.0],
        threshold=0.8,
    )
    assert result is not None
    assert result[0] == first
    assert result[1] == 1.0


@pytest.mark.asyncio
async def test_voiceprint_matching_requires_deployment_opt_in(monkeypatch):
    monkeypatch.setattr(voiceprint, "get_setting", AsyncMock(return_value=False))

    result = await voiceprint.match_voiceprint(object(), object())

    assert result is None
