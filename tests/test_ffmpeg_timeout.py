"""_run_ffmpeg must not hang forever on a stalled subprocess.

Mirrors Frigate PR #22984 (enforce a python-level timeout on probe subprocesses).
"""

import asyncio

from services.perception.conversation_clip import _run_ffmpeg


def test_run_ffmpeg_times_out_and_kills():
    # `sleep` stands in for a stalled ffmpeg; the wrapper must return promptly.
    rc = asyncio.run(_run_ffmpeg(["sleep", "10"], timeout=0.5))
    assert rc == 124  # timeout sentinel, not a hang


def test_run_ffmpeg_normal_command_returns_zero():
    rc = asyncio.run(_run_ffmpeg(["true"], timeout=5))
    assert rc == 0
