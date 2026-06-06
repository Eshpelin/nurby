"""Audio retention path resolution.

The opus-orphan bug was retention resolving audio blobs against the
recordings base (or relying on CWD). These pin the audio-specific
resolver to ``audio_storage_path`` so cleanup is CWD-independent.
"""

from __future__ import annotations

import os

from services.ingestion.retention import _resolve_audio_path
from shared.config import settings


def test_absolute_path_passes_through():
    p = "/var/lib/nurby/audio_clips/cam/2026-06-06/abc.opus"
    assert _resolve_audio_path(p) == p


def test_relative_with_dot_prefix_resolves_to_audio_base():
    base = os.path.abspath(settings.audio_storage_path)
    got = _resolve_audio_path("./audio_clips/cam/2026-06-06/abc.opus")
    assert got == os.path.join(base, "cam/2026-06-06/abc.opus")


def test_relative_without_dot_prefix_resolves_to_audio_base():
    base = os.path.abspath(settings.audio_storage_path)
    got = _resolve_audio_path("audio_clips/cam/day/x.opus")
    assert got == os.path.join(base, "cam/day/x.opus")


def test_none_is_none():
    assert _resolve_audio_path(None) is None


def test_resolves_under_audio_base_not_recordings_base():
    # The original bug pointed audio cleanup at the recordings tree.
    got = _resolve_audio_path("./audio_clips/cam/day/x.opus")
    assert os.path.abspath(settings.audio_storage_path) in got
    assert os.path.abspath(settings.recordings_path) not in got
