"""TTS provider protocol and registry (issue #154).

A direct copy of the shape in ``services/perception/audio/stt.py``:
providers are registered by ``kind`` through a factory, heavy imports
stay inside the factory bodies so a cold start does not pay for a
backend nobody configured, and the registry is module-level so routes
can list what exists without importing any of it.

Local by default, for the same reason STT is. A cloud voice sounds
better and leaves the house, and which of those a household wants is
their call rather than ours.

Synthesis is cached by ``(text, voice)``. An announcement repeats
verbatim thousands of times over a camera's life, and re-synthesizing
"please step back" on every fire is pure waste.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Awaitable, Callable, Protocol

from services.voice.types import AudioClip

logger = logging.getLogger("nurby.voice.tts")

# Utterances are short and few. A small cache covers a household's whole
# announcement vocabulary many times over.
DEFAULT_CACHE_SIZE = 64

# Refuse to synthesize an essay. A camera announcement is a sentence; a
# runaway template that interpolated a whole VLM description would
# otherwise tie up the speaker for minutes.
MAX_TEXT_CHARS = 500


class TTSProvider(Protocol):
    kind: str        # 'piper' | 'mock' | 'openai' | ...
    name: str        # human-readable, "piper en_US-amy-medium"
    model: str
    is_local: bool

    async def synthesize(self, text: str, voice: str | None = None) -> AudioClip: ...


_FACTORIES: dict[str, Callable[..., Awaitable[TTSProvider]]] = {}


def register_factory(kind: str, factory: Callable[..., Awaitable[TTSProvider]]) -> None:
    """Register a provider factory under its ``kind`` string."""
    _FACTORIES[kind] = factory


async def build_provider(kind: str, **kwargs) -> TTSProvider:
    """Resolve a registered provider by kind. Raises KeyError if missing."""
    if kind not in _FACTORIES:
        raise KeyError(f"unknown TTS provider kind. {kind}")
    return await _FACTORIES[kind](**kwargs)


def known_kinds() -> list[str]:
    return sorted(_FACTORIES.keys())


# ---- text guarding -------------------------------------------------------


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and cap length. Pure, for tests.

    Returns "" for anything with no speakable content, which callers
    treat as "do not speak" rather than synthesizing silence and playing
    it at somebody.
    """
    cleaned = " ".join((text or "").split())
    if len(cleaned) > MAX_TEXT_CHARS:
        cleaned = cleaned[:MAX_TEXT_CHARS].rsplit(" ", 1)[0]
    return cleaned


def cache_key(text: str, voice: str | None) -> str:
    """Stable key for a synthesized clip. Pure, for tests."""
    payload = f"{voice or ''}\x00{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SynthesisCache:
    """Bounded LRU of rendered clips. Not thread-safe by design: the
    voice path is asyncio on one loop, like the rest of perception."""

    def __init__(self, capacity: int = DEFAULT_CACHE_SIZE):
        self.capacity = max(1, capacity)
        self._entries: OrderedDict[str, AudioClip] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> AudioClip | None:
        clip = self._entries.get(key)
        if clip is None:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return clip

    def put(self, key: str, clip: AudioClip) -> None:
        self._entries[key] = clip
        self._entries.move_to_end(key)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


_cache = SynthesisCache()


def cache() -> SynthesisCache:
    return _cache


async def synthesize(
    provider: TTSProvider,
    text: str,
    voice: str | None = None,
    *,
    use_cache: bool = True,
) -> AudioClip | None:
    """Render ``text`` to audio, through the cache. None when there is
    nothing speakable to render."""
    cleaned = normalize_text(text)
    if not cleaned:
        return None

    key = cache_key(cleaned, voice or getattr(provider, "model", None))
    if use_cache:
        hit = _cache.get(key)
        if hit is not None:
            return hit

    clip = await provider.synthesize(cleaned, voice)
    if clip is None or not clip.pcm:
        return None
    if use_cache:
        _cache.put(key, clip)
    return clip


# Eager-register the always-available backends. Heavy imports live inside
# the factory bodies, exactly as the STT registry does it.


async def _piper_factory(
    model: str = "en_US-amy-medium",
    binary: str | None = None,
    model_path: str | None = None,
) -> TTSProvider:
    from services.voice.providers.piper_provider import PiperProvider

    return PiperProvider(model=model, binary=binary, model_path=model_path)


async def _mock_factory(
    model: str = "mock", sample_rate: int = 22050, tone_hz: float = 0.0
) -> TTSProvider:
    from services.voice.providers.mock_provider import MockTTSProvider

    return MockTTSProvider(model=model, sample_rate=sample_rate, tone_hz=tone_hz)


register_factory("piper", _piper_factory)
register_factory("mock", _mock_factory)
