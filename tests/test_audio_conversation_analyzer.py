"""Unit tests for native-audio conversation analysis (n2.0 scaffold)."""

from __future__ import annotations

import pytest

from services.perception.audio_conversation_analyzer import (
    _parse,
    analyze_conversation_audio,
    provider_supports_audio,
)


class _Prov:
    def __init__(self, kind, model="", api_key="k", supports_audio=None):
        self.kind = kind
        self.default_model = model
        self.api_key = api_key
        self.supports_audio = supports_audio


def test_ollama_does_not_support_audio():
    assert provider_supports_audio(_Prov("ollama", "gemma3:4b")) is False


def test_gemini_supports_audio():
    assert provider_supports_audio(_Prov("google", "gemini-2.0-flash")) is True


def test_openai_audio_model_supported():
    assert provider_supports_audio(_Prov("openai", "gpt-4o-audio-preview")) is True
    assert provider_supports_audio(_Prov("openai", "gpt-4o-mini")) is False


def test_explicit_flag_wins():
    assert provider_supports_audio(_Prov("ollama", "x", supports_audio=True)) is True


def test_none_provider():
    assert provider_supports_audio(None) is False


def test_parse_tolerates_fences_and_clamps_tone():
    raw = '```json\n{"speaker_count": 2, "tone": "ARGUMENT", "non_verbal": ["raised-voice"], "gist": "two people argue"}\n```'
    out = _parse(raw)
    assert out["speaker_count"] == 2
    assert out["tone"] == "argument"
    assert out["non_verbal"] == ["raised-voice"]
    assert out["gist"] == "two people argue"


def test_parse_rejects_unknown_tone():
    out = _parse('{"tone": "banana", "speaker_count": 1}')
    assert out["tone"] is None
    assert out["speaker_count"] == 1


def test_parse_garbage_returns_none():
    assert _parse("not json at all") is None
    assert _parse(None) is None


@pytest.mark.asyncio
async def test_analyze_is_noop_without_audio_provider(tmp_path):
    clip = tmp_path / "c.opus"
    clip.write_bytes(b"x")
    # ollama provider does not support audio -> no-op (keeps text summary)
    res = await analyze_conversation_audio(str(clip), "hello", _Prov("ollama", "gemma3:4b"))
    assert res is None


@pytest.mark.asyncio
async def test_analyze_noop_when_clip_missing():
    res = await analyze_conversation_audio("/no/such/clip.opus", "hi", _Prov("google", "gemini-2.0-flash"))
    assert res is None
