"""Versioned VLM prompt registry (#218).

Every VLM call outcome records which prompt produced it, so a caption, an
action label or an agent answer is attributable to an exact prompt text, and
a golden-set scorecard (#214) can read "prompt v2, model X: 91%". For that to
mean anything, the version must move whenever the prompt text moves.

Three layers:

- ``REGISTRY`` pins, per prompt key, the shipped default ``version`` and the
  ``sha`` of the text that version corresponds to. A drift test
  (``tests/test_prompt_registry.py``) compares each ``sha`` against the live
  constant; editing a prompt without bumping its version fails that test.
- ``EXTRA_VERSIONS`` holds other immutable versions of a key: retired texts
  (kept so a rollback is possible and old rows can still show their exact
  prompt) and candidates awaiting promotion.
- The ``prompt_versions`` app setting (``{key: version}``) picks which known
  version is active. Promotion and rollback are a change to that setting,
  not a code edit. An unknown version in the setting is ignored and the
  shipped default is used.

The live prompt constants stay beside the code that uses them. They are
imported lazily here (the worker imports this module, so importing back at
load time would be circular).
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from hashlib import sha1

logger = logging.getLogger("nurby.perception.prompt_registry")


@dataclass(frozen=True)
class PromptSpec:
    version: str
    sha: str  # sha1(prompt_text)[:12] of the text this version corresponds to


@dataclass(frozen=True)
class PromptRef:
    """The exact prompt a VLM call used. Stamp all three onto the result."""

    key: str
    version: str
    text: str


# key -> shipped default version + the hash of the text it was cut from.
# Bump `version` AND update `sha` together whenever a prompt's text changes,
# and move the old text into EXTRA_VERSIONS so it stays selectable.
REGISTRY: dict[str, PromptSpec] = {
    "attributes": PromptSpec("v1", "504b16acffd2"),
    "anomaly": PromptSpec("v1", "b755c2dc9e3a"),
    "temporal": PromptSpec("v1", "a6b74f34b752"),
    "summary": PromptSpec("v1", "5dfff24ed103"),
    "verify": PromptSpec("v1", "9ba6cced7732"),
    "repair": PromptSpec("v1", "51e07ebdd0d4"),
    "live_caption": PromptSpec("v1", "e9a35764a62e"),
    "action_classify": PromptSpec("v1", "d12ff0aed987"),
    "agent_analyzer": PromptSpec("v1", "c7ec397a8581"),
}

# key -> {version: exact text}. Retired and candidate versions only; the
# shipped default's text is the live constant. Never edit a text here once
# it has been active: rows in the database point at it by version.
EXTRA_VERSIONS: dict[str, dict[str, str]] = {}

# Where each key's live (default-version) text lives.
_SOURCES: dict[str, tuple[str, str, str | None]] = {
    "attributes": ("services.perception.vlm_enrichment_worker", "LENS_PROMPTS", "attributes"),
    "anomaly": ("services.perception.vlm_enrichment_worker", "LENS_PROMPTS", "anomaly"),
    "temporal": ("services.perception.vlm_enrichment_worker", "LENS_PROMPTS", "temporal"),
    "summary": ("services.perception.vlm_enrichment_worker", "LENS_PROMPTS", "summary"),
    "verify": ("services.perception.vlm_enrichment_worker", "VERIFY_PROMPT", None),
    "repair": ("services.perception.vlm_enrichment_worker", "REPAIR_PROMPT", None),
    "live_caption": ("services.perception.vlm", "SYSTEM_PROMPT", None),
    "action_classify": ("services.perception.actions", "CLASSIFY_SYSTEM_PROMPT", None),
    "agent_analyzer": ("services.agent.analyzer", "ANALYZER_SYSTEM_PROMPT", None),
}

# Default version for any pass whose key is not in the registry. Recording
# "v0-unregistered" is more honest than pretending it is "v1".
UNREGISTERED = "v0-unregistered"

# App setting holding the active-version overrides.
SETTING_KEY = "prompt_versions"

# The setting is read on every VLM call, which is seconds of model time, so a
# short in-process cache is plenty. A promotion reaches every process within
# this window.
_OVERRIDES_TTL_S = 30.0
_overrides_cache: tuple[float, dict] | None = None


def content_hash(text: str) -> str:
    """The 12-hex sha1 prefix used as a prompt's content fingerprint."""
    return sha1((text or "").encode()).hexdigest()[:12]


def version_for(key: str) -> str:
    """The shipped default version for ``key`` (never raises)."""
    spec = REGISTRY.get(key)
    return spec.version if spec else UNREGISTERED


def live_text(key: str) -> str:
    """The text of ``key``'s shipped default version."""
    module, attr, sub = _SOURCES[key]
    value = getattr(importlib.import_module(module), attr)
    return value[sub] if sub is not None else value


def text_for(key: str, version: str) -> str | None:
    """Exact text of ``key`` at ``version``, or None when that version is
    not known. Old rows resolve through here, so retired versions stay."""
    spec = REGISTRY.get(key)
    if spec is None:
        return None
    if version == spec.version:
        return live_text(key)
    return EXTRA_VERSIONS.get(key, {}).get(version)


def known_versions(key: str) -> list[str]:
    spec = REGISTRY.get(key)
    if spec is None:
        return []
    extra = sorted(v for v in EXTRA_VERSIONS.get(key, {}) if v != spec.version)
    return [spec.version, *extra]


def select(key: str, overrides: dict | None = None) -> PromptRef:
    """The active prompt for ``key`` under ``overrides`` ({key: version}).

    Pure. An override naming an unknown version is ignored (with a warning)
    so a typo in the setting can never leave a call without a prompt."""
    default = version_for(key)
    wanted = (overrides or {}).get(key)
    if wanted and wanted != default:
        text = text_for(key, wanted)
        if text is not None:
            return PromptRef(key, wanted, text)
        logger.warning(
            "prompt_versions names unknown version %r for %s; using %s",
            wanted, key, default,
        )
    return PromptRef(key, default, live_text(key))


def custom(key: str, text: str) -> PromptRef:
    """Ref for a user-authored prompt (a camera's own VLM prompt). It is not
    in the registry, so its version is its content hash: still exact, and two
    captions from the same custom text share a version."""
    return PromptRef(f"{key}/custom", f"c-{content_hash(text)}", text)


def _valid_overrides(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k in REGISTRY and v}


async def active_overrides(*, fresh: bool = False) -> dict:
    """The ``prompt_versions`` setting, cached for a few seconds."""
    global _overrides_cache
    now = time.monotonic()
    if not fresh and _overrides_cache and now - _overrides_cache[0] < _OVERRIDES_TTL_S:
        return _overrides_cache[1]
    try:
        from shared.app_settings import get_setting

        overrides = _valid_overrides(await get_setting(SETTING_KEY, {}))
    except Exception:
        logger.debug("prompt_versions read failed; using defaults", exc_info=True)
        overrides = {}
    _overrides_cache = (now, overrides)
    return overrides


def invalidate_cache() -> None:
    global _overrides_cache
    _overrides_cache = None


async def resolve(key: str) -> PromptRef:
    """The active prompt for ``key``. Never raises for a registered key."""
    return select(key, await active_overrides())
